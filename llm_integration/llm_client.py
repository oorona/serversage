# File: llm_integration/llm_client.py

import logging
import json
from typing import List, Dict, Any, Optional, TypedDict
import httpx
from string import Template
import asyncio
import os
import re
import time

logger = logging.getLogger(__name__)

# TypedDict definitions for structured LLM responses
class LLMClassification(TypedDict, total=False):
    Programming_Language: List[int]
    Experience_Level: List[int]
    Operating_System: List[int]
    Tool: List[int]
    Framework: List[int]

class LLMVerificationResponse(TypedDict):
    classification: Optional[LLMClassification]
    message_to_user: str
    is_complete: bool
    user_has_confirmed: Optional[bool]
    unassignable_skills: Optional[List[Dict[str, str]]]


class LLMClient:
    def __init__(self, api_url: str, api_token: Optional[str], model_name: str, http_session: httpx.AsyncClient, user_verification_schema_path: str, role_categorization_schema_path: str, request_timeout_seconds: Optional[int] = None):
        self.api_url = api_url.rstrip('/')
        self.api_token = api_token
        self.model_name = model_name
        self.http_session = http_session
        # per-request timeout to use when calling the LLM API (overrides session timeout per-call)
        self.request_timeout_seconds = request_timeout_seconds
        self.user_verification_schema = self._load_json_schema(user_verification_schema_path)
        self.role_categorization_schema = self._load_json_schema(role_categorization_schema_path)
        logger.info(f"LLMClient initialized for model '{self.model_name}' at URL '{self.api_url}'")
        # lightweight runtime metrics
        self.metrics: Dict[str, Any] = {
            'calls': 0,
            'truncated_responses': 0,
            'total_estimated_prompt_tokens': 0,
            'total_chars_sent': 0,
            'last_call_duration_s': None,
        }
        # default tunables (can be overridden by env or callers)
        try:
            self.default_max_tokens = int(os.getenv('DEFAULT_MAX_TOKENS', '4096'))
        except Exception:
            self.default_max_tokens = 4096
        # Welcome message tuning: can be overridden via environment
        try:
            self.welcome_temperature = float(os.getenv('WELCOME_TEMPERATURE', '0.7'))
        except Exception:
            self.welcome_temperature = 0.7
        self.welcome_hardcode = os.getenv('WELCOME_HARDCODE', 'false').lower() in ('1', 'true', 'yes')
        self.welcome_hardcode_message = os.getenv('WELCOME_HARDCODE_MESSAGE', '')
        try:
            self.welcome_max_prompt_chars = int(os.getenv('WELCOME_MAX_PROMPT_CHARS', '800'))
        except Exception:
            self.welcome_max_prompt_chars = 800
        try:
            self.welcome_max_response_tokens = int(os.getenv('WELCOME_MAX_RESPONSE_TOKENS', '1024'))
        except Exception:
            self.welcome_max_response_tokens = 1024

    def _load_json_schema(self, schema_path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(schema_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"JSON schema file not found at {schema_path}")
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {schema_path}")
        return None

    async def _make_llm_request(self,
                                messages: List[Dict[str, str]],
                                temperature: float = 0.5,
                                max_tokens: Optional[int] = None,
                                functions: Optional[List[Dict[str, Any]]] = None,
                                function_call: Optional[Dict[str, Any]] = None
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
            "max_tokens": max_tokens or self.default_max_tokens,
        }

        if functions:
            payload["functions"] = functions
        if function_call:
            payload["function_call"] = function_call

        request_url = self.api_url
        # Lightweight metrics: estimate prompt size (chars and rough token count)
        try:
            messages_text = "\n".join([m.get('content', '') for m in messages if isinstance(m, dict)])
        except Exception:
            messages_text = ''
        chars = len(messages_text)
        est_tokens = max(1, int(chars / 4))  # rough heuristic: 1 token ~ 4 chars
        self.metrics['calls'] += 1
        self.metrics['total_estimated_prompt_tokens'] += est_tokens
        self.metrics['total_chars_sent'] += chars

        logger.info(
            f"LLM request -> model={self.model_name} messages={len(messages)} chars={chars} est_tokens~{est_tokens} max_tokens={payload['max_tokens']} functions={len(functions) if functions else 0}"
        )
        logger.debug(f"Sending LLM request to {request_url} with payload: {json.dumps(payload, indent=2)}")

        try:
            # Allow a couple of retry attempts on read/timeouts for slower LLM backends
            max_attempts = 2
            backoff_seconds = 0.8
            response = None
            for attempt in range(1, max_attempts + 1):
                try:
                    start_time = time.time()
                    response = await self.http_session.post(request_url, json=payload, headers=headers, timeout=self.request_timeout_seconds)
                    duration = time.time() - start_time
                    break
                except httpx.ReadTimeout as e:
                    logger.warning(f"LLM request read timeout on attempt {attempt}/{max_attempts}: {e}")
                    if attempt < max_attempts:
                        await asyncio.sleep(backoff_seconds * attempt)
                        continue
                    raise
                except httpx.TimeoutException as e:
                    logger.warning(f"LLM request timed out on attempt {attempt}/{max_attempts}: {e}")
                    if attempt < max_attempts:
                        await asyncio.sleep(backoff_seconds * attempt)
                        continue
                    raise
            self.metrics['last_call_duration_s'] = duration

            logger.debug(f"LLM raw response status: {response.status_code}, headers: {response.headers}")
            response.raise_for_status()
            response_data = response.json()
            logger.debug(f"LLM raw response data (after json()): {json.dumps(response_data, indent=2)}")

            # Inspect finish reason if present and update metrics
            try:
                choices = response_data.get('choices') or []
                if choices and isinstance(choices, list):
                    finish_reason = choices[0].get('finish_reason')
                    if finish_reason == 'length':
                        self.metrics['truncated_responses'] += 1
                        logger.warning("LLM response was truncated (finish_reason: 'length'). Consider reducing prompt size or increasing max_tokens for final attempts.")
                    logger.info(f"LLM response finish_reason={finish_reason} duration_s={duration:.2f} est_tokens_sent~{est_tokens}")
            except Exception:
                logger.debug("Could not parse finish_reason from LLM response.")

            if 'message' in response_data and 'content' in response_data['message']:
                pass
            elif 'choices' in response_data and response_data['choices'] and \
                 'message' in response_data['choices'][0] and ('content' in response_data['choices'][0]['message'] or 'function_call' in response_data['choices'][0]['message']):
                pass
            else:
                logger.error(f"LLM response missing expected content structure. Response: {response_data}")
                return None
            return response_data
        except httpx.ReadTimeout as e:
            logger.error(f"LLM API request read timed out after {self.request_timeout_seconds}s: {e}", exc_info=True)
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
                                        conversation_language: str = "English",
                                        max_response_tokens: Optional[int] = None
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

        # Determine max_tokens to request for the summary output. The default of 300
        # can be too small for longer summaries; allow callers to override via
        # the `max_response_tokens` parameter. Use a sensible default (800).
        request_max_tokens = int(max_response_tokens) if max_response_tokens is not None else 800
        # Never request more than client's default_max_tokens
        request_max_tokens = min(request_max_tokens, self.default_max_tokens)

        # Log prompt size heuristics to help debug truncated outputs (finish_reason: 'length')
        try:
            prompt_chars = len(formatted_prompt)
            est_prompt_tokens = max(1, int(prompt_chars / 4))
        except Exception:
            prompt_chars = 0
            est_prompt_tokens = 0
        logger.info(f"Generating new user summary -> prompt_chars={prompt_chars} est_prompt_tokens~{est_prompt_tokens} request_max_tokens={request_max_tokens}")

        llm_response_data = await self._make_llm_request(messages, temperature=0.6, max_tokens=request_max_tokens)

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

    async def classify_user_for_suspicion(self, user_messages: str, analysis_prompt_template: str, max_response_tokens: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Run an LLM analysis over the user's messages and return a classification dict like:
        {"is_suspicious": bool, "reason": str}
        The analysis_prompt_template should contain a placeholder for the messages (e.g., '{messages}').
        """
        if not analysis_prompt_template:
            logger.error("No analysis prompt template provided for suspicious classification.")
            return None

        # Safely prepare the system prompt, but send the actual messages as user role so the model always sees them
        try:
            if '{messages}' in analysis_prompt_template:
                system_prompt = analysis_prompt_template.replace('{messages}', '{messages}')
            else:
                try:
                    tmpl = Template(analysis_prompt_template)
                    system_prompt = tmpl.safe_substitute(messages='{messages}')
                except Exception:
                    system_prompt = "Please analyze the following user messages for spam, bot-like behavior, or nonsensical content:"
        except Exception as e:
            logger.error(f"Failed to prepare analysis prompt template: {e}", exc_info=True)
            system_prompt = "Please analyze the following user messages for spam, bot-like behavior, or nonsensical content:"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_messages}
        ]

        request_max_tokens = int(max_response_tokens) if max_response_tokens is not None else 200
        request_max_tokens = min(request_max_tokens, self.default_max_tokens)

        # Log prompt size heuristics before making the call
        try:
            prompt_chars = len(system_prompt) + len(user_messages or "")
            est_prompt_tokens = max(1, int(prompt_chars / 4))
        except Exception:
            prompt_chars = 0
            est_prompt_tokens = 0
        logger.info(f"LLM classify_user_for_suspicion -> prompt_chars={prompt_chars} est_prompt_tokens~{est_prompt_tokens} request_max_tokens={request_max_tokens}")
        try:
            preview = repr((system_prompt + "\n\n" + (user_messages or ""))[:800])
        except Exception:
            preview = ""
        logger.debug("LLM classify_user_for_suspicion -> prompt preview: %s", preview)

        # Load our local suspicious classification schema file if available for function-calling
        functions_payload = None
        try:
            with open('llm_integration/schemas/suspicious_classification.json', 'r', encoding='utf-8') as sf:
                functions_payload = [json.load(sf)]
        except Exception:
            functions_payload = None

        # Make the LLM call using function-calling when possible
        if functions_payload:
            llm_response = await self._make_llm_request(messages, temperature=0.0, max_tokens=request_max_tokens, functions=functions_payload, function_call={"name": "classify_user"})
        else:
            llm_response = await self._make_llm_request(messages, temperature=0.0, max_tokens=request_max_tokens)

        if not llm_response:
            logger.warning("LLM classify_user_for_suspicion returned no response data.")
            return None

        # Debug preview
        try:
            logger.debug(f"LLM classify_user_for_suspicion raw response preview: {repr(str(llm_response)[:2000])}")
        except Exception:
            pass

        # Parse function-calling style responses first
        try:
            choice = llm_response.get("choices", [{}])[0]
            message_obj = choice.get("message", {})
            if message_obj.get("function_call"):
                args = message_obj["function_call"].get("arguments", "{}")
                try:
                    parsed = json.loads(args)
                    logger.info(f"LLM classify_user_for_suspicion parsed function_call JSON: keys={list(parsed.keys())}")
                    return parsed
                except json.JSONDecodeError:
                    logger.warning("LLM classify_user_for_suspicion: function_call.arguments not valid JSON; returning raw arguments as reason")
                    return {"is_suspicious": False, "reason": args[:800]}

            # Otherwise, look for content in the usual places
            content = None
            if "message" in llm_response and isinstance(llm_response["message"], dict) and "content" in llm_response["message"]:
                content = llm_response["message"]["content"]
            elif choice.get("message", {}).get("content"):
                content = choice["message"]["content"]
            else:
                content = ""

            logger.info(f"LLM classify_user_for_suspicion -> response content preview (first 400 chars): {repr((content or '')[:400])}")

            # Try to parse content as JSON
            try:
                parsed = json.loads(content)
                logger.info(f"LLM classify_user_for_suspicion parsed JSON from content: keys={list(parsed.keys())}")
                return parsed
            except Exception:
                # Fallback heuristic
                lower = (content or "").lower()
                is_suspicious = any(k in lower for k in ("spam", "bot", "nonsense", "scam", "phishing", "malicious"))
                reason_preview = (content or "")[:800]
                logger.info(f"LLM classify_user_for_suspicion heuristic result: is_suspicious={is_suspicious}")
                return {"is_suspicious": is_suspicious, "reason": reason_preview}
        except Exception as e:
            logger.error(f"Error processing LLM response for suspicion classification: {e}", exc_info=True)
        return None
    
    async def categorize_server_roles(self, roles_data: List[Dict[str, Any]], categorization_prompt: str) -> Dict[str, List[int]]:
        """Call the LLM to categorize server roles. Returns a dict: category_name -> list of role IDs."""
        logger.info(f"Attempting to categorize {len(roles_data)} roles with LLM.")
        roles_list_str = "\n".join([f"- {role['name']} (ID: {role['id']})" for role in roles_data])
        formatted_prompt = f"{categorization_prompt}\n\nHere is the list of roles to categorize:\n{roles_list_str}"

        messages = [{"role": "system", "content": formatted_prompt}]

        if not self.role_categorization_schema:
            logger.error("Role categorization schema not loaded. Aborting categorization.")
            return {}

        llm_response_data = await self._make_llm_request(
            messages,
            temperature=0.1,
            max_tokens=self.default_max_tokens,
            functions=[self.role_categorization_schema],
            function_call={"name": "categorize_server_roles"}
        )

        categorized_role_ids: Dict[str, List[int]] = {}

        if llm_response_data:
            try:
                if llm_response_data.get("choices") and llm_response_data["choices"][0].get("message", {}).get("function_call"):
                    function_call = llm_response_data["choices"][0]["message"]["function_call"]
                    if function_call.get("name") == "categorize_server_roles":
                        arguments_str = function_call.get("arguments", "{}")
                        parsed_categories_by_name = json.loads(arguments_str)
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

                        # Post-process: ensure every role from roles_data is in exactly one category.
                        role_id_to_name = {role['id']: role['name'] for role in roles_data}
                        all_role_ids = set(role_id_to_name.keys())
                        assigned_ids = set()
                        for ids in categorized_role_ids.values():
                            assigned_ids.update(ids)

                        unassigned_ids = sorted(list(all_role_ids - assigned_ids))
                        if unassigned_ids:
                            categorized_role_ids.setdefault('Other', [])
                            for uid in unassigned_ids:
                                categorized_role_ids['Other'].append(uid)
                            other_names = [role_id_to_name.get(uid, str(uid)) for uid in unassigned_ids]
                            logger.info(f"Added {len(unassigned_ids)} roles to 'Other' category: {other_names}")
                else:
                    logger.error(f"Could not find function call in LLM response for role categorization: {llm_response_data}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM function call arguments: {e}. Arguments string: {function_call.get('arguments', '')}", exc_info=True)
            except Exception as e:
                logger.error(f"Error processing LLM response for role categorization: {e}", exc_info=True)

        if not categorized_role_ids:
            logger.warning("Role categorization with LLM failed or returned no usable data.")
        return categorized_role_ids
        categorized_role_ids: Dict[str, List[int]] = {}

        if llm_response_data:
            try:
                if llm_response_data.get("choices") and llm_response_data["choices"][0].get("message", {}).get("function_call"):
                    function_call = llm_response_data["choices"][0]["message"]["function_call"]
                    if function_call.get("name") == "categorize_server_roles":
                        arguments_str = function_call.get("arguments", "{}")
                        parsed_categories_by_name = json.loads(arguments_str)
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
                    logger.error(f"Could not find function call in LLM response for role categorization: {llm_response_data}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM function call arguments: {e}. Arguments string: {function_call.get('arguments', '')}", exc_info=True)
            except Exception as e:
                logger.error(f"Error processing LLM response for role categorization: {e}", exc_info=True)

        if not categorized_role_ids:
            logger.warning("Role categorization with LLM failed or returned no usable data.")
        return categorized_role_ids

    async def get_verification_guidance(self, user_message: str, conversation_history: List[Dict[str, str]],
                                        categorized_server_roles: Dict[str, List[int]],
                                        available_roles_map: Dict[int, str],
                                        verification_prompt_template: str,
                                       max_response_tokens: Optional[int] = None) -> Optional[LLMVerificationResponse]:
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

        if not self.user_verification_schema:
            logger.error("User verification schema not loaded. Aborting guidance.")
            return None

        llm_response_data = await self._make_llm_request(
            messages,
            temperature=0.3,
            max_tokens=(max_response_tokens or self.default_max_tokens),
            functions=[self.user_verification_schema],
            function_call={"name": "propose_user_roles"}
        )

        if llm_response_data:
            try:
                choice = llm_response_data.get("choices", [{}])[0]
                if choice.get("finish_reason") == "length":
                    logger.warning(f"LLM response was truncated (finish_reason: 'length'). The prompt may be too long or max_tokens is too small.")

                if choice.get("message", {}).get("function_call"):
                    function_call = choice["message"]["function_call"]
                    if function_call.get("name") == "propose_user_roles":
                        arguments_str = function_call.get("arguments", "{}")
                        parsed_response = json.loads(arguments_str)

                        if all(key in parsed_response for key in ["message_to_user", "is_complete"]) and \
                           isinstance(parsed_response.get("user_has_confirmed"), bool):
                            if "classification" in parsed_response and parsed_response["classification"] is not None:
                                if not isinstance(parsed_response["classification"], dict):
                                    logger.error(f"LLM 'classification' field is not a dictionary.")
                                    parsed_response["classification"] = None
                                else:
                                    for category_key in list(parsed_response["classification"].keys()):
                                        if isinstance(parsed_response["classification"][category_key], list):
                                            try:
                                                valid_ids = [int(rid) for rid in parsed_response["classification"][category_key] if rid is not None]
                                                parsed_response["classification"][category_key] = valid_ids
                                            except (ValueError, TypeError):
                                                logger.error(f"LLM returned non-integer/None role ID in {category_key}.")
                                                parsed_response["classification"][category_key] = []
                                        else:
                                            logger.error(f"LLM 'classification' for {category_key} is not a list.")
                                            parsed_response["classification"][category_key] = []
                            logger.info(f"Successfully parsed verification guidance from LLM.")
                            return parsed_response
                        else:
                            logger.error(f"LLM JSON response missing required keys or 'user_has_confirmed' not bool. Parsed: {parsed_response}")
                else:
                    logger.error(f"Could not find function call in LLM response for user verification: {llm_response_data}")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM function call arguments: {e}. Arguments string: {function_call.get('arguments', '')}", exc_info=True)
            except Exception as e:
                logger.error(f"Error processing LLM response for user verification: {e}", exc_info=True)

        logger.warning("Using fallback response for verification guidance.")
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

        # Safely substitute template variables using string.Template to preserve literal braces
        try:
            tmpl = Template(welcome_prompt_template_str)
            system_message_content = tmpl.safe_substitute(server_name=server_name, member_name=member_name, member_id=member_id)
        except Exception as e:
            logger.error(f"Error formatting welcome prompt template: {e}", exc_info=True)
            system_message_content = (
                "Eres un asistente amigable. Genera un mensaje breve y entusiasta de bienvenida para un nuevo miembro de Discord. "
                "Menciónalo por su nombre y sugiere que recibirá un DM para la asignación de roles. Responde en español."
            )

        # Ensure Spanish output is requested
        try:
            if 'español' not in (system_message_content or '').lower() and 'spanish' not in (system_message_content or '').lower():
                system_message_content = "Responde en español.\n\n" + (system_message_content or "")
        except Exception:
            pass

        # Ask the model to include a short Markdown instruction to run /assign-roles
        user_message_content = (
            f"Un nuevo usuario llamado '{member_name}' se ha unido al servidor. Genera un mensaje de bienvenida breve y amistoso mencionándolo con <@{member_id}>. "
            "Incluye una instrucción breve en Markdown que diga: ejecuta `/assign-roles` para verificar tu cuenta y recibir roles. "
            "Responde solo con el mensaje, puedes usar Markdown ligero pero no bloques de código."
        )
        # Cap user message size (should be short) to avoid adding large context
        try:
            if len(user_message_content) > 800:
                logger.warning(f"Trimming welcome user message from {len(user_message_content)} to 800 chars.")
                user_message_content = user_message_content[:800]
        except Exception:
            pass

        # Normalize whitespace in system prompt to reduce token overhead
        try:
            normalized_system = re.sub(r"\s+", " ", (system_message_content or "")).strip()
        except Exception:
            normalized_system = system_message_content or ""

        # Smart trim: keep head and tail so the model retains instructions and context
        def _smart_trim(text: str, max_chars: int) -> str:
            if not text or len(text) <= max_chars:
                return text
            marker = "\n\n...[truncated to avoid exceeding token limit]...\n\n"
            # Reserve space for marker
            reserve = len(marker)
            if max_chars <= reserve + 20:
                return text[:max_chars]
            head_chars = int((max_chars - reserve) * 0.6)
            tail_chars = max_chars - reserve - head_chars
            head = text[:head_chars].rstrip()
            tail = text[-tail_chars:].lstrip()
            return head + marker + tail

        final_system = normalized_system
        try:
            orig_len = len(final_system)
            if orig_len > self.welcome_max_prompt_chars:
                final_system = _smart_trim(final_system, self.welcome_max_prompt_chars)
                logger.warning(f"Smart-trimmed welcome system prompt: original_chars={orig_len} trimmed_chars={len(final_system)}")
                logger.debug(f"Welcome system prompt preview after trim (first 300 chars): {repr(final_system[:300])}")
        except Exception:
            logger.debug("Error while smart-trimming system prompt; using normalized content as-is.")

        messages = [
            {"role": "system", "content": final_system},
            {"role": "user", "content": user_message_content}
        ]

        logger.debug(f"Welcome prompt preview (first 400 chars): {repr(final_system[:400])}")

        # Request a reasonably short welcome message using configurable parameters
        llm_response_data = await self._make_llm_request(messages, temperature=self.welcome_temperature, max_tokens=self.welcome_max_response_tokens)

        # If the model was truncated and returned no content, try one bounded retry with higher max_tokens
        try:
            if llm_response_data and isinstance(llm_response_data.get('choices'), list) and llm_response_data['choices']:
                choice0 = llm_response_data['choices'][0]
                finish_reason = choice0.get('finish_reason')
                # If no content returned and model was cut off, attempt a retry with a larger max_tokens
                content_here = None
                if isinstance(choice0.get('message'), dict):
                    content_here = choice0['message'].get('content')
                if finish_reason == 'length' and not content_here:
                    # compute a larger token budget but bounded by default_max_tokens
                    retry_tokens = min(self.default_max_tokens, max(self.welcome_max_response_tokens * 3, self.welcome_max_response_tokens + 400))
                    # Avoid retrying with the same or smaller budget
                    if retry_tokens > self.welcome_max_response_tokens:
                        logger.warning(f"Welcome generation truncated (finish_reason: 'length') and returned empty. Retrying with max_tokens={retry_tokens}.")
                        llm_response_retry = await self._make_llm_request(messages, temperature=self.welcome_temperature, max_tokens=retry_tokens)
                        if llm_response_retry:
                            llm_response_data = llm_response_retry
        except Exception:
            logger.debug("Error during welcome generation retry logic; proceeding with initial response.")

        # Spanish fallback if LLM doesn't produce usable content
        fallback_text = self.welcome_hardcode_message or f"Bienvenido a {server_name}, <@{member_id}>! Estamos encantados de tenerte aquí. Es posible que recibas un DM para ayudarte a asignar algunos roles iniciales."

        # Respect hardcode setting: if configured, return the hardcoded message immediately
        if self.welcome_hardcode:
            logger.info("Using hardcoded welcome message (WELCOME_HARDCODE=true)")
            return fallback_text

        if llm_response_data:
            response_content_str: Optional[str] = None
            try:
                # Standard content locations
                if "message" in llm_response_data and isinstance(llm_response_data["message"], dict) and "content" in llm_response_data["message"]:
                    response_content_str = llm_response_data["message"]["content"]
                elif "choices" in llm_response_data and isinstance(llm_response_data.get("choices"), list) and len(llm_response_data["choices"]) > 0 and isinstance(llm_response_data["choices"][0], dict) and "message" in llm_response_data["choices"][0] and isinstance(llm_response_data["choices"][0].get("message"), dict) and "content" in llm_response_data["choices"][0]["message"]:
                    response_content_str = llm_response_data["choices"][0]["message"]["content"]

                # Function-calling style
                if not response_content_str and "choices" in llm_response_data and isinstance(llm_response_data.get("choices"), list) and len(llm_response_data["choices"]) > 0:
                    try:
                        choice = llm_response_data["choices"][0]
                        func = choice.get("message", {}).get("function_call") if isinstance(choice.get("message"), dict) else None
                        if func and "arguments" in func:
                            args_str = func.get("arguments", "")
                            try:
                                parsed_args = json.loads(args_str)
                                if isinstance(parsed_args, dict):
                                    for k in ("welcome_message", "message", "content", "text"):
                                        if k in parsed_args and isinstance(parsed_args[k], str):
                                            response_content_str = parsed_args[k]
                                            break
                                    if response_content_str is None:
                                        response_content_str = json.dumps(parsed_args)
                                elif isinstance(parsed_args, str):
                                    response_content_str = parsed_args
                            except json.JSONDecodeError:
                                response_content_str = args_str
                    except Exception:
                        logger.debug("No function_call.arguments found or could not parse it for welcome message.")

                if response_content_str and isinstance(response_content_str, str):
                    stripped = response_content_str.strip()
                    if stripped:
                        logger.info("Welcome message generated by LLM.")
                        logger.debug(f"LLM welcome message (repr): {repr(stripped)}")
                        return stripped
                    else:
                        logger.warning("LLM returned an empty/whitespace welcome message after stripping. Using fallback.")
                        logger.debug(f"Raw LLM response data for welcome message (empty after strip): {llm_response_data}")
                else:
                    logger.warning(f"LLM response content for welcome message was None or not a string. Data: {llm_response_data}")

            except Exception as e:
                logger.error(f"Error processing LLM response content for welcome message: {e}", exc_info=True)
                logger.debug(f"Problematic LLM response data for welcome message: {llm_response_data}")

        logger.warning("Failed to generate LLM welcome message or content was null/invalid, using fallback.")
        logger.info(f"Using fallback welcome message: {repr(fallback_text)}")
        return fallback_text