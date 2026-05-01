from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    FRONTEND_URL: str
    ENV: str = "development"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_USE_TLS: bool = True
    OTP_TTL_SECONDS: int = 30
    OTP_MAX_ATTEMPTS: int = 2
    TRANSFER_REQUEST_TTL_MINUTES: int = 15

    class Config:
        env_file = ".env"

settings = Settings()
print("SETTINGS LOADED:", settings.model_dump())
