from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from email import policy
from email.utils import getaddresses
from email.message import EmailMessage, Message
from email.parser import BytesParser
import html
from html.parser import HTMLParser
import imaplib
import logging
import re
from typing import Callable
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.db.models import Ticket, TicketHappiness, User
from app.db.session import SessionLocal
from app.happiness.rules import score_ticket_number
from app.notifications import notify_ticket_mail_confirmed, notify_ticket_uploaded
from app.tickets.parser import is_nspk_sbp_email, normalize_ocr_text, parse_ticket_text


LOGGER = logging.getLogger(__name__)
NSPK_CONFIRM_URL_RE = re.compile(
    r"https://bilet\.nspk\.ru/auth/confirm-fiscal-email/[0-9a-f-]+",
    re.IGNORECASE,
)
NSPK_CONFIRM_EMAIL_API_URL = "https://bilet.nspk.ru/api/v1/user/confirm-email"


@dataclass(slots=True)
class TicketMailStats:
    seen: int = 0
    confirmed: int = 0
    imported: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(slots=True)
class TicketMailMessageResult:
    confirmed: int = 0
    imported: int = 0
    duplicate: bool = False
    skipped: bool = False
    failed: bool = False
    mark_seen: bool = False
    detail: str | None = None


def ticket_mail_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        settings.ticket_mail_enabled
        and settings.ticket_mail_imap_host
        and settings.ticket_mail_imap_username
        and settings.ticket_mail_imap_password
    )


async def ticket_mail_loop(interval_seconds: int | None = None) -> None:
    settings = get_settings()
    interval = interval_seconds or settings.ticket_mail_poll_interval_seconds
    if interval <= 0:
        return

    startup_delay = min(10, max(1, interval))
    await asyncio.sleep(startup_delay)
    while True:
        try:
            stats = await asyncio.to_thread(process_ticket_mail_once, settings)
            if stats.seen or stats.confirmed or stats.imported or stats.failed:
                LOGGER.info("Ticket mail processed: %s", stats)
        except Exception:
            LOGGER.exception("Ticket mail loop failed")
        await asyncio.sleep(interval)


