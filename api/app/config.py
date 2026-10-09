import os
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # LLM Settings
    openai_api_key: str = ""
    groq_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    max_tokens: int = 1024
    request_timeout: float = 30.0
    max_tool_iterations: int = 5

    # CORS Settings
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000

    # Data Path
    data_path: str = "data/orders.csv"

    @property
    def api_key(self) -> str:
        """Return the effective API key (groq_api_key if set, else openai_api_key)."""
        return self.groq_api_key.strip() or self.openai_api_key.strip()

    @property
    def effective_base_url(self) -> str:
        """Return Groq base URL if Groq API key is detected and base URL is default."""
        key = self.api_key
        if (self.groq_api_key or key.startswith("gsk_")) and self.openai_base_url == "https://api.openai.com/v1":
            return "https://api.groq.com/openai/v1"
        return self.openai_base_url

    @property
    def effective_model(self) -> str:
        """Return appropriate default model: openai/gpt-oss-120b for Groq if default model was set."""
        key = self.api_key
        if self.groq_api_key or key.startswith("gsk_"):
            if self.openai_model in ("gpt-4o-mini", "llama-3.3-70b-versatile"):
                return "openai/gpt-oss-120b"
        return self.openai_model

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated cors_origins string into a list."""
        if not self.cors_origins:
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache()
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
