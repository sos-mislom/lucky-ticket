from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import os
import socket
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx


API_TIMEOUT = 20
RETRY_DELAY = 5
TICKETS_PAGE_SIZE = 8
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def _load_dotenv() -> None:
    env_path = os.getenv("ENV_FILE", ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _prefer_ipv4_dns() -> None:
    def getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
        results = _ORIGINAL_GETADDRINFO(*args, **kwargs)
        ipv4_results = [result for result in results if result[0] == socket.AF_INET]
        return ipv4_results or results

    socket.getaddrinfo = getaddrinfo


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def _public_web_url() -> str:
    return os.getenv("PUBLIC_WEB_URL", "http://127.0.0.1:5173").rstrip("/")


def _lk_url(access_token: str, view: str = "tickets") -> str:
    return f"{_public_web_url()}/?{urlencode({'token': access_token, 'view': view})}"


def _account_keyboard(access_token: str) -> dict[str, Any]:
    tickets_url = _lk_url(access_token, "tickets")
    profile_url = _lk_url(access_token, "profile")
    tickets_button: dict[str, Any] = {"text": "Открыть ЛК и камеру", "url": tickets_url}
    if tickets_url.startswith("https://"):
        tickets_button = {"text": "Открыть ЛК и камеру", "web_app": {"url": tickets_url}}
    return {
        "inline_keyboard": [
            [tickets_button],
            [{"text": "Профиль", "url": profile_url}],
        ]
    }


def _internal_headers() -> dict[str, str]:
    token = os.getenv("INTERNAL_API_TOKEN", "")
    return {"X-Internal-Token": token} if token else {}


def _summary_zone() -> ZoneInfo:
    return ZoneInfo(os.getenv("DAILY_SUMMARY_TZ", "Asia/Yekaterinburg"))


def _summary_time() -> time:
    raw_value = os.getenv("DAILY_SUMMARY_TIME", "23:00")
    hour, minute = raw_value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def _telegram_display_name(tg_user: dict[str, Any]) -> str:
    return (
        " ".join(
            part
            for part in [tg_user.get("first_name"), tg_user.get("last_name")]
            if isinstance(part, str) and part.strip()
        ).strip()
        or tg_user.get("username")
        or f"tg-{tg_user.get('id')}"
    )


def _telegram_avatar_url(tg_user: dict[str, Any]) -> str | None:
    username = tg_user.get("username")
    if isinstance(username, str) and username.strip():
        return f"https://t.me/i/userpic/320/{username.strip().lstrip('@')}.jpg"
    return None


def _is_link_code(text: str) -> bool:
    return text.isdigit() and len(text) == 6


async def _register_user(client: httpx.AsyncClient, backend_url: str, message: dict[str, Any]) -> dict[str, Any]:
    tg_user = message.get("from") or {}
    response = await client.post(
        f"{backend_url}/api/users/register",
        json={
            "display_name": _telegram_display_name(tg_user),
            "source": "telegram",
            "external_id": str(tg_user.get("id")),
            "username": tg_user.get("username"),
            "avatar_url": _telegram_avatar_url(tg_user),
        },
    )
    response.raise_for_status()
    return response.json()


async def _link_user(
    client: httpx.AsyncClient,
    backend_url: str,
    message: dict[str, Any],
    code: str,
) -> dict[str, Any]:
    tg_user = message.get("from") or {}
    response = await client.post(
        f"{backend_url}/api/bot/telegram/link",
        json={
            "code": code,
            "telegram_id": str(tg_user.get("id")),
            "username": tg_user.get("username"),
            "display_name": _telegram_display_name(tg_user),
            "avatar_url": _telegram_avatar_url(tg_user),
        },
    )
    response.raise_for_status()
    return response.json()


async def _submit_ticket_file(
    client: httpx.AsyncClient,
    backend_url: str,
    user_id: str,
    access_token: str,
    content: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    response = await client.post(
        f"{backend_url}/api/users/{user_id}/tickets/upload",
        headers={"X-User-Token": access_token, "X-Ticket-Origin": "telegram"},
        files={"file": (filename, content, content_type)},
    )
    response.raise_for_status()
    return response.json()


async def _fetch_ticket_page(
    client: httpx.AsyncClient,
    backend_url: str,
    user_id: str,
    access_token: str,
    page: int,
) -> dict[str, Any]:
    page = max(1, page)
    response = await client.get(
        f"{backend_url}/api/users/{user_id}/tickets",
        headers={"X-User-Token": access_token},
        params={"limit": TICKETS_PAGE_SIZE, "offset": (page - 1) * TICKETS_PAGE_SIZE},
    )
    response.raise_for_status()
    return response.json()


async def _download_telegram_file(
    client: httpx.AsyncClient,
    token: str,
    file_id: str,
) -> tuple[bytes, str]:
    file_response = await client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
    file_response.raise_for_status()
    file_path = file_response.json()["result"]["file_path"]
    content_response = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
    content_response.raise_for_status()
    return content_response.content, file_path


async def _send_message(
    client: httpx.AsyncClient,
    token: str,
    chat_id: int,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
    )
    response.raise_for_status()
    return response.json()


async def _edit_message_text(
    client: httpx.AsyncClient,
    token: str,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = await client.post(
        f"https://api.telegram.org/bot{token}/editMessageText",
        json=payload,
    )
    response.raise_for_status()


async def _answer_callback_query(client: httpx.AsyncClient, token: str, callback_id: str) -> None:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
        json={"callback_query_id": callback_id},
    )
    response.raise_for_status()


def _ticket_reply(ticket: dict[str, Any], include_class: bool = False) -> str:
    lines = [
        f"Билет засчитан за {ticket['day']}.",
        f"Номер: {ticket['ticket_number'][-4:]}",
    ]
    if include_class:
        lines.append(f"Класс: {ticket['official_label']} ({ticket['official_degree']})")
    else:
        lines.append(f"Очков: {ticket['official_points']}")
    lines.append(f"Статус: {_status_label(ticket['status'])}")
    return "\n".join(lines)


def _status_label(status: str) -> str:
    if status == "verified":
        return "проверен"
    if status == "pending_check":
        return "ждет проверки"
    if status == "not_found":
        return "не найден у фискализатора"
    if status == "check_error":
        return "ошибка проверки"
    return status


def _ticket_page_from_text(text: str) -> int | None:
    parts = text.strip().split()
    if not parts:
        return None
    first = parts[0].split("@", 1)[0].casefold()
    normalized = text.casefold().strip()
    if first not in {"/tickets", "/history"} and not (
        normalized == "билеты"
        or normalized == "история"
        or normalized.startswith("билеты ")
        or normalized.startswith("история ")
    ):
        return None
    if len(parts) >= 2 and parts[1].isdigit():
        return max(1, int(parts[1]))
    return 1


def _format_ticket_list(user: dict[str, Any], page_data: dict[str, Any]) -> str:
    total = int(page_data["total"])
    if total == 0:
        return (
            f"Сохраненных билетов пока нет.\n"
            f"{user['display_name']}, пришли фото или PDF билета сюда, и я добавлю его в список."
        )

    lines = [
        f"Сохраненные билеты: {user['display_name']}",
        f"Страница {page_data['page']} из {page_data['page_count']} · всего {total}",
        "",
    ]
    offset = int(page_data["offset"])
    for index, ticket in enumerate(page_data["items"], start=offset + 1):
        route = f" · маршрут {ticket['route_number']}" if ticket.get("route_number") else ""
        lines.append(
            f"{index}. {ticket['day']} · {ticket['ticket_number'][-4:]}{route} · "
            f"{_status_label(ticket['status'])} · класс {ticket['official_degree']} · "
            f"{ticket['official_points']} очк."
        )
    return "\n".join(lines)


def _ticket_list_keyboard(access_token: str, page_data: dict[str, Any]) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    nav: list[dict[str, Any]] = []
    if page_data.get("prev_offset") is not None:
        nav.append({"text": "Назад", "callback_data": f"tickets:{int(page_data['page']) - 1}"})
    if page_data.get("next_offset") is not None:
        nav.append({"text": "Дальше", "callback_data": f"tickets:{int(page_data['page']) + 1}"})
    if nav:
        rows.append(nav)
    rows.extend(_account_keyboard(access_token)["inline_keyboard"])
    return {"inline_keyboard": rows}


async def _send_ticket_list(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    message: dict[str, Any],
    page: int,
) -> None:
    chat_id = message["chat"]["id"]
    data = await _register_user(client, backend_url, message)
    page_data = await _fetch_ticket_page(
        client,
        backend_url,
        data["user"]["id"],
        data["access_token"],
        page,
    )
    await _send_message(
        client,
        token,
        chat_id,
        _format_ticket_list(data["user"], page_data),
        reply_markup=_ticket_list_keyboard(data["access_token"], page_data),
    )


async def _handle_callback_query(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    callback_query: dict[str, Any],
) -> None:
    callback_id = callback_query.get("id")
    callback_data = str(callback_query.get("data") or "")
    if not callback_data.startswith("tickets:"):
        if callback_id:
            await _answer_callback_query(client, token, callback_id)
        return
    try:
        page = max(1, int(callback_data.split(":", 1)[1]))
    except ValueError:
        page = 1

    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None:
        return

    data = await _register_user(client, backend_url, {"from": callback_query.get("from") or {}})
    page_data = await _fetch_ticket_page(
        client,
        backend_url,
        data["user"]["id"],
        data["access_token"],
        page,
    )
    await _edit_message_text(
        client,
        token,
        int(chat_id),
        int(message_id),
        _format_ticket_list(data["user"], page_data),
        reply_markup=_ticket_list_keyboard(data["access_token"], page_data),
    )
    if callback_id:
        await _answer_callback_query(client, token, callback_id)


async def _submit_file_and_reply(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    message: dict[str, Any],
    content: bytes,
    filename: str,
    content_type: str,
) -> None:
    chat_id = message["chat"]["id"]
    data = await _register_user(client, backend_url, message)
    try:
        submitted = await _submit_ticket_file(
            client,
            backend_url,
            data["user"]["id"],
            data["access_token"],
            content,
            filename,
            content_type,
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 409:
            await _send_message(
                client,
                token,
                chat_id,
                "Этот билет уже был засчитан.",
                reply_markup=_account_keyboard(data["access_token"]),
            )
            return
        await _send_message(
            client,
            token,
            chat_id,
            "Не распознал билет. Пришли четкое фото или PDF, либо открой ЛК и сними камерой.",
            reply_markup=_account_keyboard(data["access_token"]),
        )
        return
    await _send_message(
        client,
        token,
        chat_id,
        _ticket_reply(submitted["ticket"], include_class=True),
        reply_markup=_account_keyboard(data["access_token"]),
    )


async def _handle_message(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    message: dict[str, Any],
) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    text = (message.get("text") or "").strip()
    ticket_page = _ticket_page_from_text(text)
    if ticket_page is not None:
        await _send_ticket_list(client, token, backend_url, message, ticket_page)
        return

    if text.startswith("/start"):
        data = await _register_user(client, backend_url, message)
        user = data["user"]
        status = "создан" if data["created"] else "обновлен"
        await _send_message(
            client,
            token,
            chat_id,
            (
                f"Профиль {status}: {user['display_name']}\n"
                f"Билетов: {user['tickets_count']}\n"
                f"Очков: {user['points']}\n\n"
                "Можно прислать фото/PDF билета сюда или открыть ЛК с камерой.\n"
                "Список сохраненных билетов: /tickets"
            ),
            reply_markup=_account_keyboard(data["access_token"]),
        )
        return

    if text.startswith("/link") or _is_link_code(text):
        parts = text.split(maxsplit=1)
        code = text if _is_link_code(text) else parts[1].strip() if len(parts) == 2 else ""
        if not code:
            await _send_message(client, token, chat_id, "Пришли команду так: /link 123456")
            return
        try:
            linked = await _link_user(client, backend_url, message, code)
        except httpx.HTTPStatusError:
            await _send_message(client, token, chat_id, "Код не подошел или аккаунт уже привязан.")
            return
        await _send_message(
            client,
            token,
            chat_id,
            f"Telegram привязан к профилю {linked['user']['display_name']}.",
            reply_markup=_account_keyboard(linked["access_token"]),
        )
        return

    if text.startswith("/profile"):
        data = await _register_user(client, backend_url, message)
        user = data["user"]
        await _send_message(
            client,
            token,
            chat_id,
            f"{user['display_name']}\nБилетов: {user['tickets_count']}\nОчков: {user['points']}",
            reply_markup=_account_keyboard(data["access_token"]),
        )
        return

    if text.startswith("/day"):
        data = await _register_user(client, backend_url, message)
        today = datetime.now(_summary_zone()).date()
        profile_response = await client.get(
            f"{backend_url}/api/users/{data['user']['id']}/profile",
            headers={"X-User-Token": data["access_token"]},
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
        tickets = [ticket for ticket in profile["tickets"] if ticket["day"] == today.isoformat()]
        stats = next(
            (point for point in profile["daily_stats"] if point["day"] == today.isoformat()),
            _empty_stats(today),
        )
        await _send_message(
            client,
            token,
            chat_id,
            _format_daily_summary(data["user"], today, stats, tickets),
            reply_markup=_account_keyboard(data["access_token"]),
        )
        return

    if message.get("document"):
        document = message["document"]
        file_name = document.get("file_name", "ticket")
        mime_type = document.get("mime_type", "application/octet-stream")
        if not (
            file_name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
            or mime_type == "application/pdf"
            or mime_type.startswith("image/")
        ):
            await _send_message(client, token, chat_id, "Принимаю PDF или фото билета.")
            return
        content, _ = await _download_telegram_file(client, token, document["file_id"])
        await _submit_file_and_reply(client, token, backend_url, message, content, file_name, mime_type)
        return

    if message.get("photo"):
        photo = max(message["photo"], key=lambda item: item.get("file_size", 0))
        content, file_path = await _download_telegram_file(client, token, photo["file_id"])
        await _submit_file_and_reply(client, token, backend_url, message, content, file_path or "ticket.jpg", "image/jpeg")
        return

    if text and not text.startswith("/"):
        await _send_message(client, token, chat_id, "Для зачета пришли PDF или фото билета. 4 цифры можно проверить на сайте.")
        return

    await _send_message(client, token, chat_id, "Пришли PDF-билет или фото, и я засчитаю его.")


def _empty_stats(day: date) -> dict[str, Any]:
    return {
        "day": day.isoformat(),
        "tickets_count": 0,
        "verified_tickets_count": 0,
        "official_points": 0,
        "personal_points": 0,
        "best_ticket": None,
        "best_degree": None,
    }


def _format_daily_summary(
    user: dict[str, Any],
    day: date,
    stats: dict[str, Any],
    tickets: list[dict[str, Any]],
) -> str:
    lines = [
        f"Итоги дня {day.isoformat()}",
        f"{user['display_name']}",
        f"Билетов: {stats['tickets_count']}",
        f"Проверенных: {stats['verified_tickets_count']}",
        f"Официальные очки: {stats['official_points']}",
        f"Личная шкала: {stats['personal_points']}",
    ]
    if stats.get("best_ticket"):
        lines.append(f"Лучший билет: {stats['best_ticket']} · класс {stats['best_degree']}")
    if tickets:
        lines.append("")
        lines.append("Билеты:")
        for ticket in tickets[:12]:
            lines.append(
                f"· {ticket['ticket_number'][-4:]} · {_status_label(ticket['status'])} · "
                f"класс {ticket['official_degree']} · {ticket['official_points']} очк."
            )
        if len(tickets) > 12:
            lines.append(f"Еще билетов: {len(tickets) - 12}")
    return "\n".join(lines)


async def _send_daily_digests(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    day: date,
) -> None:
    response = await client.get(
        f"{backend_url}/api/bot/telegram/daily-digests",
        headers=_internal_headers(),
        params={"day": day.isoformat()},
    )
    response.raise_for_status()
    for digest in response.json():
        await _send_message(
            client,
            token,
            digest["chat_id"],
            _format_daily_summary(digest["user"], day, digest["stats"], digest["tickets"]),
        )


async def _poll_updates(client: httpx.AsyncClient, token: str, backend_url: str) -> None:
    offset = 0
    while True:
        try:
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={
                    "timeout": 25,
                    "offset": offset,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=35,
            )
            response.raise_for_status()
            payload = response.json()
            for update in payload.get("result", []):
                offset = max(offset, update["update_id"] + 1)
                try:
                    callback_query = update.get("callback_query")
                    if callback_query:
                        await _handle_callback_query(client, token, backend_url, callback_query)
                        continue
                    message = update.get("message")
                    if not message:
                        continue
                    await _handle_message(client, token, backend_url, message)
                except (httpx.HTTPError, KeyError, ValueError) as error:
                    print(f"Message handling failed: {type(error).__name__}", flush=True)
        except httpx.HTTPError as error:
            print(f"Telegram polling failed: {type(error).__name__}", flush=True)
            await asyncio.sleep(RETRY_DELAY)


async def _daily_summary_loop(client: httpx.AsyncClient, token: str, backend_url: str) -> None:
    sent_days: set[str] = set()
    while True:
        zone = _summary_zone()
        now = datetime.now(zone)
        target = datetime.combine(now.date(), _summary_time(), tzinfo=zone)
        day_key = now.date().isoformat()
        if now >= target and day_key not in sent_days:
            try:
                await _send_daily_digests(client, token, backend_url, now.date())
                sent_days.add(day_key)
                sent_days = set(sorted(sent_days)[-7:])
            except httpx.HTTPError as error:
                print(f"Daily digest failed: {type(error).__name__}", flush=True)

        next_target = target if now < target else target + timedelta(days=1)
        seconds = max(60, min(300, int((next_target - now).total_seconds())))
        await asyncio.sleep(seconds)


async def run() -> None:
    _load_dotenv()
    token = _required_env("TG_BOT_TOKEN")
    backend_url = _backend_url()
    timeout = httpx.Timeout(API_TIMEOUT, connect=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except httpx.HTTPError as error:
            print(f"Telegram webhook cleanup failed: {type(error).__name__}", flush=True)
        await asyncio.gather(
            _poll_updates(client, token, backend_url),
            _daily_summary_loop(client, token, backend_url),
        )


if __name__ == "__main__":
    asyncio.run(run())
