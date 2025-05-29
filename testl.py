# File: test_llm_length.py

import asyncio
import httpx
import json
import os
import logging
from string import Template
from dotenv import load_dotenv

# Setup basic logging for this script
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration - Load from .env ---
load_dotenv() # Load variables from .env file in the current directory or project root

#LLM_API_URL = os.getenv("LLM_API_URL")
LLM_API_URL = "http://bot:3000/api/chat/completions"
LLM_API_TOKEN = os.getenv("LLM_API_TOKEN") # Might be None if not used
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")
PROMPT_FILE_PATH = os.getenv("PROMPT_FILE_USER_VERIFICATION", "prompts/user_verification_prompt.txt")

# --- Editable Variables for Your Test ---
# Simulate the list of current roles. Modify this string to test different lengths.
# This is the part that gets prepended in the "update" scenario.
# Start with the long version from your logs, then shorten it.
#current_roles_list_for_context = [
#     "Proxmox", "Debian", "RaspbianOS", "Arch", "Ubuntu", 
#     "Windows", "Linux", "R", "Java", "C", "Python", "Experto"
#]

current_roles_list_for_context = [
     "Proxmox","Debian", "RaspbianOS","Arch", "Ubuntu", 
]

#current_roles_list_for_context = ["Python", "Experto"] # Example shorter list
#current_roles_list_for_context = [] # Example for no existing roles (like new user)

user_actual_request = "I program in python R java and C. I use linux debian and I have many years of experience programming. I also have a msc on Data science"

#Dummy data for other placeholders in the system prompt
dummy_available_roles_text_list = (
    "- Programming Language: 'Python' (ID: 1), 'Java' (ID: 2), 'R' (ID: 3), 'C' (ID: 4)\n"
    "- Experience Level: 'Beginner' (ID: 5), 'Intermediate' (ID: 6), 'Experto' (ID: 7)\n"
    "- Operating System: 'Linux' (ID: 8), 'Windows' (ID: 9), 'Debian' (ID: 10), 'Ubuntu' (ID: 11), 'Arch' (ID: 12), 'RaspbianOS' (ID: 13), 'Proxmox' (ID: 14), 'MacOS' (ID: 15)"
)

#dummy_available_roles_text_list = ()

# Simulate a very short conversation history (bot's initial greeting)
simulated_initial_bot_greeting = (
    "Hello User! To begin your verification, please tell me about your skills (e.g., Programming Languages, Experience Level, Operating Systems).\n\n"
    "¡Hola User! Para comenzar tu verificación, por favor cuéntame sobre tus habilidades (ej. Lenguajes de Programación, Nivel de Experiencia, Sistemas Operativos)."
)
conversation_history_for_llm = [
    {'role': 'assistant', 'content': simulated_initial_bot_greeting}
]
# --- End of Editable Variables ---


async def make_llm_api_call(http_session: httpx.AsyncClient, messages: list):
    """Makes the API call to the LLM."""
    if not LLM_API_URL or not LLM_MODEL_NAME:
        logger.error("LLM_API_URL or LLM_MODEL_NAME is not set in .env")
        return None

    headers = {"Content-Type": "application/json"}
    if LLM_API_TOKEN:
        headers["Authorization"] = f"Bearer {LLM_API_TOKEN}"

    payload = {
        "model": LLM_MODEL_NAME,
        "messages": messages,
        "temperature": 0.3,  # Keep consistent with bot's settings for this test
        "max_tokens": 1024, # Keep consistent with bot's settings for this test
        # "stream": False, # Ensure stream is false if your endpoint expects it
    }
    # If your LLM supports "format: json" for Ollama models via OpenWebUI:
    # payload["format"] = "json" 

    logger.info(f"Sending request to LLM: {LLM_API_URL}")
    logger.info(f"Payload (first message content): {messages[0]['content'][:200]}...") # Log start of system prompt
    if len(messages) > 1:
        logger.info(f"Payload (last message content): {messages[-1]['content'][:200]}...") # Log start of user message

    try:
        response = await http_session.post(LLM_API_URL, json=payload, headers=headers, timeout=60.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from LLM API: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"Request error for LLM API: {e}")
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON response from LLM. Response text: {response.text if 'response' in locals() else 'N/A'}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during LLM call: {e}", exc_info=True)
    return None


