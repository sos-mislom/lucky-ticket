import os
import tempfile
import json
from email.message import EmailMessage

import httpx

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace("\\", "/")

from app.core.settings import Settings
from app.db.models import Ticket, User
from app.db.session import SessionLocal, init_db
from app.jobs import ticket_mail
from app.jobs.ticket_mail import process_ticket_mail_message


NSPK_TICKET_EMAIL = """
Мир Транспорт
Здравствуйте!
Чтобы подтвердить адрес электронной почты, нажмите кнопку ниже.
https://bilet.nspk.ru/auth/confirm-fiscal-email/11111111-1111-4111-8111-111111111111

Транспорт
Регион
Муниципальные образования Свердловской области

Серия билета
260430-00000009-023

Номер билета
0930

Вид билета
Разовый билет на проезд пассажира

Стоимость
42 руб.

Дата проезда
30.04.2026 09:32:15

Дата оплаты
30.04.2026 09:36:38

Статус оплаты
Оплачено

Карта
XXXX XXXX XXXX 0000

Идентификатор банковского терминала
00000001

Серийный номер банковского терминала
00000009

ИНН перевозчика
0000000000

Наименование перевозчика
ТЕСТОВЫЙ ПЕРЕВОЗЧИК

Название маршрута/линии
ст. Чкаловская

Маршрут/Станция
101

Вид транспорта
Метро
"""


def test_ticket_mail_confirms_nspk_email_and_imports_ticket(monkeypatch) -> None:
    init_db()
    with SessionLocal() as db:
        user = User(display_name="Mail User", source="web")
        db.add(user)
        db.commit()
        db.refresh(user)
        ticket_mail_code = user.ticket_mail_code

    message = EmailMessage()
    message["From"] = "no-reply@bilet.nspk.ru"
    message["To"] = f"tickets+{ticket_mail_code}@example.test"
    message.set_content(NSPK_TICKET_EMAIL)

    confirmed_urls: list[str] = []

    def fake_confirm(url: str) -> bool:
        confirmed_urls.append(url)
        return True

    notifications: list[tuple[str, str | None]] = []

    async def fake_notify(user_id: str, address: str | None = None) -> None:
        notifications.append((user_id, address))

    monkeypatch.setattr(ticket_mail, "notify_ticket_mail_confirmed", fake_notify)

    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
    )
    result = process_ticket_mail_message(message.as_bytes(), settings, confirm_url=fake_confirm)

    assert result.confirmed == 1
    assert result.imported == 1
    assert result.mark_seen is True
    assert confirmed_urls == [
        "https://bilet.nspk.ru/auth/confirm-fiscal-email/11111111-1111-4111-8111-111111111111"
    ]
    assert notifications == [(user.id, f"tickets+{ticket_mail_code}@example.test")]

    with SessionLocal() as db:
        ticket = db.query(Ticket).one()
        assert ticket.user.ticket_mail_code == ticket_mail_code
        assert ticket.source_format == "nspk_sbp_email_v1"
        assert ticket.status == "verified"
        assert ticket.ticket_number == "0930"
        assert ticket.fiscal_series == "260430-00000009-023"
        assert ticket.route_number == "101"

    duplicate = process_ticket_mail_message(message.as_bytes(), settings, confirm_url=fake_confirm)
    assert duplicate.duplicate is True
    assert duplicate.imported == 0
    assert duplicate.mark_seen is True

    with SessionLocal() as db:
        assert db.query(Ticket).count() == 1


def test_nspk_email_confirmation_posts_api_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"responseStatus": "SUCCESS", "responseBody": None},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        confirmed = ticket_mail._confirm_nspk_email_url(
            client,
            "https://bilet.nspk.ru/auth/confirm-fiscal-email/11111111-1111-4111-8111-111111111111",
        )

    assert confirmed is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://bilet.nspk.ru/api/v1/user/confirm-email"
    assert json.loads(request.content) == {
        "token": "11111111-1111-4111-8111-111111111111",
    }


def test_nspk_email_confirmation_rejects_failed_api_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "responseStatus": "FAILED",
                "responseError": "TOKEN_NOT_FOUND",
                "responseBody": None,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        confirmed = ticket_mail._confirm_nspk_email_url(
            client,
            "https://bilet.nspk.ru/auth/confirm-fiscal-email/00000000-0000-0000-0000-000000000000",
        )

    assert confirmed is False
