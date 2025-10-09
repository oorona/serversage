# File: config.py

import logging
from typing import List, Optional
from pydantic import Field, PositiveInt, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

config_logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    # Discord Bot Configuration
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_BOT_TOKEN_FILE: Optional[str] = None

    # LLM API Configuration
    LLM_API_URL: HttpUrl
    LLM_API_TOKEN: Optional[str] = None
    LLM_API_TOKEN_FILE: Optional[str] = None
    LLM_MODEL_NAME: str = "your-llm-model-name"

    # Discord Role IDs
    VERIFIED_ROLE_ID: PositiveInt
    UNVERIFIED_ROLE_ID: PositiveInt
    VERIFICATION_IN_PROGRESS_ROLE_ID: PositiveInt
    
    ADMIN_ROLE_IDS_STR: str = Field("", alias="ADMIN_ROLE_IDS")

    # Discord Channel IDs
    NOTIFICATION_CHANNEL_ID: Optional[PositiveInt] = None
    WELCOME_CHANNEL_ID: Optional[PositiveInt] = None
    
    # Bot Behavior Configuration
    VERIFICATION_RETRIES: PositiveInt = 3
    REBUILD_ROLE_CATEGORIES_ON_STARTUP: bool = False

    # Logging Configuration
    LOG_LEVEL: str = "INFO"

    # File Paths
    PROMPT_PATH_ROLE_CATEGORIZATION_SYSTEM: str = "prompts/role_categorization/system.txt"
    PROMPT_PATH_USER_VERIFICATION_SYSTEM_TEMPLATE: str = "prompts/user_verification/system_template.txt"
    PROMPT_PATH_CHANNEL_WELCOME_SYSTEM_TEMPLATE: str = "prompts/welcome_message/system_template.txt"
    PROMPT_PATH_NEW_USER_SUMMARY_SYSTEM_TEMPLATE: str = "prompts/new_user_summary/system_template.txt"
    CATEGORIZED_ROLES_FILE: str = "data/categorized_roles.json"
    USER_VERIFICATION_SCHEMA_PATH: str = "llm_integration/schemas/user_verification.json"
    ROLE_CATEGORIZATION_SCHEMA_PATH: str = "llm_integration/schemas/role_categorization.json"

    PARSED_ADMIN_ROLE_IDS: List[int] = []

    @model_validator(mode='after')
    def load_secrets_from_files(self) -> 'Settings':
        """Load secrets from files if the corresponding _FILE env var is set."""
        if self.DISCORD_BOT_TOKEN_FILE and os.path.exists(self.DISCORD_BOT_TOKEN_FILE):
            try:
                with open(self.DISCORD_BOT_TOKEN_FILE, 'r') as f:
                    self.DISCORD_BOT_TOKEN = f.read().strip()
                config_logger.info("Loaded DISCORD_BOT_TOKEN from file.")
            except Exception as e:
                config_logger.error(f"Could not read secret from {self.DISCORD_BOT_TOKEN_FILE}: {e}")
        
        if self.LLM_API_TOKEN_FILE and os.path.exists(self.LLM_API_TOKEN_FILE):
            try:
                with open(self.LLM_API_TOKEN_FILE, 'r') as f:
                    self.LLM_API_TOKEN = f.read().strip()
                config_logger.info("Loaded LLM_API_TOKEN from file.")
            except Exception as e:
                config_logger.error(f"Could not read secret from {self.LLM_API_TOKEN_FILE}: {e}")

        if not self.DISCORD_BOT_TOKEN:
            raise ValueError("DISCORD_BOT_TOKEN must be set via environment variable or file.")
            
        return self

    @property
    def ADMIN_ROLES_AS_INT_LIST(self) -> List[int]:
        if not self.ADMIN_ROLE_IDS_STR:
            return []
        try:
            return [int(role_id.strip()) for role_id in self.ADMIN_ROLE_IDS_STR.split(',') if role_id.strip().isdigit()]
        except ValueError as e:
            config_logger.error(f"Invalid ADMIN_ROLE_IDS format: '{self.ADMIN_ROLE_IDS_STR}'. Must be comma-separated integers. Error: {e}")
            return []

try:
    settings = Settings()
    settings.PARSED_ADMIN_ROLE_IDS = settings.ADMIN_ROLES_AS_INT_LIST
except Exception as e:
    config_logger.critical(f"CRITICAL: Failed to load application settings. Error: {e}", exc_info=True)
    print(f"CRITICAL: Failed to load application settings. Error: {e}\nCheck your .env file and configurations.")
    raise SystemExit(f"Configuration load failed: {e}")