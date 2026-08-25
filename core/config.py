from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    FRONTEND_URL: str
    ENV: str = "development"
    DATABASE_URL: str  # mysql+asyncmy://... — used by the whole stack
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int
    # Carried in .env from an earlier provider-switch design. Nothing reads it
    # today — extraction is configured entirely by the OPENROUTER_* settings
    # below — but Settings is `extra="forbid"`, so leaving it undeclared makes
    # the whole app fail to start with `extra_forbidden` on any .env that
    # still lists it. Declared (and ignored) rather than silently dropped.
    PROVIDER: str | None = None

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash"
    GOTENBERG_URL: str = "http://localhost:3000"
    DOCUMENT_LLM_RENDER_DPI: int = 300
    DOCUMENT_LLM_MAX_CONCURRENCY: int = 16
    DOCUMENT_LLM_TIMEOUT_SECONDS: int = 120
    DOCUMENT_LLM_MAX_OUTPUT_TOKENS: int = 12000
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

    # ── Validation engine ──────────────────────────────────────────
    NDC_CACHE_TTL_DAYS: int = 7
    NDC_CACHE_FORCE_REFRESH: bool = False
    # Module D Tier-3 generic bounds.
    DAYS_SUPPLY_RATE_MAX: float = 50.0  # qty/days > this → WARNING
    DAYS_SUPPLY_RATE_MIN: float = 0.05  # qty/days < this → WARNING
    # Module A — flag listings expiring within N days as INFO (not ERROR).
    NDC_LISTING_EXPIRY_INFO_DAYS: int = 365

    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── Outbound email (SMTP) ───────────────────────────────────────
    # Defaults target Gmail, so a working setup needs only TWO .env keys:
    #
    #     SMTP_USERNAME=you@gmail.com
    #     SMTP_PASSWORD=<16-char Google App Password, no spaces>
    #
    # Gmail rejects your normal account password — generate an App Password
    # at https://myaccount.google.com/apppasswords (2FA must be on).
    # For another provider just override SMTP_HOST / SMTP_PORT.
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    # From-address; falls back to SMTP_USERNAME when left blank (Gmail
    # rewrites the envelope sender to the authenticated account anyway).
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Queue RX"
    # Address replies actually reach. Falls back to the From address.
    # "Do not reply" with no reachable Reply-To is a bulk-mail signal.
    SMTP_REPLY_TO: str = ""
    # Shown in the footer of every email. Receivers (and recipients) treat a
    # real, identifiable sender as a legitimacy signal; a bare "automated
    # message" footer is what bulk mail looks like. Set it to your operating
    # name and city/address.
    EMAIL_SENDER_IDENTITY: str = "Queue RX"
    SMTP_USE_TLS: bool = True  # STARTTLS on port 587
    SMTP_USE_SSL: bool = False  # implicit TLS — set with SMTP_PORT=465
    SMTP_TIMEOUT_SECONDS: int = 20
    # When true, emails are logged instead of sent (handy before SMTP creds
    # exist). Auto-enabled at runtime if no SMTP_USERNAME is configured.
    SMTP_DEBUG_LOG_ONLY: bool = False

    # ── OTP / one-time codes ────────────────────────────────────────
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 600  # 10 min — used by transfer OTPs
    OTP_MAX_ATTEMPTS: int = 5
    PASSWORD_RESET_OTP_TTL_SECONDS: int = 900  # 15 min
    # Lifetime of the short-lived JWT handed out after a reset OTP is
    # verified; the client exchanges it for the actual password change.
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 15

    # ── Signup email verification ───────────────────────────────────
    # How long a staged signup (and its code) stays redeemable before the
    # applicant has to start over.
    SIGNUP_OTP_TTL_SECONDS: int = 900  # 15 min
    SIGNUP_OTP_MAX_ATTEMPTS: int = 5
    # Minimum gap between two codes mailed to the same address, and the
    # total number of codes one signup attempt may burn. Together they cap
    # how much mail a single address can be made to receive.
    SIGNUP_OTP_RESEND_COOLDOWN_SECONDS: int = 60
    SIGNUP_OTP_MAX_SENDS: int = 5
    # Per-email budget on the unauthenticated signup endpoints — deliberately
    # not per-IP, so people sharing an office or carrier NAT do not throttle
    # each other. Best-effort and per API process; see core/rate_limit.py.
    # Set the limit to 0 to disable.
    SIGNUP_RATE_LIMIT_PER_EMAIL: int = 15
    SIGNUP_RATE_LIMIT_WINDOW_SECONDS: int = 900

    # ── Temperature device logging ──────────────────────────────────
    # Device session tokens are deliberately longer-lived than a user access
    # token: an unattended logger should not have to re-authenticate every
    # few minutes. It re-authenticates with its secret when this elapses.
    TEMPERATURE_DEVICE_TOKEN_EXPIRE_MINUTES: int = 720  # 12 h
    # Minimum length accepted for a caller-supplied device secret. Secrets we
    # generate ourselves are far longer (32 random bytes, url-safe).
    TEMPERATURE_DEVICE_SECRET_MIN_LENGTH: int = 12
    # Cap on readings accepted in a single push, so one malformed batch can
    # not blow up a transaction.
    TEMPERATURE_LOG_MAX_BATCH_SIZE: int = 500
    # Safe storage range used to derive a reading's status when the device
    # does not report one itself (matches the 2-8 °C fridge band in the UI).
    TEMPERATURE_SAFE_MIN_C: float = 2.0
    TEMPERATURE_SAFE_MAX_C: float = 8.0

    # ── Pharmacy ownership transfer ─────────────────────────────────
    # How long a pending transfer request stays actionable by the new owner.
    TRANSFER_REQUEST_TTL_HOURS: int = 48

    model_config = ConfigDict(extra="forbid", env_file=".env")


settings = Settings()
