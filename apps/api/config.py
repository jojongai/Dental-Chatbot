from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
