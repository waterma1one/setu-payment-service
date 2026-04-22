from functools import lru_cache
import os


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "Setu Payment Event Service")
        self.app_env = os.getenv("APP_ENV", "development")
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/setu_payment",
        )
        self.log_level = os.getenv("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()