def process_ticket_mail_once(settings: Settings | None = None) -> TicketMailStats:
    settings = settings or get_settings()
    stats = TicketMailStats()
    if not ticket_mail_configured(settings):
        LOGGER.warning("Ticket mail is enabled but IMAP settings are incomplete")
        return stats

    with imaplib.IMAP4_SSL(settings.ticket_mail_imap_host, settings.ticket_mail_imap_port) as mailbox:
        mailbox.login(settings.ticket_mail_imap_username, settings.ticket_mail_imap_password)
        status, _ = mailbox.select(settings.ticket_mail_imap_folder)
        if status != "OK":
            raise RuntimeError(f"Could not select IMAP folder {settings.ticket_mail_imap_folder!r}")

        status, search_data = mailbox.uid("search", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Could not search unread ticket mail")

        uids = search_data[0].split() if search_data and search_data[0] else []
        for uid in uids:
            stats.seen += 1
            result = _process_uid(mailbox, uid, settings)
            stats.confirmed += result.confirmed
            stats.imported += result.imported
            stats.duplicates += int(result.duplicate)
            stats.skipped += int(result.skipped)
            stats.failed += int(result.failed)
            if settings.ticket_mail_mark_seen and result.mark_seen:
                mailbox.uid("store", uid, "+FLAGS", r"(\Seen)")

    return stats


def _process_uid(
    mailbox: imaplib.IMAP4_SSL,
    uid: bytes,
    settings: Settings,
) -> TicketMailMessageResult:
    status, fetch_data = mailbox.uid("fetch", uid, "(RFC822)")
    if status != "OK":
        LOGGER.warning("Could not fetch ticket mail UID %s", uid)
        return TicketMailMessageResult(failed=True, detail="fetch_failed")

    raw_message = _raw_message_from_fetch(fetch_data)
    if raw_message is None:
        return TicketMailMessageResult(failed=True, detail="empty_message")

    try:
        return process_ticket_mail_message(raw_message, settings)
    except Exception as error:
        LOGGER.exception("Ticket mail message processing failed for UID %s", uid)
        return TicketMailMessageResult(failed=True, detail=str(error))


def process_ticket_mail_message(
    raw_message: bytes,
    settings: Settings | None = None,
    confirm_url: Callable[[str], bool] | None = None,
) -> TicketMailMessageResult:
    settings = settings or get_settings()
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    text = extract_message_text(message)

    with SessionLocal() as db:
        user, recipient_address = _target_user_context(db, message, settings)
        target_user_id = user.id if user is not None else None

    confirmed = 0
    if settings.ticket_mail_auto_confirm_enabled:
        confirmed = confirm_nspk_email_links(text, confirm_url=confirm_url)
        if confirmed and target_user_id is not None:
            LOGGER.warning("Confirmed NSPK fiscal email for user %s", target_user_id)
            _notify_ticket_mail_confirmed(target_user_id, recipient_address)

    normalized = normalize_ocr_text(text)
    if not is_nspk_sbp_email(normalized):
        return TicketMailMessageResult(
            confirmed=confirmed,
            skipped=True,
            mark_seen=confirmed > 0 or not normalized,
            detail="not_nspk_ticket",
        )

    if target_user_id is None:
        return TicketMailMessageResult(
            confirmed=confirmed,
            skipped=True,
            mark_seen=False,
            detail="target_user_not_configured",
        )

    with SessionLocal() as db:
        user = db.get(User, target_user_id)
        if user is None:
            return TicketMailMessageResult(
                confirmed=confirmed,
                skipped=True,
                mark_seen=False,
                detail="target_user_not_configured",
            )
        status, ticket_id = _import_ticket_text(db, user, text)

    if status == "imported" and ticket_id is not None:
        _notify_ticket_uploaded(target_user_id, ticket_id)

    return TicketMailMessageResult(
        confirmed=confirmed,
        imported=int(status == "imported"),
        duplicate=status == "duplicate",
        mark_seen=status in {"imported", "duplicate"} or confirmed > 0,
        detail=status,
    )


def confirm_nspk_email_links(
    text: str,
    confirm_url: Callable[[str], bool] | None = None,
) -> int:
    urls = sorted(set(NSPK_CONFIRM_URL_RE.findall(html.unescape(text))))
    if not urls:
        return 0

    confirmer = confirm_url or _confirm_url_with_http
    confirmed = 0
    for url in urls:
        try:
            if confirmer(url):
                confirmed += 1
        except Exception:
            LOGGER.exception("NSPK email confirmation failed for %s", url)
    return confirmed


def extract_message_text(message: Message) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            if _is_attachment(part):
                continue
            text = _text_from_part(part)
            if text:
                parts.append(text)
    else:
        text = _text_from_part(message)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _raw_message_from_fetch(fetch_data: list[bytes | tuple[bytes, bytes]]) -> bytes | None:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _is_attachment(part: Message) -> bool:
    disposition = (part.get_content_disposition() or "").lower()
    return disposition == "attachment"


def _text_from_part(part: Message) -> str | None:
    content_type = part.get_content_type()
    if content_type not in {"text/plain", "text/html"}:
        return None

    if isinstance(part, EmailMessage):
        payload = part.get_content()
        text = str(payload)
    else:
        raw_payload = part.get_payload(decode=True)
        if raw_payload is None:
            return None
        charset = part.get_content_charset() or "utf-8"
        text = raw_payload.decode(charset, errors="replace")

    if content_type == "text/html":
        return _html_to_text(text)
    return html.unescape(text)


def _html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return html.unescape(parser.text)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return "\n".join(part.strip() for part in self._parts if part.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data)


def _confirm_url_with_http(url: str) -> bool:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        return _confirm_nspk_email_url(client, url)


def _confirm_nspk_email_url(client: httpx.Client, url: str) -> bool:
    token = _nspk_confirm_token_from_url(url)
    if token is None:
        return False

    response = client.post(NSPK_CONFIRM_EMAIL_API_URL, json={"token": token})
    if response.status_code >= 400:
        return False

    try:
        data = response.json()
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("responseStatus") == "SUCCESS"


def _nspk_confirm_token_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path_prefix = "/auth/confirm-fiscal-email/"
    if parsed.netloc.casefold() != "bilet.nspk.ru":
        return None
    if not parsed.path.startswith(path_prefix):
        return None
    token = parsed.path[len(path_prefix) :].strip("/")
    return token or None


def _target_user(db: Session, settings: Settings) -> User | None:
    if settings.ticket_mail_target_user_id:
        user = db.get(User, settings.ticket_mail_target_user_id)
        if user is not None:
            return user
    if settings.ticket_mail_target_user_token:
        return db.scalar(select(User).where(User.access_token == settings.ticket_mail_target_user_token))
    return None


def _target_user_context(
    db: Session,
    message: Message,
    settings: Settings,
) -> tuple[User | None, str | None]:
    for address in _recipient_addresses(message):
        code = _ticket_mail_code_from_address(address)
        if not code:
            continue
        user = db.scalar(select(User).where(User.ticket_mail_code == code))
        if user is not None:
            return user, address
    return _target_user(db, settings), None


def _target_user_from_message(db: Session, message: Message) -> User | None:
    for address in _recipient_addresses(message):
        code = _ticket_mail_code_from_address(address)
        if not code:
            continue
        user = db.scalar(select(User).where(User.ticket_mail_code == code))
        if user is not None:
            return user
    return None


def _recipient_addresses(message: Message) -> list[str]:
    headers = [
        "to",
        "cc",
        "bcc",
        "delivered-to",
        "x-original-to",
        "envelope-to",
        "resent-to",
    ]
    values: list[str] = []
    for header in headers:
        values.extend(message.get_all(header, []))
    return [address.casefold() for _, address in getaddresses(values) if address]


def _ticket_mail_code_from_address(address: str) -> str | None:
    local_part = address.split("@", 1)[0].casefold()
    match = re.search(r"(?:^|[+._-])(?P<code>[a-f0-9]{10})(?:$|[+._-])", local_part)
    return match.group("code") if match else None


def _notify_ticket_mail_confirmed(user_id: str, address: str | None) -> None:
    coroutine = notify_ticket_mail_confirmed(user_id, address)
    _run_or_schedule_notification(coroutine)


def _notify_ticket_uploaded(user_id: str, ticket_id: str) -> None:
    coroutine = notify_ticket_uploaded(user_id, ticket_id)
    _run_or_schedule_notification(coroutine)


def _run_or_schedule_notification(coroutine: asyncio.coroutines.Coroutine) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coroutine)
    else:
        loop.create_task(coroutine)


