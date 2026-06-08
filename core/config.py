from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    FRONTEND_URL: str
    ENV: str = "development"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int
    INVOICE_PROVIDER: str = Field(default="openrouter", validation_alias="PROVIDER")
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "qwen/qwen3-vl-8b"
    INVOICE_MAX_FILES: int = 10
    INVOICE_MAX_PAGES: int = 15
    BARCODE_MAX_FILES: int = 50
    REPORT_MAX_FILES: int = 10
    APP_TIMEZONE: str = "Asia/Kolkata"
    DATAMATRIX_DEBUG: bool = False
    DATAMATRIX_DEBUG_DIR: str = "logs/datamatrix_debug"

    # ── Kafka connection ────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # Topic names are DERIVED per process type (see kafka_infra.topics):
    #   <type>-processing  main job topic
    #   <type>-retry       delayed-retry topic
    #   <type>-dlq         dead letter queue
    # Only the shared results topic is named explicitly.
    KAFKA_RESULTS_TOPIC: str = "processing-results"

    # Default partitions per topic when auto/explicitly created.
    KAFKA_NUM_PARTITIONS: int = 3
    KAFKA_REPLICATION_FACTOR: int = 1

    # ── Retry / DLQ policy ──────────────────────────────────────────
    # Total attempts = 1 initial + (DOCUMENT_MAX_RETRIES - 1) retries.
    DOCUMENT_MAX_RETRIES: int = 3
    # Backoff for retry topic: delay = base * (2 ** (attempt - 1)) seconds.
    KAFKA_RETRY_BACKOFF_BASE_SECONDS: int = 2

    # How long the upload endpoint waits (async-await UX) for a result
    # before falling back to a 202 + doc_key polling response.
    PROCESSING_RESULT_TIMEOUT_SECONDS: int = 180

    # ── Document processing settings ────────────────────────────────
    DOCUMENT_STORAGE_DIR: str = "storage/documents"
    DOCUMENT_MAX_FILE_SIZE_MB: int = 50

    model_config = ConfigDict(extra="forbid", env_file=".env")

settings = Settings()
print("SETTINGS LOADED:", settings.model_dump())
