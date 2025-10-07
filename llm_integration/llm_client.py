# File: llm_integration/llm_client.py

import logging
import json
from typing import List, Dict, Any, Optional, TypedDict 
import httpx
from string import Template 
import asyncio
import re

logger = logging.getLogger(__name__)

# TypedDict definitions for structured LLM responses
class LLMClassification(TypedDict, total=False):
    Programming_Language: List[int] 
    Experience_Level: List[int]
    Operating_System: List[int]

class LLMVerificationResponse(TypedDict):
    classification: Optional[LLMClassification]
    message_to_user: str
    is_complete: bool
    user_has_confirmed: Optional[bool]
    unassignable_skills: Optional[List[Dict[str, str]]]


class LLMClient:
    def __init__(self, api_url: str, api_token: Optional[str], model_name: str, http_session: httpx.AsyncClient):
        self.api_url = api_url.rstrip('/') 
        self.api_token = api_token
        self.model_name = model_name
        self.http_session = http_session  
        logger.info(f"LLMClient initialized for model '{self.model_name}' at URL '{self.api_url}'")

    async def _make_llm_request(self, 
                                messages: List[Dict[str, str]], 
                                temperature: float = 0.5, 
                                max_tokens: int = 1536,
                                expect_json: bool = False 
                               ) -> Optional[Dict[str, Any]]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        final_temperature = temperature
        if "gpt-5" in self.model_name.lower():
            logger.debug(f"Model '{self.model_name}' is a gpt-5 variant. Forcing temperature to 1.0 as required.")
            final_temperature = 1.0

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": final_temperature,
            "max_tokens": max_tokens,
        }

        if expect_json:
             logger.info("Attempting to request JSON formatted response from LLM (if backend supports 'format: json').")

        request_url = self.api_url 
        logger.debug(f"Sending LLM request to {request_url} with payload: {json.dumps(payload, indent=2)}")

        try:
            response = await self.http_session.post(request_url, json=payload, headers=headers)
            logger.debug(f"LLM raw response status: {response.status_code}, headers: {response.headers}")
            response.raise_for_status()
            response_data = response.json()
            logger.debug(f"LLM raw response data (after json()): {json.dumps(response_data, indent=2)}")

            if 'message' in response_data and 'content' in response_data['message']:
                pass 
            elif 'choices' in response_data and response_data['choices'] and \
                 'message' in response_data['choices'][0] and 'content' in response_data['choices'][0]['message']:
                pass 
            else:
                logger.error(f"LLM response missing expected content structure. Response: {response_data}")
                return None
            return response_data
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API request failed with status {e.response.status_code}: {e.response.text}", exc_info=True)
        except httpx.TimeoutException as e:
            logger.error(f"LLM API request timed out: {e}", exc_info=True)
        except httpx.RequestError as e: 
            logger.error(f"LLM API request failed due to a network or connection error: {e}", exc_info=True)
        except json.JSONDecodeError: 
            response_text_for_log = "N/A"
            if 'response' in locals() and hasattr(response, 'text'):
                response_text_for_log = response.text
            logger.error(f"Failed to decode LLM API JSON response. Status (if available): {response.status_code if 'response' in locals() else 'N/A'}, Content: {response_text_for_log}", exc_info=True)
        except Exception as e: 
            logger.error(f"An unexpected error occurred during LLM request: {e}", exc_info=True)
        return None
    
    async def generate_new_user_summary(self, 
                                        conversation_history_text: str, 
                                        assigned_roles_names_str: str, 
                                        summary_prompt_template: str,
                                        conversation_language: str = "English"
                                       ) -> Optional[str]:
        logger.info(f"Generating new user summary. Conversation language: {conversation_language}")
        
        try:
            template = Template(summary_prompt_template)
            formatted_prompt = template.substitute(
                language=conversation_language, 
                conversation_history=conversation_history_text,
                assigned_roles_names_list=assigned_roles_names_str
            )
        except KeyError as e:
            logger.error(f"KeyError during new user summary prompt formatting! Missing key: {e.args[0]}", exc_info=True)
            return "Error: Could not generate summary due to a prompt formatting issue."
        except Exception as e:
            logger.error(f"Unexpected error formatting new user summary prompt: {e}", exc_info=True)
            return "Error: Could not generate summary due to an unexpected prompt issue."

        messages = [{"role": "system", "content": formatted_prompt}] 

        llm_response_data = await self._make_llm_request(messages, temperature=0.6, max_tokens=300)

        if llm_response_data:
            response_content_str: Optional[str] = None
            try:
                if "message" in llm_response_data and isinstance(llm_response_data["message"], dict) and \
                   "content" in llm_response_data["message"]:
                    response_content_str = llm_response_data["message"]["content"]
                elif "choices" in llm_response_data and isinstance(llm_response_data.get("choices"), list) and \
                     len(llm_response_data["choices"]) > 0 and isinstance(llm_response_data["choices"][0], dict) and \
                     "message" in llm_response_data["choices"][0] and \
                     isinstance(llm_response_data["choices"][0].get("message"), dict) and \
                     "content" in llm_response_data["choices"][0]["message"]:
                    response_content_str = llm_response_data["choices"][0]["message"]["content"]
                
                if response_content_str is not None:
                    return response_content_str.strip()
                else:
                    logger.warning(f"LLM response for new user summary content was None. Data: {llm_response_data}")
            except Exception as e:
                logger.error(f"Error processing LLM response for new user summary: {e}", exc_info=True)
        
        logger.warning("Failed to generate new user summary from LLM, returning None.")
        return None

    async def categorize_server_roles(self, roles_data: List[Dict[str, Any]], categorization_prompt: str) -> Dict[str, List[int]]:
        logger.info(f"Attempting to categorize {len(roles_data)} roles with LLM.")
        roles_list_str = "\n".join([f"- {role['name']} (ID: {role['id']})" for role in roles_data])
        formatted_prompt = f"{categorization_prompt}\n\nHere is the list of roles to categorize:\n{roles_list_str}\n\nPlease return ONLY the JSON object with categories as keys and lists of role NAMES as values. Example: {{ \"Programming Language\": [\"Python Developer\", \"Java Expert\"] }}"
        
        messages = [{"role": "system", "content": formatted_prompt}]
        llm_response_data = await self._make_llm_request(messages, temperature=0.1, max_tokens=2048, expect_json=True) 
        categorized_role_ids: Dict[str, List[int]] = {}

        if llm_response_data:
            response_content = ""
            try:
                if "message" in llm_response_data and "content" in llm_response_data["message"]:
                    response_content = llm_response_data["message"]["content"]
                elif llm_response_data.get("choices") and llm_response_data["choices"][0].get("message"):
                    response_content = llm_response_data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"Unexpected LLM response structure for role categorization: {llm_response_data}")
                    return categorized_role_ids 

                json_start_index = response_content.find('{')
                json_end_index = response_content.rfind('}') + 1
                if json_start_index != -1 and json_end_index != -1:
                    json_str = response_content[json_start_index:json_end_index]
                    parsed_categories_by_name = json.loads(json_str) 
                    role_name_to_id_map = {role['name'].lower(): role['id'] for role in roles_data}
                    for category, role_names in parsed_categories_by_name.items():
                        if not isinstance(role_names, list):
                            logger.warning(f"LLM returned non-list for role names in category '{category}': {role_names}")
                            continue
                        ids_for_category = []
                        for name in role_names:
                            if not isinstance(name, str):
                                logger.warning(f"LLM returned non-string role name in category '{category}': {name}")
                                continue
                            role_id = role_name_to_id_map.get(name.lower())
                            if role_id:
                                ids_for_category.append(role_id)
                            else:
                                logger.warning(f"LLM categorized role name '{name}' (category: {category}) not found in server roles or name mismatch.")
                        if ids_for_category:
                           categorized_role_ids[category] = ids_for_category
                    logger.info(f"Successfully categorized roles: {categorized_role_ids}")
                else:
                    logger.error(f"Could not find JSON in LLM response for role categorization: {response_content}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM response for role categorization: {e}. Response content: {response_content}", exc_info=True)
            except Exception as e:
                logger.error(f"Error processing LLM response for role categorization: {e}", exc_info=True)
        if not categorized_role_ids:
            logger.warning("Role categorization with LLM failed or returned no usable data.")
        return categorized_role_ids

    async def get_verification_guidance(self, user_message: str, conversation_history: List[Dict[str, str]], 
                                        categorized_server_roles: Dict[str, List[int]], 
                                        available_roles_map: Dict[int, str], 
                                        verification_prompt_template: str,
                                        max_retries: int = 2,
                                        retry_delay_seconds: int = 2
                                       ) -> Optional[LLMVerificationResponse]:
        logger.info(f"Getting verification guidance from LLM for user message: '{user_message}'")
        
        available_roles_text_parts = []
        for category, role_ids in categorized_server_roles.items():
            role_names_in_category = [f"'{available_roles_map.get(rid, str(rid))}' (ID: {rid})" for rid in role_ids if rid in available_roles_map]
            if role_names_in_category:
                available_roles_text_parts.append(f"- {category}: {', '.join(role_names_in_category)}")
        available_roles_text_list = "\n".join(available_roles_text_parts)
        if not available_roles_text_list:
            available_roles_text_list = "No specific skill/experience/OS roles are currently defined for classification."

        try:
            template = Template(verification_prompt_template)
            system_prompt_content = template.substitute(
                available_roles_text_list=available_roles_text_list
            )
        except KeyError as e:
            logger.error(f"KeyError during string.Template substitution! Missing key: {e.args[0]}", exc_info=True)
            return {"classification": None, "message_to_user": "Prompt error.", "is_complete": False, "user_has_confirmed": False, "unassignable_skills": None}
        except ValueError as e: 
            logger.error(f"ValueError during string.Template substitution (bad template syntax): {e}", exc_info=True)
            return {"classification": None, "message_to_user": "Prompt syntax error.", "is_complete": False, "user_has_confirmed": False, "unassignable_skills": None}

        messages = [{"role": "system", "content": system_prompt_content}]
        messages.extend(conversation_history) 
        messages.append({"role": "user", "content": user_message}) 

        # --- MODIFICATION START: IMPLEMENT 3-STEP RETRY LOGIC ---
        last_llm_response_content = "" # Store the raw content of the last failed response

        for attempt in range(max_retries + 1):
            logger.info(f"LLM guidance attempt {attempt + 1}/{max_retries + 1}")

            # On retries, add a corrective prompt to the message history for this attempt
            if attempt == 1: # First failure, begin self-correction
                logger.warning("LLM response was not valid JSON. Attempting self-correction prompt.")
                correction_prompt = {
                    "role": "assistant",
                    "content": f"SYSTEM: Your previous response was not valid JSON. The raw response was: ```{last_llm_response_content}```. Please re-format the entire response as a single, valid JSON object with no extra text or markdown."
                }
                messages.append(correction_prompt)
            elif attempt == 2: # Second failure, switch to strict mode
                logger.error("LLM self-correction failed. Switching to strict mode prompt.")
                strict_prompt = {
                    "role": "assistant",
                    "content": "SYSTEM: Your previous response was still not valid JSON. Output ONLY a minified JSON object with the required keys. Do not add explanations, do not use markdown, do not include any text before or after the braces."
                }
                messages.append(strict_prompt)


            llm_response_data = await self._make_llm_request(messages, temperature=0.3, max_tokens=1024, expect_json=True)
            
            if llm_response_data:
                response_content_str: Optional[str] = None
                try:
                    if "message" in llm_response_data and isinstance(llm_response_data["message"], dict) and "content" in llm_response_data["message"]:
                        response_content_str = llm_response_data["message"]["content"]
                    elif "choices" in llm_response_data and isinstance(llm_response_data.get("choices"), list) and \
                         len(llm_response_data["choices"]) > 0 and isinstance(llm_response_data["choices"][0], dict) and \
                         "message" in llm_response_data["choices"][0] and \
                         isinstance(llm_response_data["choices"][0].get("message"), dict) and \
                         "content" in llm_response_data["choices"][0]["message"]:
                        response_content_str = llm_response_data["choices"][0]["message"]["content"]
                    else:
                        logger.error(f"Attempt {attempt + 1}: Unexpected LLM response structure: {llm_response_data}")

                    if response_content_str is not None and isinstance(response_content_str, str):
                        last_llm_response_content = response_content_str # Store for potential correction
                        json_str = None
                        match = re.search(r"```json\s*(\{.*?\})\s*```", response_content_str, re.DOTALL | re.IGNORECASE)
                        if match:
                            json_str = match.group(1)
                        else:
                            json_start_index = response_content_str.find('{')
                            json_end_index = response_content_str.rfind('}') + 1
                            if json_start_index != -1 and json_end_index != -1 and json_start_index < json_end_index:
                                json_str = response_content_str[json_start_index:json_end_index]
                        
                        if json_str:
                            cleaned_json_str = json_str.strip()
                            cleaned_json_str = re.sub(r",\s*([\}\]])", r"\1", cleaned_json_str)
                            logger.debug(f"Attempt {attempt + 1}: Attempting to parse JSON: '{cleaned_json_str}'")
                            parsed_response = json.loads(cleaned_json_str)
                            
                            if all(key in parsed_response for key in ["message_to_user", "is_complete"]) and \
                               isinstance(parsed_response.get("user_has_confirmed"), bool):
                                if "classification" in parsed_response and parsed_response["classification"] is not None:
                                    if not isinstance(parsed_response["classification"], dict):
                                        logger.error(f"Attempt {attempt + 1}: LLM 'classification' field is not a dictionary.")
                                        parsed_response["classification"] = None
                                    else:
                                        for category_key in list(parsed_response["classification"].keys()):
                                            if isinstance(parsed_response["classification"][category_key], list):
                                                try:
                                                    valid_ids = [int(rid) for rid in parsed_response["classification"][category_key] if rid is not None]
                                                    parsed_response["classification"][category_key] = valid_ids
                                                except (ValueError, TypeError):
                                                    logger.error(f"Attempt {attempt + 1}: LLM returned non-integer/None role ID in {category_key}.")
                                                    parsed_response["classification"][category_key] = []
                                            else:
                                                logger.error(f"Attempt {attempt + 1}: LLM 'classification' for {category_key} is not a list.")
                                                parsed_response["classification"][category_key] = []
                                logger.info(f"Attempt {attempt + 1}: Successfully parsed verification guidance from LLM.")
                                return parsed_response # SUCCESS
                            else:
                                logger.error(f"Attempt {attempt + 1}: LLM JSON response missing required keys or 'user_has_confirmed' not bool. Parsed: {parsed_response}")
                                raise json.JSONDecodeError("Missing required keys in parsed JSON", cleaned_json_str, 0) 
                        else:
                             logger.error(f"Attempt {attempt + 1}: Could not find any JSON object in LLM response: '{response_content_str}'")
                    else: 
                        logger.error(f"Attempt {attempt + 1}: LLM response content was None or not a string. Full LLM data: {llm_response_data}")

                except json.JSONDecodeError as e:
                    logger.error(f"Attempt {attempt + 1}: Failed to parse JSON: {e}. Content: '{last_llm_response_content}'")
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1}: Error processing LLM response: {e}", exc_info=True)
            
            if attempt < max_retries:
                logger.info(f"Retrying LLM call in {retry_delay_seconds} seconds...")
                await asyncio.sleep(retry_delay_seconds)
            else:
                logger.error(f"All {max_retries + 1} attempts to get valid LLM guidance failed.")
        
        # --- MODIFICATION END ---

        logger.warning("Using fallback response for verification guidance after all retries.")
        fallback_response_defined: LLMVerificationResponse = {
            "classification": None,
            "message_to_user": "I'm currently having trouble processing information. Please try again in a few moments.",
            "is_complete": False,
            "user_has_confirmed": False, 
            "unassignable_skills": None
        }
        return fallback_response_defined

    async def generate_welcome_message(self, member_name: str, server_name: str, member_id: int, welcome_prompt_template_str: str) -> str:
        logger.info(f"Generating welcome message for '{member_name}' in server '{server_name}'")
        
        system_message_content: Optional[str] = None
        try:
            system_message_content = welcome_prompt_template_str.format(server_name=server_name, member_name=member_name, member_id=member_id)
        except KeyError as e:
            logger.error(f"Placeholder {e} missing in welcome_prompt_template (expected {{server_name}}). Using generic system prompt.")
            system_message_content = (
                "You are a friendly AI assistant. Generate a short, enthusiastic welcome message for a new Discord user. "
                "Acknowledge them by name and mention they might get a DM for role assignment."
            )
        except Exception as e:
            logger.error(f"Error formatting system prompt for welcome message: {e}", exc_info=True)
            system_message_content = "You are a friendly AI assistant. Generate a welcome message."

        user_message_content = f"A new user named '{member_name}' has just joined the server. Please generate their welcome message."

        messages = [
            {"role": "system", "content": system_message_content},
            {"role": "user", "content": user_message_content}
        ]
        
        llm_response_data = await self._make_llm_request(messages, temperature=0.7, max_tokens=150)
        
        fallback_text = f"Welcome to {server_name}, {member_name}! We're excited to have you here. You might receive a DM shortly to help assign some initial roles."

        if llm_response_data:
            response_content_str: Optional[str] = None
            try:
                if "message" in llm_response_data and \
                   isinstance(llm_response_data["message"], dict) and \
                   "content" in llm_response_data["message"]:
                    response_content_str = llm_response_data["message"]["content"]
                elif "choices" in llm_response_data and \
                     isinstance(llm_response_data.get("choices"), list) and \
                     len(llm_response_data["choices"]) > 0 and \
                     isinstance(llm_response_data["choices"][0], dict) and \
                     "message" in llm_response_data["choices"][0] and \
                     isinstance(llm_response_data["choices"][0].get("message"), dict) and \
                     "content" in llm_response_data["choices"][0]["message"]:
                    response_content_str = llm_response_data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"Unexpected LLM response structure for welcome message: {llm_response_data}")

                if response_content_str is not None and isinstance(response_content_str, str):
                    return response_content_str.strip()
                else:
                    logger.warning(f"LLM response content for welcome message was None or not a string. Data: {llm_response_data}")

            except Exception as e:
                logger.error(f"Error processing LLM response content for welcome message: {e}", exc_info=True)
                logger.debug(f"Problematic LLM response data for welcome message: {llm_response_data}")
        
        logger.warning("Failed to generate LLM welcome message or content was null/invalid, using fallback.")
        return fallback_text