async def test_prompt_length():
    logger.info("Starting LLM prompt length test...")

    # 1. Load the main system prompt template
    try:
        with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
            verification_prompt_template_content = f.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {PROMPT_FILE_PATH}")
        return
    except Exception as e:
        logger.error(f"Error reading prompt file: {e}")
        return

    # 2. Format the system prompt (substituting available_roles_text_list)
    try:
        template = Template(verification_prompt_template_content)
        system_prompt = template.substitute(
            available_roles_text_list=dummy_available_roles_text_list
        )
    except KeyError as e:
        logger.error(f"KeyError formatting system prompt: {e}. Ensure prompt only uses ${available_roles_text_list}.")
        return
    except Exception as e:
        logger.error(f"Error formatting system prompt: {e}")
        return

    # 3. Construct the "user" message, including the prepended context for updates
    # This mimics what your bot does in services/verification_flow_service.py
    # for the first user message in an update session.
    current_roles_text_for_context_note = ", ".join(current_roles_list_for_context)
    
    # This is the user message structure that might be too long
    prepended_context_user_message = (
        f"[System Note: User is updating roles. Current roles: {current_roles_text_for_context_note}. User's request follows.]\n"
        f"User: {user_actual_request}"
    )
    # To test the bot's exact message construction for the LLM:
    # User's request: {user_actual_request}

    # 4. Construct the full messages list for the LLM
    messages_for_llm = [
        {"role": "system", "content": system_prompt},
    ]
    messages_for_llm.extend(conversation_history_for_llm) # Add simulated past turns
    messages_for_llm.append({"role": "user", "content": prepended_context_user_message}) # Add the potentially long user message

    # Optional: Log estimated total characters/tokens (very rough estimate)
    total_chars = sum(len(msg["content"]) for msg in messages_for_llm)
    logger.info(f"Estimated total characters in prompt messages: {total_chars}")
    if total_chars > 7000: # Gemini 1.5 Flash has huge context, but many APIs limit total request size before that.
                           # A typical token is ~4 chars. 2160 tokens is ~8640 chars.
        logger.warning("Prompt character count is very high, might exceed limits.")

    # 5. Make the API call
    async with httpx.AsyncClient() as client:
        llm_response = await make_llm_api_call(client, messages_for_llm)

    # 6. Print the results
    if llm_response:
        logger.info("\n--- LLM Response ---")
        print(json.dumps(llm_response, indent=2, ensure_ascii=False)) # ensure_ascii for Spanish characters
        
        finish_reason = "N/A"
        content_is_none = True
        prompt_tokens = "N/A"
        completion_tokens = "N/A"

        if "choices" in llm_response and llm_response["choices"]:
            choice = llm_response["choices"][0]
            finish_reason = choice.get("finish_reason", "N/A")
            if "message" in choice and choice["message"]:
                content_is_none = choice["message"].get("content") is None
        
        if "usage" in llm_response and llm_response["usage"]:
            prompt_tokens = llm_response["usage"].get("prompt_tokens", "N/A")
            completion_tokens = llm_response["usage"].get("completion_tokens", "N/A")

        logger.info(f"\n--- Summary ---")
        logger.info(f"Finish Reason: {finish_reason}")
        logger.info(f"Content is None: {content_is_none}")
        logger.info(f"Prompt Tokens: {prompt_tokens}")
        logger.info(f"Completion Tokens: {completion_tokens}")
        
        if finish_reason == 'length' or content_is_none:
            logger.warning("LLM output was likely truncated or content was None. Try shortening the 'current_roles_list_for_context' in this script.")
        else:
            logger.info("LLM call seems to have completed without length issues.")
    else:
        logger.error("Failed to get any response from LLM.")

if __name__ == "__main__":
    asyncio.run(test_prompt_length())