def _import_ticket_text(db: Session, user: User, text: str) -> tuple[str, str | None]:
    parsed = parse_ticket_text(text)
    if not parsed.ticket_number:
        return "parse_failed", None

    ticket_key = _ticket_key(parsed.fiscal_series, parsed.ticket_number)
    duplicate = db.scalar(select(Ticket).where(Ticket.ticket_key == ticket_key))
    if duplicate is not None:
        return "duplicate", duplicate.id

    happiness = score_ticket_number(parsed.ticket_number[-4:])
    ticket = Ticket(
        user_id=user.id,
        ticket_key=ticket_key,
        ticket_number=parsed.ticket_number,
        fiscal_series=parsed.fiscal_series,
        source_format=parsed.source_format,
        status=_default_ticket_status(parsed.source_format),
        purchased_at=parsed.purchased_at,
        route_number=parsed.route_number,
        price_rub=Decimal(parsed.price_rub) if parsed.price_rub is not None else None,
        raw_ocr_text=text,
        parsed_payload=parsed.model_dump(mode="json"),
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketHappiness(
            ticket_id=ticket.id,
            degree=happiness.degree,
            points=happiness.points,
            label=happiness.label,
            reasons={
                "reasons": happiness.reasons,
                "matched_rules": happiness.matched_rules,
            },
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "duplicate", None
    return "imported", ticket.id


def _ticket_key(fiscal_series: str | None, ticket_number: str) -> str:
    series = fiscal_series.strip().upper() if fiscal_series else "NO_SERIES"
    number = ticket_number.strip().upper()
    return f"{series}:{number}"


def _default_ticket_status(source_format: str) -> str:
    if source_format in {"ekarta_ek_qr_pdf_v1", "nspk_sbp_email_v1"}:
        return "verified"
    return "pending_check"
