"""All configuration comes from environment variables (no secrets in code)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Auth between portal and API
    atlas_api_key: str = ""

    # LLM (Groq, OpenAI-compatible)
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_router_model: str = "llama-3.1-8b-instant"
    llm_fallback_model: str = "llama-3.1-8b-instant"
    llm_timeout_s: float = 12.0
    max_tokens_per_request: int = 6000
    max_output_tokens: int = 700

    # Behaviour
    confidence_threshold: float = 0.6
    request_timeout_s: float = 28.0
    cache_ttl_s: int = 3600
    retrieval_top_k: int = 6
    sql_row_limit: int = 50
    sql_timeout_ms: int = 2000
    log_level: str = "INFO"

    # MySQL
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_database: str = "atlas"
    mysql_app_user: str = "atlas_app"
    mysql_app_password: str = ""
    mysql_ro_user: str = "atlas_ro"
    mysql_ro_password: str = ""

    # Vector store / embeddings
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "atlas_reports"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "/models"
    reports_dir: str = "/data/reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
