# File: test_prompt_format.py

import os

# Define the path to your prompt file relative to this script
# Assuming this script is in the project root and prompts are in 'prompts/'
PROMPT_FILE_PATH = os.path.join("prompts", "user_verification_prompt.txt")

def test_format():
    print(f"Attempting to load prompt file from: {os.path.abspath(PROMPT_FILE_PATH)}")

    if not os.path.exists(PROMPT_FILE_PATH):
        print(f"ERROR: Prompt file not found at {PROMPT_FILE_PATH}")
        return

    try:
        with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
            prompt_template_content = f.read()
    except Exception as e:
        print(f"ERROR: Could not read the prompt file: {e}")
        return

    print("\n--- Content of Prompt File (first 500 chars) ---")
    print(prompt_template_content[:500] + "..." if len(prompt_template_content) > 500 else prompt_template_content)
    print("--- End of Prompt File Content Sample ---\n")

    # Dummy data for the placeholder we expect to be in the prompt
    dummy_data = {
        "available_roles_text_list": "- Category A: Role1 (ID: 1), Role2 (ID: 2)\n- Category B: Role3 (ID: 3)"
    }

    print(f"Attempting to format the prompt with data: {dummy_data}")

    try:
        formatted_content = prompt_template_content.format(**dummy_data)
        print("\n--- Successfully formatted the prompt! ---")
        print("--- Formatted Content Sample (first 500 chars) ---")
        print(formatted_content[:500] + "..." if len(formatted_content) > 500 else formatted_content)
        print("--- End of Formatted Content Sample ---")

    except KeyError as e:
        print("\n--- KeyError during formatting! ---")
        problem_key = e.args[0]
        print(f"Python's .format() method is looking for a placeholder named: {repr(problem_key)}")
        print("This means it found something like {key_name} in your prompt file, where key_name matches the above.")
        print("Please inspect your prompt file very carefully for any unintended single curly braces {} surrounding that key.")
        print(f"\nFull error: {e}")

    except Exception as e:
        print(f"\n--- An unexpected error occurred during formatting: {e} ---")

if __name__ == "__main__":
    test_format()