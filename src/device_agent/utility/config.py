"""Utility-level config — reads from environment."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(override=False)


class UtilityConfig:
    def __init__(self) -> None:
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        self.db_host: str = os.getenv("DB_HOST", "localhost")
        self.db_user: str = os.getenv("DB_USER", "appuser")
        self.db_password: str = os.getenv("DB_PASSWORD", "apppassword")
        self.db_name: str = os.getenv("DB_NAME", "appdb")
        self.db_port: int = int(os.getenv("DB_PORT", "3306"))

        self.email_recipients: list = [
            e.strip()
            for e in os.getenv(
                "EMAIL_RECIPIENTS",
                "divyanshukollu@gmail.com,krishank@aditiconsulting.com",
            ).split(",")
            if e.strip()
        ]


utility_config = UtilityConfig()

