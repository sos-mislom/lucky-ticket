from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import random
from typing import Any

import httpx

from app.core.settings import get_settings
from app.db.models import Ticket, User
from app.db.session import SessionLocal


LOGGER = logging.getLogger(__name__)
NOTIFICATION_TIMEOUT = 20
TELEGRAM_NOTIFICATION_ATTEMPTS = 3


async def notify_ticket_uploaded(user_id: str, ticket_id: str, origin: str | None = None) -> None:
    try:
        settings = get_settings()
        if not settings.messenger_notifications_enabled:
            return

        with SessionLocal() as db:
            user = db.get(User, user_id)
            ticket = db.get(Ticket, ticket_id)
            if user is None or ticket is None:
                return
            await _send_to_linked_messengers(user, _ticket_uploaded_message(ticket), skip_provider=origin)
    except Exception:
        LOGGER.exception("Ticket upload notification failed for ticket %s", ticket_id)


async def notify_ticket_check_status(
    ticket_id: str,
    official_status: str | None = None,
    detail: str | None = None,
) -> None:
    try:
        settings = get_settings()
        if not settings.messenger_notifications_enabled:
            return

        with SessionLocal() as db:
            ticket = db.get(Ticket, ticket_id)
            if ticket is None:
                return
            user = db.get(User, ticket.user_id)
            if user is None:
                return

            status = official_status or _last_official_status(ticket) or ticket.status
            notification_key = f"official-status:{status}"
            payload = _ticket_payload(ticket)
            if payload.get("last_status_notification_key") == notification_key:
                return

            sent = await _send_to_linked_messengers(
                user,
                _ticket_check_status_message(ticket, status, detail),
            )
            if sent:
                payload["last_status_notification_key"] = notification_key
                payload["last_status_notification_at"] = datetime.now(UTC).isoformat()
                ticket.parsed_payload = payload
                db.commit()
    except Exception:
        LOGGER.exception("Ticket status notification failed for ticket %s", ticket_id)


async def notify_ticket_mail_confirmed(user_id: str, address: str | None = None) -> None:
    try:
        settings = get_settings()
        if not settings.messenger_notifications_enabled:
            return

        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is None:
                return
            await _send_to_linked_messengers(user, _ticket_mail_confirmed_message(address))
    except Exception:
        LOGGER.exception("Ticket mail confirmation notification failed for user %s", user_id)


async def _send_to_linked_messengers(
    user: User,
    text: str,
    skip_provider: str | None = None,
) -> bool:
    settings = get_settings()
    calls = []
    if settings.tg_bot_token and user.telegram_external_id and skip_provider != "telegram":
        calls.append(
            (
                "telegram",
                _send_telegram_notification(settings.tg_bot_token, user.telegram_external_id, text),
            )
        )
    if settings.vk_bot_token and user.vk_external_id and skip_provider != "vk":
        calls.append(
            (
                "vk",
                _send_vk_notification(
                    settings.vk_bot_token,
                    settings.vk_api_version,
                    user.vk_external_id,
                    text,
                ),
            )
        )
    if not calls:
        return False

    providers = [provider for provider, _ in calls]
    results = await asyncio.gather(*(call for _, call in calls), return_exceptions=True)

    sent = False
    for provider, result in zip(providers, results, strict=True):
        if isinstance(result, Exception):
            LOGGER.warning("Messenger notification failed via %s: %r", provider, result)
        else:
            sent = True
    return sent


async def _send_telegram_notification(token: str, chat_id: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=NOTIFICATION_TIMEOUT) as client:
        await _send_telegram_message(client, token, chat_id, text)


async def _send_vk_notification(token: str, api_version: str, peer_id: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=NOTIFICATION_TIMEOUT) as client:
        await _send_vk_message(client, token, api_version, peer_id, text)


async def _send_telegram_message(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    text: str,
) -> None:
    last_error: Exception | None = None
    for attempt in range(TELEGRAM_NOTIFICATION_ATTEMPTS):
        try:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            response.raise_for_status()
            return
        except (httpx.TimeoutException, httpx.TransportError) as error:
            last_error = error
            if attempt + 1 < TELEGRAM_NOTIFICATION_ATTEMPTS:
                await asyncio.sleep(1)
    if last_error is not None:
        raise last_error


async def _send_vk_message(
    client: httpx.AsyncClient,
    token: str,
    api_version: str,
    peer_id: str,
    text: str,
) -> None:
    response = await client.post(
        "https://api.vk.com/method/messages.send",
        data={
            "access_token": token,
            "v": api_version,
            "peer_id": peer_id,
            "message": text,
            "random_id": random.randint(1, 2**31 - 1),
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        message = payload["error"].get("error_msg", "VK API error")
        raise RuntimeError(message)


def _ticket_uploaded_message(ticket: Ticket) -> str:
    lines = [
        "Билет подгрузился.",
        *_ticket_summary(ticket),
    ]
    if ticket.status == "verified":
        lines.append("Статус проверки: проверен.")
    else:
        lines.append("Статус проверки: ждет официальной проверки.")
        lines.append("Когда статус обновится, я пришлю отдельное уведомление.")
    return "\n".join(lines)


def _ticket_check_status_message(ticket: Ticket, official_status: str, detail: str | None) -> str:
    lines = [
        "Обновился статус проверки билета.",
        *_ticket_summary(ticket),
    ]
    if ticket.status == "verified" or official_status == "verified":
        lines.append("Статус проверки: проверен.")
    elif official_status == "not_found":
        lines.append("Статус проверки: официальный сайт пока не нашел билет.")
        lines.append("Оставляю билет в очереди и проверю снова позже.")
    elif official_status == "error":
        lines.append("Статус проверки: временная ошибка официальной проверки.")
        lines.append("Попробую снова позже.")
    else:
        lines.append(f"Статус проверки: {_status_label(ticket.status)}.")
    if detail:
        lines.append(f"Комментарий: {detail}")
    return "\n".join(lines)


def _ticket_mail_confirmed_message(address: str | None) -> str:
    lines = [
        "Почта для билетов подтверждена.",
        "Теперь письма от Мир Транспорт можно автоматически добавлять в профиль.",
    ]
    if address:
        lines.append(f"Адрес: {address}")
    return "\n".join(lines)


def _ticket_summary(ticket: Ticket) -> list[str]:
    happiness = ticket.happiness
    lines = [
        f"Номер: {ticket.ticket_number[-4:]}",
        f"Дата: {_ticket_day(ticket)}",
    ]
    if ticket.route_number:
        lines.append(f"Маршрут: {ticket.route_number}")
    if happiness is not None:
        lines.append(f"Класс: {happiness.label} ({happiness.degree})")
        lines.append(f"Очки: {happiness.points}")
    return lines


def _ticket_day(ticket: Ticket) -> str:
    value = ticket.purchased_at or ticket.created_at
    return value.date().isoformat()


def _status_label(status: str) -> str:
    if status == "verified":
        return "проверен"
    if status == "pending_check":
        return "ждет проверки"
    if status == "not_found":
        return "не найден у фискализатора"
    if status == "check_error":
        return "ошибка проверки"
    if status == "parsed":
        return "распознан"
    return status


def _last_official_status(ticket: Ticket) -> str | None:
    check = _ticket_payload(ticket).get("last_official_check")
    if isinstance(check, dict):
        status = check.get("status")
        if isinstance(status, str):
            return status
    return None


def _ticket_payload(ticket: Ticket) -> dict[str, Any]:
    return dict(ticket.parsed_payload) if isinstance(ticket.parsed_payload, dict) else {}
