# File: config.py

import logging
from typing import List, Optional, Union # Union might not be needed here currently
from pydantic import Field, PositiveInt, HttpUrl, field_validator # field_validator for Pydantic v2

from pydantic_settings import BaseSettings, SettingsConfigDict

# Configure a basic logger for config loading issues, actual setup is in main.py
# This helps catch errors if main.py's logging isn't set up yet.
config_logger = logging.getLogger(__name__) # Use __name__ for module-specific logger

class Settings(BaseSettings):
    # Model config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra fields from .env
        case_sensitive=False # Environment variable names are typically case-insensitive
    )

    # Discord Bot Configuration
    DISCORD_BOT_TOKEN: str

    # LLM API Configuration
    LLM_API_URL: HttpUrl # Pydantic will validate this is a valid HTTP/S URL
    LLM_API_TOKEN: Optional[str] = None 
    LLM_MODEL_NAME: str = "your-llm-model-name" # Default can be overridden by .env

    # Discord Role IDs
    VERIFIED_ROLE_ID: PositiveInt
    UNVERIFIED_ROLE_ID: PositiveInt
    VERIFICATION_IN_PROGRESS_ROLE_ID: PositiveInt
    
    # For ADMIN_ROLE_IDS, we take a string and parse it into a list of ints
    ADMIN_ROLE_IDS_STR: str = Field("", alias="ADMIN_ROLE_IDS") 

    # Discord Channel IDs (make them optional by default if they aren't strictly required for bot to start)
    NOTIFICATION_CHANNEL_ID: Optional[PositiveInt] = None
    WELCOME_CHANNEL_ID: Optional[PositiveInt] = None
    
    # Bot Behavior Configuration
    VERIFICATION_RETRIES: PositiveInt = 3
    REBUILD_ROLE_CATEGORIES_ON_STARTUP: bool = False

    # Logging Configuration
    LOG_LEVEL: str = "INFO"

    # File Paths (Updated to new structure)
    PROMPT_PATH_ROLE_CATEGORIZATION_SYSTEM: str = "prompts/role_categorization/system.txt"
    PROMPT_PATH_USER_VERIFICATION_SYSTEM_TEMPLATE: str = "prompts/user_verification/system_template.txt"
    PROMPT_PATH_CHANNEL_WELCOME_SYSTEM_TEMPLATE: str = "prompts/welcome_message/system_template.txt"
    PROMPT_PATH_NEW_USER_SUMMARY_SYSTEM_TEMPLATE: str = "prompts/new_user_summary/system_template.txt"
    CATEGORIZED_ROLES_FILE: str = "data/categorized_roles.json"
    

    # This will hold the parsed list of admin role IDs
    PARSED_ADMIN_ROLE_IDS: List[int] = []

    # Validator to parse ADMIN_ROLE_IDS_STR into PARSED_ADMIN_ROLE_IDS
    @field_validator('ADMIN_ROLE_IDS_STR', mode='after') # mode='after' ensures it runs after initial parsing
    def parse_admin_role_ids_list(cls, value: str, values) -> str: # Return value is not used for this validator's side effect
        # The goal is to populate PARSED_ADMIN_ROLE_IDS on the instance
        # This approach is a bit of a workaround for Pydantic v2 if directly assigning to another field in validator.
        # A cleaner way might be using a computed field or root_validator if complex inter-dependencies.
        # For now, we'll populate it on the instance after validation.
        # This validator just ensures the string is available. The property below is better.
        return value # Return the original string value for the field

    @property
    def ADMIN_ROLES_AS_INT_LIST(self) -> List[int]: # Renamed for clarity from PARSED_ADMIN_ROLE_IDS
        if not self.ADMIN_ROLE_IDS_STR:
            return []
        try:
            return [int(role_id.strip()) for role_id in self.ADMIN_ROLE_IDS_STR.split(',') if role_id.strip().isdigit()]
        except ValueError as e:
            config_logger.error(f"Invalid ADMIN_ROLE_IDS format: '{self.ADMIN_ROLE_IDS_STR}'. Must be comma-separated integers. Error: {e}")
            return []

# Global settings instance
try:
    settings = Settings()
    # Populate the parsed list after instantiation
    settings.PARSED_ADMIN_ROLE_IDS = settings.ADMIN_ROLES_AS_INT_LIST
except Exception as e:
    config_logger.critical(f"CRITICAL: Failed to load application settings from .env or defaults. Error: {e}", exc_info=True)
    # This print is for cases where logging might not be fully set up yet
    print(f"CRITICAL: Failed to load application settings. Error: {e}\nCheck your .env file and configurations.")
    raise SystemExit(f"Configuration load failed: {e}")