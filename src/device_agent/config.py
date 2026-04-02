"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Centralised settings for the Device Agent."""

    base_url: str = field(
        default_factory=lambda: os.getenv(
            "DEVICE_API_BASE_URL", "http://127.0.0.1:8000"
        )
    )
    api_timeout: int = field(
        default_factory=lambda: int(os.getenv("DEVICE_API_TIMEOUT", "10"))
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )

    @property
    def eligibility_url(self) -> str:
        return f"{self.base_url}/device/check-eligibility"

    @property
    def unlock_url(self) -> str:
        return f"{self.base_url}/device/unlock-device"


# Singleton used across the application
settings = Settings()
