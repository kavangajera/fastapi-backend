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

    # ── Kafka settings ──────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_DOCUMENT_TOPIC: str = "pdf-processing"
    KAFKA_CONSUMER_GROUP: str = "pdf-workers"
    KAFKA_DLQ_TOPIC: str = "pdf-processing-dlq"

    # ── Document processing settings ────────────────────────────────
    DOCUMENT_STORAGE_DIR: str = "storage/documents"
    DOCUMENT_MAX_FILE_SIZE_MB: int = 50
    DOCUMENT_MAX_RETRIES: int = 3

    model_config = ConfigDict(extra="forbid", env_file=".env")

settings = Settings()
print("SETTINGS LOADED:", settings.model_dump())