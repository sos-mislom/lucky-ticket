from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import json
import os
import random
import re
import socket
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx


API_TIMEOUT = 20
API_VERSION = "5.199"
RETRY_DELAY = 5
TICKETS_PAGE_SIZE = 8
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


class VkApiError(RuntimeError):
    pass


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


def _account_keyboard(access_token: str) -> str:
    return json.dumps(
        {
            "one_time": False,
            "inline": True,
            "buttons": [
                [
                    {
                        "action": {
                            "type": "open_link",
                            "label": "Открыть ЛК и камеру",
                            "link": _lk_url(access_token, "tickets"),
                        }
                    }
                ],
                [
                    {
                        "action": {
                            "type": "open_link",
                            "label": "Профиль",
                            "link": _lk_url(access_token, "profile"),
                        }
                    }
                ],
            ],
        },
        ensure_ascii=False,
    )


def _internal_headers() -> dict[str, str]:
    token = os.getenv("INTERNAL_API_TOKEN", "")
    return {"X-Internal-Token": token} if token else {}


def _whyfi_backend_url() -> str:
    return os.getenv("WHYFI_BACKEND_URL", "").strip().rstrip("/")


def _whyfi_headers() -> dict[str, str]:
    token = os.getenv("WHYFI_INTERNAL_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _summary_zone() -> ZoneInfo:
    return ZoneInfo(os.getenv("DAILY_SUMMARY_TZ", "Asia/Yekaterinburg"))


def _summary_time() -> time:
    raw_value = os.getenv("DAILY_SUMMARY_TIME", "23:00")
    hour, minute = raw_value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


async def _vk_api(client: httpx.AsyncClient, token: str, method: str, **params: Any) -> Any:
    payload = {"access_token": token, "v": API_VERSION, **params}
    response = await client.post(f"https://api.vk.com/method/{method}", data=payload)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        error = data["error"]
        raise VkApiError(f"{method}: {error.get('error_msg', 'VK API error')}")
    return data.get("response")


async def _resolve_group_id(client: httpx.AsyncClient, token: str) -> int:
    env_group_id = os.getenv("VK_GROUP_ID", "").strip()
    if env_group_id:
        return abs(int(env_group_id))

    response = await _vk_api(client, token, "groups.getById")
    groups = response.get("groups") if isinstance(response, dict) else response
    if isinstance(groups, list) and groups:
        return abs(int(groups[0]["id"]))
    if isinstance(response, dict) and response.get("id"):
        return abs(int(response["id"]))
    raise VkApiError("Не смог определить группу. Добавь VK_GROUP_ID в .env.")


async def _get_long_poll_server(client: httpx.AsyncClient, token: str, group_id: int) -> dict[str, str]:
    response = await _vk_api(client, token, "groups.getLongPollServer", group_id=group_id)
    return {
        "server": response["server"],
        "key": response["key"],
        "ts": response["ts"],
    }


async def _vk_user(client: httpx.AsyncClient, token: str, user_id: int) -> dict[str, Any]:
    try:
        users = await _vk_api(
            client,
            token,
            "users.get",
            user_ids=str(user_id),
            fields="screen_name,photo_200",
        )
    except (VkApiError, httpx.HTTPError):
        return {"id": user_id}
    if isinstance(users, list) and users:
        return users[0]
    return {"id": user_id}


def _vk_display_name(user: dict[str, Any], user_id: int) -> str:
    return (
        " ".join(
            part
            for part in [user.get("first_name"), user.get("last_name")]
            if isinstance(part, str) and part.strip()
        ).strip()
        or user.get("screen_name")
        or f"vk-{user_id}"
    )


def _extract_whyfi_login_token(message: dict[str, Any], text: str) -> str:
    candidates: list[str] = [text]
    for key in ("ref", "ref_source", "payload"):
        value = message.get(key)
        if isinstance(value, str):
            candidates.append(value)
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                for nested_key in ("request_token", "token", "ref", "command"):
                    nested_value = parsed.get(nested_key)
                    if isinstance(nested_value, str):
                        candidates.append(nested_value)
    for value in candidates:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        match = re.search(r"(?:^|[\s:/?&=])(?:/)?whyfi[_\s-]+([A-Za-z0-9_-]{16,})", normalized, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{24,}", normalized):
            return normalized
    return ""


async def _approve_whyfi_login(
    client: httpx.AsyncClient,
    vk_token: str,
    vk_user_id: int,
    request_token: str,
) -> dict[str, Any]:
    backend_url = _whyfi_backend_url()
    headers = _whyfi_headers()
    if not backend_url or not headers:
        raise RuntimeError("WHYFI VK bridge is not configured")
    vk_user = await _vk_user(client, vk_token, vk_user_id)
    response = await client.post(
        f"{backend_url}/api/internal/web-auth/vk/approve",
        headers=headers,
        json={
            "request_token": request_token,
            "vk_id": str(vk_user_id),
            "username": vk_user.get("screen_name"),
            "display_name": _vk_display_name(vk_user, vk_user_id),
            "first_name": vk_user.get("first_name"),
        },
    )
    response.raise_for_status()
    return response.json()


def _is_link_code(text: str) -> bool:
    return text.isdigit() and len(text) == 6


async def _register_user(
    client: httpx.AsyncClient,
    backend_url: str,
    token: str,
    vk_user_id: int,
) -> dict[str, Any]:
    vk_user = await _vk_user(client, token, vk_user_id)
    response = await client.post(
        f"{backend_url}/api/users/register",
        json={
            "display_name": _vk_display_name(vk_user, vk_user_id),
            "source": "vk",
            "external_id": str(vk_user_id),
            "username": vk_user.get("screen_name"),
            "avatar_url": vk_user.get("photo_200"),
        },
    )
    response.raise_for_status()
    return response.json()


async def _link_user(
    client: httpx.AsyncClient,
    backend_url: str,
    token: str,
    vk_user_id: int,
    code: str,
) -> dict[str, Any]:
    vk_user = await _vk_user(client, token, vk_user_id)
    response = await client.post(
        f"{backend_url}/api/bot/vk/link",
        json={
            "code": code,
            "vk_id": str(vk_user_id),
            "username": vk_user.get("screen_name"),
            "display_name": _vk_display_name(vk_user, vk_user_id),
            "avatar_url": vk_user.get("photo_200"),
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
        headers={"X-User-Token": access_token, "X-Ticket-Origin": "vk"},
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


async def _send_message(
    client: httpx.AsyncClient,
    token: str,
    peer_id: int,
    text: str,
    keyboard: str | None = None,
) -> None:
    params: dict[str, Any] = {
        "peer_id": peer_id,
        "message": text,
        "random_id": random.randint(1, 2**31 - 1),
    }
    if keyboard:
        params["keyboard"] = keyboard
    await _vk_api(client, token, "messages.send", **params)


async def _download_url(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    response = await client.get(url)
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]


def _photo_url(photo: dict[str, Any]) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return photo.get("photo_1280") or photo.get("photo_807") or photo.get("photo_604")
    best = max(sizes, key=lambda item: int(item.get("width", 0)) * int(item.get("height", 0)))
    return best.get("url")


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


def _ticket_page_from_text(text: str) -> int | None:
    parts = text.strip().split()
    if not parts:
        return None
    normalized = text.casefold().strip()
    first = parts[0].casefold()
    if first not in {"/tickets", "tickets", "/history", "history", "билеты", "история"}:
        return None
    if len(parts) >= 2 and parts[1].isdigit():
        return max(1, int(parts[1]))
    if normalized in {"билеты", "история"}:
        return 1
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


def _ticket_list_keyboard(access_token: str, page_data: dict[str, Any]) -> str:
    buttons: list[list[dict[str, Any]]] = []
    nav: list[dict[str, Any]] = []
    if page_data.get("prev_offset") is not None:
        nav.append(
            {
                "action": {
                    "type": "text",
                    "label": f"Билеты {int(page_data['page']) - 1}",
                },
                "color": "secondary",
            }
        )
    if page_data.get("next_offset") is not None:
        nav.append(
            {
                "action": {
                    "type": "text",
                    "label": f"Билеты {int(page_data['page']) + 1}",
                },
                "color": "secondary",
            }
        )
    if nav:
        buttons.append(nav)
    buttons.append(
        [
            {
                "action": {
                    "type": "open_link",
                    "label": "Открыть ЛК",
                    "link": _lk_url(access_token, "tickets"),
                }
            }
        ]
    )
    return json.dumps({"one_time": False, "inline": True, "buttons": buttons}, ensure_ascii=False)


async def _send_ticket_list(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    peer_id: int,
    vk_user_id: int,
    page: int,
) -> None:
    data = await _register_user(client, backend_url, token, vk_user_id)
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
        peer_id,
        _format_ticket_list(data["user"], page_data),
        keyboard=_ticket_list_keyboard(data["access_token"], page_data),
    )


async def _submit_file_and_reply(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    peer_id: int,
    vk_user_id: int,
    content: bytes,
    filename: str,
    content_type: str,
) -> None:
    data = await _register_user(client, backend_url, token, vk_user_id)
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
                peer_id,
                "Этот билет уже был засчитан.",
                keyboard=_account_keyboard(data["access_token"]),
            )
            return
        await _send_message(
            client,
            token,
            peer_id,
            "Не распознал билет. Пришли четкое фото или PDF, либо открой ЛК и сними камерой.",
            keyboard=_account_keyboard(data["access_token"]),
        )
        return
    await _send_message(
        client,
        token,
        peer_id,
        _ticket_reply(submitted["ticket"], include_class=True),
        keyboard=_account_keyboard(data["access_token"]),
    )


async def _handle_attachment(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    peer_id: int,
    vk_user_id: int,
    attachment: dict[str, Any],
) -> bool:
    attachment_type = attachment.get("type")
    if attachment_type == "photo":
        url = _photo_url(attachment.get("photo") or {})
        if not url:
            return False
        content, content_type = await _download_url(client, url)
        await _submit_file_and_reply(
            client,
            token,
            backend_url,
            peer_id,
            vk_user_id,
            content,
            "vk-ticket.jpg",
            content_type if content_type.startswith("image/") else "image/jpeg",
        )
        return True

    if attachment_type == "doc":
        doc = attachment.get("doc") or {}
        title = doc.get("title") or "vk-ticket"
        url = doc.get("url")
        ext = (doc.get("ext") or "").lower()
        if not url or ext not in {"pdf", "jpg", "jpeg", "png", "webp"}:
            return False
        content, content_type = await _download_url(client, url)
        if content_type == "application/octet-stream" and ext == "pdf":
            content_type = "application/pdf"
        await _submit_file_and_reply(
            client,
            token,
            backend_url,
            peer_id,
            vk_user_id,
            content,
            title,
            content_type,
        )
        return True

    return False


async def _send_profile(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    peer_id: int,
    vk_user_id: int,
) -> None:
    data = await _register_user(client, backend_url, token, vk_user_id)
    user = data["user"]
    await _send_message(
        client,
        token,
        peer_id,
        f"{user['display_name']}\nБилетов: {user['tickets_count']}\nОчков: {user['points']}",
        keyboard=_account_keyboard(data["access_token"]),
    )


async def _send_today(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    peer_id: int,
    vk_user_id: int,
) -> None:
    data = await _register_user(client, backend_url, token, vk_user_id)
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
        peer_id,
        _format_daily_summary(data["user"], today, stats, tickets),
        keyboard=_account_keyboard(data["access_token"]),
    )


async def _send_leaderboard(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    peer_id: int,
) -> None:
    response = await client.get(f"{backend_url}/api/leaderboard")
    response.raise_for_status()
    users = response.json()
    if not users:
        await _send_message(client, token, peer_id, "Топ пока пустой.")
        return
    lines = ["Топ счастливых билетиков:"]
    for index, user in enumerate(users[:10], start=1):
        handle = f" @{user['username']}" if user.get("username") else ""
        lines.append(f"{index}. {user['display_name']}{handle} · {user['points']} очков")
    await _send_message(client, token, peer_id, "\n".join(lines))


async def _handle_message(
    client: httpx.AsyncClient,
    token: str,
    backend_url: str,
    message: dict[str, Any],
) -> None:
    peer_id = message.get("peer_id")
    from_id = message.get("from_id")
    if peer_id is None or from_id is None or int(from_id) <= 0:
        return
    peer_id = int(peer_id)
    vk_user_id = int(from_id)
    text = (message.get("text") or "").strip()
    normalized = text.lower()
    whyfi_login_token = _extract_whyfi_login_token(message, text)
    if whyfi_login_token:
        try:
            await _approve_whyfi_login(client, token, vk_user_id, whyfi_login_token)
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code if error.response is not None else 0
            if status_code == 410:
                await _send_message(client, token, peer_id, "Ссылка входа WHYFI устарела. Открой приложение и начни вход заново.")
            elif status_code == 404:
                await _send_message(client, token, peer_id, "Не нашел запрос входа WHYFI. Открой приложение и начни вход заново.")
            else:
                await _send_message(client, token, peer_id, "Не смог подтвердить вход WHYFI. Попробуй еще раз через приложение.")
            return
        except Exception:
            await _send_message(client, token, peer_id, "Мост входа WHYFI пока недоступен. Попробуй войти через Telegram.")
            return
        await _send_message(
            client,
            token,
            peer_id,
            "Вход в WHYFI подтвержден. Вернись в приложение или браузер, кабинет откроется автоматически.",
        )
        return
    ticket_page = _ticket_page_from_text(text)
    if ticket_page is not None:
        await _send_ticket_list(client, token, backend_url, peer_id, vk_user_id, ticket_page)
        return

    if normalized in {"/start", "start", "начать", "старт"}:
        data = await _register_user(client, backend_url, token, vk_user_id)
        user = data["user"]
        status = "создан" if data["created"] else "обновлен"
        await _send_message(
            client,
            token,
            peer_id,
            (
                f"Профиль {status}: {user['display_name']}\n"
                f"Билетов: {user['tickets_count']}\n"
                f"Очков: {user['points']}\n\n"
                "Можно прислать фото/PDF билета сюда или открыть ЛК с камерой.\n"
                "Список сохраненных билетов: Билеты"
            ),
            keyboard=_account_keyboard(data["access_token"]),
        )
        return

    if (
        normalized.startswith("/link")
        or normalized.startswith("link")
        or normalized.startswith("привязать")
        or _is_link_code(text)
    ):
        parts = text.split(maxsplit=1)
        code = text if _is_link_code(text) else parts[1].strip() if len(parts) == 2 else ""
        if not code:
            await _send_message(client, token, peer_id, "Пришли команду так: /link 123456")
            return
        try:
            linked = await _link_user(client, backend_url, token, vk_user_id, code)
        except httpx.HTTPStatusError:
            await _send_message(client, token, peer_id, "Код не подошел или аккаунт уже привязан.")
            return
        await _send_message(
            client,
            token,
            peer_id,
            f"VK привязан к профилю {linked['user']['display_name']}.",
            keyboard=_account_keyboard(linked["access_token"]),
        )
        return

    if normalized in {"/profile", "профиль", "лк"}:
        await _send_profile(client, token, backend_url, peer_id, vk_user_id)
        return

    if normalized in {"/day", "день", "итоги"}:
        await _send_today(client, token, backend_url, peer_id, vk_user_id)
        return

    if normalized in {"/top", "топ"}:
        await _send_leaderboard(client, token, backend_url, peer_id)
        return

    for attachment in message.get("attachments") or []:
        handled = await _handle_attachment(client, token, backend_url, peer_id, vk_user_id, attachment)
        if handled:
            return

    if text:
        await _send_message(
            client,
            token,
            peer_id,
            "Для зачета пришли PDF или фото билета. 4 цифры можно быстро проверить на сайте.",
        )
        return

    await _send_message(client, token, peer_id, "Пришли PDF-билет или фото, и я засчитаю его.")


def _empty_stats(day: date) -> dict[str, Any]:
    return {
        "day": day.isoformat(),
        "tickets_count": 0,
        "verified_tickets_count": 0,
        "official_points": 0,
        "personal_points": 0,
        "official_happiness": 0,
        "personal_happiness": 0,
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
        f"Средняя счастливость: {stats.get('official_happiness', 0)} / 5",
        f"Личная шкала: {stats.get('personal_happiness', 0)} / 5",
        f"Официальные очки: {stats['official_points']}",
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
        f"{backend_url}/api/bot/vk/daily-digests",
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
    while True:
        try:
            group_id = await _resolve_group_id(client, token)
            server_state = await _get_long_poll_server(client, token, group_id)
            print(f"VK bot long poll started for group {group_id}", flush=True)
            break
        except (httpx.HTTPError, VkApiError) as error:
            print(f"VK long poll is not ready: {type(error).__name__}: {error}", flush=True)
            await asyncio.sleep(60)

    while True:
        try:
            response = await client.get(
                server_state["server"],
                params={
                    "act": "a_check",
                    "key": server_state["key"],
                    "ts": server_state["ts"],
                    "wait": 25,
                },
                timeout=35,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("failed"):
                failed = int(payload["failed"])
                if failed == 1:
                    server_state["ts"] = payload["ts"]
                else:
                    server_state = await _get_long_poll_server(client, token, group_id)
                continue

            server_state["ts"] = payload.get("ts", server_state["ts"])
            for update in payload.get("updates", []):
                if update.get("type") != "message_new":
                    continue
                message = (update.get("object") or {}).get("message")
                if not message:
                    continue
                try:
                    await _handle_message(client, token, backend_url, message)
                except (httpx.HTTPError, KeyError, ValueError, VkApiError) as error:
                    print(f"VK message handling failed: {type(error).__name__}: {error}", flush=True)
        except (httpx.HTTPError, VkApiError) as error:
            print(f"VK polling failed: {type(error).__name__}: {error}", flush=True)
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
                print(f"VK daily digest failed: {type(error).__name__}", flush=True)

        next_target = target if now < target else target + timedelta(days=1)
        seconds = max(60, min(300, int((next_target - now).total_seconds())))
        await asyncio.sleep(seconds)


async def run() -> None:
    _load_dotenv()
    _prefer_ipv4_dns()
    token = _required_env("VK_BOT_TOKEN")
    backend_url = _backend_url()
    timeout = httpx.Timeout(API_TIMEOUT, connect=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await asyncio.gather(
            _poll_updates(client, token, backend_url),
            _daily_summary_loop(client, token, backend_url),
        )


if __name__ == "__main__":
    asyncio.run(run())
