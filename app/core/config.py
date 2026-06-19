from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="Petunjukku AI Service", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_port: int = Field(default=8000, alias="APP_PORT")
    internal_api_key: str = Field(
        default="change-this-internal-key",
        alias="INTERNAL_API_KEY",
    )

    llm_provider: str = Field(default="openrouter", alias="LLM_PROVIDER")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices("OPENROUTER_BASE_URL", "OPENROUTER_API_BASE_URL"),
    )
    llm_model: str = Field(default="qwen/qwen3.7-plus", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.3, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=12000, alias="LLM_MAX_TOKENS")

    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL_NAME",
    )
    embedding_dimension: int = Field(default=384, alias="EMBEDDING_DIMENSION")

    request_timeout_seconds: int = Field(default=180, alias="REQUEST_TIMEOUT_SECONDS")
    resource_discovery_enabled: bool = Field(
        default=True,
        alias="RESOURCE_DISCOVERY_ENABLED",
    )
    resource_discovery_timeout_seconds: int = Field(
        default=15,
        alias="RESOURCE_DISCOVERY_TIMEOUT_SECONDS",
    )
    resource_discovery_max_results: int = Field(
        default=5,
        alias="RESOURCE_DISCOVERY_MAX_RESULTS",
    )
    youtube_api_key: str | None = Field(default=None, alias="YOUTUBE_API_KEY")
    youtube_api_base_url: str = Field(
        default="https://www.googleapis.com/youtube/v3",
        alias="YOUTUBE_API_BASE_URL",
    )
    book_catalog_api_url: str | None = Field(
        default=(
            "https://api.buku.cloudapp.web.id/api/catalogue/"
            "getPenggerakTextBooks"
        ),
        alias="BOOK_CATALOG_API_URL",
    )
    book_catalog_allowed_domains: str = Field(
        default=(
            "buku.kemendikdasmen.go.id,static.sc.cloudapp.web.id,"
            "static-sc.cloudapp.web.id,files.cloudapp.web.id"
        ),
        alias="BOOK_CATALOG_ALLOWED_DOMAINS",
    )
    faiss_index_path: str = Field(
        default="app/data/vector_store/cp.index",
        alias="FAISS_INDEX_PATH",
    )
    faiss_metadata_path: str = Field(
        default="app/data/vector_store/cp_metadata.json",
        alias="FAISS_METADATA_PATH",
    )

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider.strip().lower() == "openrouter" and bool(
            self.openrouter_api_key
        )

    @property
    def openrouter_chat_url(self) -> str:
        base_url = self.openrouter_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    @property
    def openrouter_embeddings_url(self) -> str:
        base_url = self.openrouter_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            base_url = base_url.removesuffix("/chat/completions")
        return f"{base_url}/embeddings"


settings = Settings()
