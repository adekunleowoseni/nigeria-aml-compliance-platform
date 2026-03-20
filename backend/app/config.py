from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    app_env: str = "development"
    log_level: str = "INFO"
    enable_swagger: bool = True

    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # If true, API accepts requests without Bearer token in development (demo-user).
    # Set false to require login (recommended with the admin login UI).
    allow_anonymous_dev: bool = False

    postgres_url: str = "postgresql://postgres:postgres@postgres:5432/aml_platform"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"
    kafka_bootstrap_servers: str = "kafka:9092"
    redis_url: str = "redis://redis:6379/0"

    model_path: str = "/app/models/gnn_model.pt"
    model_batch_size: int = 32
    model_confidence_threshold: float = 0.7

    nfiu_api_url: str = "https://portal.fiu.gov.ng/api"
    nfiu_api_key: str = "change-me"
    nfiu_client_cert_path: str | None = None
    nfiu_private_key_path: str | None = None

    # Decision Support Layer (LLMs)
    llm_provider: str = "ollama"  # ollama | openai | gemini

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"

    # Unsupervised anomaly scoring
    anomaly_threshold: float = 0.6


settings = Settings()

