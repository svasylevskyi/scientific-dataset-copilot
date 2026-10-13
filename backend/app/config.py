"""Environment configuration; defaults are deliberately local-only."""

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    public_url: str
    secure_cookies: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_starttls: bool
    mail_from: str

    @property
    def origin(self) -> str:
        return self.public_url


@lru_cache
def settings() -> Settings:
    public_url = os.getenv("SDC_PUBLIC_URL", "http://127.0.0.1:5173").rstrip("/")
    url = urlsplit(public_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.path
        or url.query
        or url.fragment
        or url.username
        or url.password
    ):
        raise ValueError("SDC_PUBLIC_URL must be an absolute origin without a path")
    secure = os.getenv("SDC_SECURE_COOKIES", "false").lower() == "true"
    if url.hostname not in {"localhost", "127.0.0.1"} and (url.scheme != "https" or not secure):
        raise ValueError("Non-local deployments require HTTPS and SDC_SECURE_COOKIES=true")
    database_url = os.getenv(
        "SDC_DATABASE_URL", "postgresql+psycopg://sdc:sdc_local@127.0.0.1:5432/sdc"
    )
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("SDC_DATABASE_URL must use postgresql+psycopg")
    return Settings(
        database_url=database_url,
        public_url=public_url,
        secure_cookies=secure,
        smtp_host=os.getenv("SDC_SMTP_HOST", "127.0.0.1"),
        smtp_port=int(os.getenv("SDC_SMTP_PORT", "1025")),
        smtp_username=os.getenv("SDC_SMTP_USERNAME", ""),
        smtp_password=os.getenv("SDC_SMTP_PASSWORD", ""),
        smtp_starttls=os.getenv("SDC_SMTP_STARTTLS", "false").lower() == "true",
        mail_from=os.getenv("SDC_MAIL_FROM", "Scientific Dataset Copilot <hello@sdc.local>"),
    )
