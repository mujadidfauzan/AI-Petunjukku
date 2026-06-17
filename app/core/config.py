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
    llm_model: str = Field(default="google/gemini-2.5-flash", alias="LLM_MODEL")
    kina_llm_model: str = Field(
        default="qwen/qwen3-coder-flash",
        alias="KINA_LLM_MODEL",
    )
    kina_solver_model: str | None = Field(default=None, alias="KINA_SOLVER_MODEL")
    kina_evaluator_model: str | None = Field(default=None, alias="KINA_EVALUATOR_MODEL")
    llm_temperature: float = Field(default=0.3, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=2048, alias="LLM_MAX_TOKENS")

    embedding_provider: str = Field(default="openrouter", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field(
        default="google/gemini-embedding-2-preview",
        validation_alias=AliasChoices("EMBEDDING_MODEL_NAME", "EMBEDDING_MODEL"),
    )
    embedding_dimension: int = Field(
        default=1536,
        validation_alias=AliasChoices("EMBEDDING_DIMENSION", "EMBEDDING_DIMENSIONS"),
    )

    request_timeout_seconds: int = Field(default=60, alias="REQUEST_TIMEOUT_SECONDS")
    cp_pdf_path: str = Field(
        default="../../rag/data/Kepka_BSKAP_No_01k17e8396ajn15j3hcw0k773b.pdf",
        alias="CP_PDF_PATH",
    )
    local_vector_index_path: str = Field(
        default="app/data/vector_store/local_vector_index.json",
        alias="LOCAL_VECTOR_INDEX_PATH",
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
