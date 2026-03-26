from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so it works regardless of CWD.
_here = Path(__file__).resolve().parent

# Load in order: local override first, then repo root.
# Using an explicit absolute path avoids find_dotenv() walk-order surprises.
_root_env = _here.parents[1] / ".env"  # Dental-Chatbot/.env
_local_env = _here / ".env"  # apps/api/.env  (optional dev override)

load_dotenv(_root_env, override=False)
if _local_env.exists():
    load_dotenv(_local_env, override=True)  # local override wins


class Settings(BaseSettings):
    # No env_file here — load_dotenv above already populated os.environ.
    # pydantic-settings reads from os.environ (highest priority).
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    cors_origins: str = "http://localhost:3000"

    # Gemini — required for LLM features; optional during unit tests
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # Thinking budget in tokens (0 = disable thinking mode)
    gemini_thinking_budget: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
