"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Local storage root (self-contained inside gov_report/)
    data_dir: Path = Path("data")

    # HTTP settings
    user_agent: str = "gov-report-crawler/0.1"
    request_timeout: int = 30
    max_concurrent: int = 3

    # LLM extraction settings (OpenRouter / OpenAI-compatible)
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.0
    llm_context_chars: int = 4000

    # TextIn API (for PDF delegation only)
    textin_app_id: str = ""
    textin_secret_code: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def extraction_path(self) -> Path:
        return self.data_dir / "extraction"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_path(self) -> Path:
        return self.data_dir / "gov_downloads"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_db_path(self) -> Path:
        return self.data_dir / "gov_report_sync.db"

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.extraction_path.mkdir(parents=True, exist_ok=True)
        self.download_path.mkdir(parents=True, exist_ok=True)

    def to_doc_parser_settings(self):
        """Build a doc_parser.config.Settings for PDF delegation."""
        from doc_parser.config import Settings as DocSettings

        return DocSettings(
            textin_app_id=self.textin_app_id,
            textin_secret_code=self.textin_secret_code,
            data_dir=self.data_dir,
            llm_api_key=self.llm_api_key,
            llm_base_url=self.llm_base_url,
            llm_model=self.llm_model,
            llm_max_tokens=self.llm_max_tokens,
            llm_temperature=self.llm_temperature,
            llm_context_chars=self.llm_context_chars,
        )


def get_settings(**overrides: object) -> Settings:
    """Create a Settings instance, allowing overrides for testing."""
    return Settings(**overrides)  # type: ignore[arg-type]
