from functools import lru_cache
import os
from pathlib import Path

from pydantic import BaseModel


def load_dotenv(path: str = ".env") -> None:
    dotenv_path = _resolve_dotenv_path(path)
    if dotenv_path is None:
        return
    with dotenv_path.open(encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _resolve_dotenv_path(path: str) -> Path | None:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    for base in [Path.cwd(), *Path.cwd().parents]:
        dotenv_path = base / candidate
        if dotenv_path.exists():
            return dotenv_path
    return None


class Settings(BaseModel):
    app_name: str = "счастливый билетик"
    app_version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://lucky:lucky@localhost:5432/lucky_ticket"
    ekarta_fiscal_base_url: str = "http://f.ekarta-ek.ru/fiscal/"
    fiscal_check_providers: str = "ekarta"
    ticket_check_interval_seconds: int = 900
    internal_api_token: str = ""
    tg_bot_token: str = ""
    vk_bot_token: str = ""
    vk_api_version: str = "5.199"
    messenger_notifications_enabled: bool = False
    ticket_mail_enabled: bool = False
    ticket_mail_imap_host: str = ""
    ticket_mail_imap_port: int = 993
    ticket_mail_imap_username: str = ""
    ticket_mail_imap_password: str = ""
    ticket_mail_imap_folder: str = "INBOX"
    ticket_mail_poll_interval_seconds: int = 300
    ticket_mail_auto_confirm_enabled: bool = True
    ticket_mail_mark_seen: bool = True
    ticket_mail_target_user_id: str = ""
    ticket_mail_target_user_token: str = ""
    ticket_mail_public_address_template: str = ""


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "счастливый билетик"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        database_url=os.getenv(
            "DATABASE_URL", "postgresql+psycopg://lucky:lucky@localhost:5432/lucky_ticket"
        ),
        ekarta_fiscal_base_url=os.getenv(
            "EKARTA_FISCAL_BASE_URL", "http://f.ekarta-ek.ru/fiscal/"
        ),
        fiscal_check_providers=os.getenv("FISCAL_CHECK_PROVIDERS", "ekarta"),
        ticket_check_interval_seconds=int(os.getenv("TICKET_CHECK_INTERVAL_SECONDS", "900")),
        internal_api_token=os.getenv("INTERNAL_API_TOKEN", ""),
        tg_bot_token=os.getenv("TG_BOT_TOKEN", ""),
        vk_bot_token=os.getenv("VK_BOT_TOKEN", ""),
        vk_api_version=os.getenv("VK_API_VERSION", "5.199"),
        messenger_notifications_enabled=_env_bool("MESSENGER_NOTIFICATIONS_ENABLED"),
        ticket_mail_enabled=_env_bool("TICKET_MAIL_ENABLED"),
        ticket_mail_imap_host=os.getenv("TICKET_MAIL_IMAP_HOST", ""),
        ticket_mail_imap_port=int(os.getenv("TICKET_MAIL_IMAP_PORT", "993")),
        ticket_mail_imap_username=os.getenv("TICKET_MAIL_IMAP_USERNAME", ""),
        ticket_mail_imap_password=os.getenv("TICKET_MAIL_IMAP_PASSWORD", ""),
        ticket_mail_imap_folder=os.getenv("TICKET_MAIL_IMAP_FOLDER", "INBOX"),
        ticket_mail_poll_interval_seconds=int(os.getenv("TICKET_MAIL_POLL_INTERVAL_SECONDS", "300")),
        ticket_mail_auto_confirm_enabled=_env_bool("TICKET_MAIL_AUTO_CONFIRM_ENABLED", True),
        ticket_mail_mark_seen=_env_bool("TICKET_MAIL_MARK_SEEN", True),
        ticket_mail_target_user_id=os.getenv("TICKET_MAIL_TARGET_USER_ID", ""),
        ticket_mail_target_user_token=os.getenv("TICKET_MAIL_TARGET_USER_TOKEN", ""),
        ticket_mail_public_address_template=os.getenv("TICKET_MAIL_PUBLIC_ADDRESS_TEMPLATE", ""),
    )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}
