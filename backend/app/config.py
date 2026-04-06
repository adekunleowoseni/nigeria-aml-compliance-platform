from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repo root (so GEMINI_API_KEY etc. load when cwd is backend/)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / ".env"), str(Path(__file__).resolve().parent.parent / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    app_env: str = "development"
    log_level: str = "INFO"
    enable_swagger: bool = True

    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # If true, API accepts requests without Bearer token in development (demo-user).
    # Set false to require login (recommended with the admin login UI).
    allow_anonymous_dev: bool = False

    postgres_url: str = "postgresql://postgres:postgres@postgres:5432/aml_platform"

    # Audit trail: postgres (audit_events, append-only + hash chain) or memory (dev fallback only).
    audit_trail_backend: Literal["memory", "postgres"] = "postgres"
    # Optional: shared secret for POST /audit/event (internal integrators).
    audit_internal_api_key: str = ""
    # Minimum age in days to keep; unset or 0 disables scheduled purge (export/archive before enabling in production).
    audit_retention_days: Optional[int] = None
    audit_retention_interval_hours: int = 24

    # Compliance workflow (default: CO escalates → CCO approves before STR / OTC report generation).
    # Admin may enable shortcuts for demo/training only.
    cco_auto_approve_otc_reporting: bool = False
    cco_auto_approve_str_on_escalation: bool = False

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
    llm_provider: str = "gemini"  # ollama | openai | gemini

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"

    # Unsupervised anomaly scoring
    anomaly_threshold: float = 0.6

    # Real-time rule thresholds (NGN) — individual vs corporate inbound credits
    aml_huge_inflow_individual_ngn: float = 5_000_000.0
    aml_huge_inflow_corporate_ngn: float = 10_000_000.0
    # Flag when calendar-year inbound total exceeds declared annual expectation × ratio (requires KYC/metadata).
    aml_turnover_exceeds_expected_ratio: float = 1.0
    # Optional LLM narrative screen on ingest (Gemini/OpenAI/Ollama per llm_provider)
    aml_realtime_llm_screening: bool = True
    # LLM maps remarks + customer activity to red-flag catalog rule_code; adds RF-AI-EXT-* if no catalog fit.
    aml_red_flag_llm_matching: bool = True
    aml_red_flag_llm_max_catalog_rules: int = 55
    # Second LLM pass on alert snapshot rebuild (extra cost; default off).
    aml_red_flag_llm_on_snapshot: bool = False
    # Append-only DB log of LLM outputs for compliance analytics / future rule authoring (not auto-training).
    aml_red_flag_ai_observation_log: bool = False

    # SMTP (EDD / CCO notifications). Leave host empty to disable sending.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # Chief Compliance Officer mailbox (pre-escalation / STR heads-up)
    cco_email: str = ""

    # Optional PNG/JPG path embedded under SAR approval (Chief Compliance Officer signature)
    cco_signature_image_path: str = ""

    # Optional OpenSanctions API key (some deployments require auth)
    opensanctions_api_key: str = ""

    # Admin-uploaded sanctions / PEP / adverse-media lists (JSON or XML). Fuzzy match score 50–100 (inclusive).
    reference_lists_fuzzy_threshold: int = 82
    reference_lists_internal_api_key: str = ""
    # Full-database rescreen interval in the API process (hours). Use 0 when only Celery Beat triggers run-now.
    reference_lists_embedded_run_interval_hours: int = 24

    # Funds Transfer Report (FTR) — CBN cross-border / wire threshold (NGN / USD + FX for other CCY).
    ftr_threshold_ngn: float = 1_000_000.0
    ftr_threshold_usd: float = 1000.0
    ftr_usd_ngn_rate: float = 1550.0
    ftr_retention_years: int = 5
    ftr_auto_scan_interval_hours: int = 24
    # stub: synthetic ack; api: POST XML to cbn_ftr_api_url when set.
    cbn_ftr_submit_mode: str = "stub"
    cbn_ftr_api_url: str = ""
    # When submit_mode=file_drop, XML is written here and a local reference is stored as acknowledgment (demo).
    cbn_ftr_file_drop_dir: str = ""

    # Data retention & destruction (CBN 5.11.b.ii / NDPA). Celery Beat calls run-now with RETENTION_INTERNAL_API_KEY.
    retention_hard_purge_grace_days: int = 30
    retention_internal_api_key: str = ""
    # Set >0 only when not using Celery Beat (avoids duplicate in-process runs).
    retention_embedded_run_interval_hours: int = 0
    celery_broker_url: str = "redis://redis:6379/1"

    # Board / ECO MI scheduled email tick (Celery POSTs into API). Falls back to RETENTION_INTERNAL_API_KEY if unset.
    mi_schedule_internal_api_key: str = ""
    public_api_base_url: str = ""
    mi_pdf_download_ttl_seconds: int = 900


settings = Settings()

