import asyncio
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db").replace("\\", "/")

from fastapi.testclient import TestClient

from app.api import routes
from app.core.settings import get_settings
from app.db.models import TicketHappiness
from app.db.session import SessionLocal, init_db
from app.fiscal.ekarta import EkartaReceiptResult
from app.fiscal import providers
from app.fiscal.types import FiscalCheckOutcome, FiscalReceiptResult
from app.jobs import ticket_checks
from app.main import app
from test_ticket_parser import SAMPLE_EKARTA_TEXT


def test_registers_telegram_user_idempotently() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/users/register",
            json={
                "display_name": "Telegram User",
                "source": "telegram",
                "external_id": "123",
                "username": "lucky_user",
            },
        )
        second = client.post(
            "/api/users/register",
            json={
                "display_name": "Telegram User Updated",
                "source": "telegram",
                "external_id": "123",
                "username": "lucky_user",
            },
        )

    assert first.status_code == 200
    assert first.json()["created"] is True
    assert first.json()["access_token"]
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["user"]["id"] == first.json()["user"]["id"]
    assert second.json()["user"]["display_name"] == "Telegram User Updated"


def test_logs_in_with_profile_access_token() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Login Player", "source": "web", "personal_data_consent": True},
        ).json()
        login = client.post(
            "/api/users/login",
            json={"access_token": registered["access_token"]},
        )
        missing = client.post(
            "/api/users/login",
            json={"access_token": "not-a-real-profile-token"},
        )

    assert login.status_code == 200
    assert login.json()["created"] is False
    assert login.json()["user"]["id"] == registered["user"]["id"]
    assert login.json()["access_token"] == registered["access_token"]
    assert missing.status_code == 404


def test_web_display_names_must_be_unique() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/users/register",
            json={"display_name": "Same Name", "source": "web", "personal_data_consent": True},
        )
        duplicate = client.post(
            "/api/users/register",
            json={"display_name": " same   name ", "source": "web", "personal_data_consent": True},
        )
        second = client.post(
            "/api/users/register",
            json={"display_name": "Other Name", "source": "web", "personal_data_consent": True},
        ).json()
        duplicate_update = client.patch(
            f"/api/users/{second['user']['id']}/profile",
            headers={"X-User-Token": second["access_token"]},
            json={"display_name": "Same Name"},
        )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate_update.status_code == 409


def test_submits_ticket_to_trip_day_and_verified_leaderboard() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Daily Player", "source": "telegram", "external_id": "777"},
        ).json()
        user = registered["user"]

        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
09.04.2026 16:26

Вид билета
Разовый билет (QR) в Екатеринбурге

Серия билета
QR000000000041

Номер билета
20000101000000099

Дата и время поездки
09.04.2026 16:26

Стоимость
42.0 руб.
"""
            },
        )
        profile = client.get(f"/api/users/{user['id']}/profile")
        leaderboard = client.get("/api/leaderboard")

    assert submit.status_code == 200
    assert submit.json()["ticket"]["status"] == "verified"
    assert submit.json()["ticket"]["day"] == "2026-04-09"
    assert profile.status_code == 200
    assert profile.json()["daily_stats"][0]["day"] == "2026-04-09"
    assert profile.json()["daily_stats"][0]["tickets_count"] == 1
    assert profile.json()["daily_stats"][0]["official_happiness"] >= 0
    assert profile.json()["daily_stats"][0]["personal_happiness"] >= 0
    assert profile.json()["hourly_stats"][0]["day"] == "2026-04-09"
    assert profile.json()["hourly_stats"][0]["hour"] == 16
    assert profile.json()["hourly_stats"][0]["tickets_count"] == 1
    assert profile.json()["hourly_stats"][0]["official_happiness"] >= 0
    assert leaderboard.status_code == 200
    rows = [row for row in leaderboard.json() if row["id"] == user["id"]]
    assert rows[0]["verified_tickets_count"] == 1
    assert rows[0]["points"] > 0


def test_pending_ekarta_ticket_is_checked_against_official_service(monkeypatch) -> None:
    calls = []

    class FakeEkartaFiscalClient:
        def __init__(self, base_url: str):
            self.base_url = base_url

        async def check(self, request):
            calls.append(request)
            return EkartaReceiptResult(
                status="verified",
                request_url="https://ekarta.example/check",
                receipt_url="https://consumer.example/ticket",
            )

    monkeypatch.setattr(providers, "EkartaFiscalClient", FakeEkartaFiscalClient)

    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Pending Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={"text": SAMPLE_EKARTA_TEXT},
        )
        ticket_id = submit.json()["ticket"]["id"]

    assert submit.status_code == 200
    assert submit.json()["ticket"]["status"] == "pending_check"

    checked_count = asyncio.run(ticket_checks.check_pending_tickets_once(limit=1))

    with TestClient(app) as client:
        profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": registered["access_token"]},
        )
        leaderboard = client.get("/api/leaderboard")

    assert checked_count == 1
    assert calls[0].series == "260428-00000001-052"
    assert calls[0].number == "0369"
    assert calls[0].is_qr is False
    ticket = [row for row in profile.json()["tickets"] if row["id"] == ticket_id][0]
    assert ticket["status"] == "verified"
    rows = [row for row in leaderboard.json() if row["id"] == user["id"]]
    assert rows[0]["verified_tickets_count"] == 1


def test_official_not_found_status_is_saved_for_pending_ticket(monkeypatch) -> None:
    calls = []

    class FakeEkartaFiscalClient:
        def __init__(self, base_url: str):
            self.base_url = base_url

        async def check(self, request):
            calls.append(request)
            return EkartaReceiptResult(
                status="not_found",
                request_url="https://ekarta.example/check",
                message="Билет не найден",
            )

    monkeypatch.setattr(providers, "EkartaFiscalClient", FakeEkartaFiscalClient)

    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Not Found Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
28.04.26 19:38 Бил. 0369
Сер. 26042,-00000003-952-.
Цена 42.00 руб.
"""
            },
        )
        ticket_id = submit.json()["ticket"]["id"]

    checked_count = asyncio.run(ticket_checks.check_pending_tickets_once(limit=1))

    with TestClient(app) as client:
        profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": registered["access_token"]},
        )

    ticket = [row for row in profile.json()["tickets"] if row["id"] == ticket_id][0]
    assert checked_count == 1
    assert calls[0].series == "260428-00000003-952"
    assert calls[0].number == "0369"
    assert ticket["status"] == "not_found"
    assert ticket["fiscal_series"] == "260428-00000003-952"


def test_pending_ticket_tries_close_ocr_series_candidates(monkeypatch) -> None:
    calls = []

    class FakeEkartaFiscalClient:
        def __init__(self, base_url: str):
            self.base_url = base_url

        async def check(self, request):
            calls.append(request)
            if request.series == "260428-11111111-052":
                return EkartaReceiptResult(
                    status="verified",
                    request_url="https://ekarta.example/check",
                    receipt_url="https://consumer.example/ticket",
                )
            return EkartaReceiptResult(
                status="not_found",
                request_url="https://ekarta.example/check",
                message="Билет не найден",
            )

    monkeypatch.setattr(providers, "EkartaFiscalClient", FakeEkartaFiscalClient)

    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Ocr Candidate Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
28.04.26 19:38 Бил. 0469
Сер. 26042, 11111111 052
Цена 42.00 руб.
ИНН 0000000000
28.04.26 19:38 Бил. 0469
Сер. 260428-22222222-052
Цена 42.00 руб.
"""
            },
        )
        ticket_id = submit.json()["ticket"]["id"]

    checked_count = asyncio.run(ticket_checks.check_pending_tickets_once(limit=1))

    with TestClient(app) as client:
        profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": registered["access_token"]},
        )

    ticket = [row for row in profile.json()["tickets"] if row["id"] == ticket_id][0]
    assert checked_count == 1
    assert calls[0].series == "260428-22222222-052"
    assert any(call.series == "260428-11111111-052" for call in calls)
    assert ticket["status"] == "verified"
    assert ticket["fiscal_series"] == "260428-11111111-052"


def test_pending_ticket_can_be_checked_by_custom_provider(monkeypatch) -> None:
    calls = []

    class FakeFiscalProvider:
        name = "fake"

        def candidates_for(self, ticket):
            return [ticket.fiscal_series] if ticket.fiscal_series else []

        def can_check(self, ticket, candidates):
            return ticket.source_format == "unknown" and bool(candidates)

        async def check(self, ticket, candidates):
            calls.append((ticket.ticket_number, candidates))
            return FiscalCheckOutcome(
                result=FiscalReceiptResult(
                    provider="fake",
                    status="verified",
                    request_url="https://fake.example/check",
                    receipt_url="https://fake.example/receipt",
                ),
                checked_series=candidates[0],
                checked_candidates=candidates,
            )

    monkeypatch.setattr(
        ticket_checks,
        "build_fiscal_check_providers",
        lambda settings: [FakeFiscalProvider()],
    )

    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Custom Provider Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
28.04.26 19:38 Бил. 1369
Сер. 260428-00000001-052
Цена 42.00 руб.
"""
            },
        )
        ticket_id = submit.json()["ticket"]["id"]

    checked_count = asyncio.run(ticket_checks.check_pending_tickets_once(limit=1))

    with TestClient(app) as client:
        profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": registered["access_token"]},
        )

    ticket = [row for row in profile.json()["tickets"] if row["id"] == ticket_id][0]
    assert checked_count == 1
    assert calls == [("1369", ["260428-00000001-052"])]
    assert ticket["status"] == "verified"


def test_lists_saved_tickets_with_pagination() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "History Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]

        for index, ticket_number in enumerate(["0369", "0370", "0371"]):
            ticket_text = (
                SAMPLE_EKARTA_TEXT
                .replace("0369", ticket_number)
                .replace("00000001-052", f"828326{80 + index}-052")
            )
            submit = client.post(
                f"/api/users/{user['id']}/tickets/submit",
                headers={"X-User-Token": registered["access_token"]},
                json={"text": ticket_text},
            )
            assert submit.status_code == 200

        first_page = client.get(
            f"/api/users/{user['id']}/tickets",
            headers={"X-User-Token": registered["access_token"]},
            params={"limit": 2},
        )
        second_page = client.get(
            f"/api/users/{user['id']}/tickets",
            headers={"X-User-Token": registered["access_token"]},
            params={"limit": 2, "offset": 2},
        )

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert first_page.json()["limit"] == 2
    assert first_page.json()["page"] == 1
    assert first_page.json()["page_count"] == 2
    assert first_page.json()["next_offset"] == 2
    assert first_page.json()["prev_offset"] is None
    assert len(first_page.json()["items"]) == 2
    assert second_page.status_code == 200
    assert second_page.json()["page"] == 2
    assert second_page.json()["next_offset"] is None
    assert second_page.json()["prev_offset"] == 0
    assert len(second_page.json()["items"]) == 1


def test_startup_refreshes_saved_happiness_translations() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Translation Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
09.04.2026 16:26

Серия билета
QR000000000045

Номер билета
20000101000000045

Дата и время поездки
09.04.2026 16:26
"""
            },
        )
        ticket_id = submit.json()["ticket"]["id"]

    with SessionLocal() as db:
        happiness = db.get(TicketHappiness, ticket_id)
        assert happiness is not None
        happiness.label = "ordinary spark"
        happiness.reasons = {"reasons": ["no strong pattern found"], "matched_rules": ["baseline"]}
        db.commit()

    init_db()

    with TestClient(app) as client:
        profile = client.get(f"/api/users/{user['id']}/profile")

    ticket = profile.json()["tickets"][0]
    assert ticket["official_label"] == "обычный билет"
    assert ticket["official_points"] == 1


def test_uploads_ticket_file_for_registered_user(monkeypatch) -> None:
    ticket_text = """
09.04.2026 16:26

Серия билета
QR000000000044

Номер билета
20000101000000044

Дата и время поездки
09.04.2026 16:26
"""

    def fake_extract_ticket_text(content: bytes, filename: str = "", content_type: str = "") -> str:
        assert content == b"fake image bytes"
        assert filename == "ticket.jpg"
        assert content_type == "image/jpeg"
        return ticket_text

    monkeypatch.setattr(routes, "extract_ticket_text", fake_extract_ticket_text)

    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Upload Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]

        upload = client.post(
            f"/api/users/{user['id']}/tickets/upload",
            headers={"X-User-Token": registered["access_token"]},
            files={"file": ("ticket.jpg", b"fake image bytes", "image/jpeg")},
        )
        image = client.get(
            upload.json()["ticket"]["image_url"],
            headers={"X-User-Token": registered["access_token"]},
        )

    assert user["personal_data_consent_given"] is True
    assert upload.status_code == 200
    assert upload.json()["ticket"]["ticket_number"] == "20000101000000044"
    assert upload.json()["ticket"]["day"] == "2026-04-09"
    assert upload.json()["ticket"]["image_url"]
    assert image.status_code == 200
    assert image.content == b"fake image bytes"


def test_updates_profile_and_hides_selected_public_blocks() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/users/register",
            json={"display_name": "Profile Player", "source": "web", "personal_data_consent": True},
        ).json()
        second = client.post(
            "/api/users/register",
            json={"display_name": "Other Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = first["user"]

        update = client.patch(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": first["access_token"]},
            json={"display_name": "Renamed Player", "username": "lucky_one", "bio": "Люблю билеты"},
        )
        duplicate_username = client.patch(
            f"/api/users/{second['user']['id']}/profile",
            headers={"X-User-Token": second["access_token"]},
            json={"username": "lucky_one"},
        )
        privacy = client.patch(
            f"/api/users/{user['id']}/privacy",
            headers={"X-User-Token": first["access_token"]},
            json={"show_about": False, "show_stats": False, "show_tickets": False},
        )
        public_profile = client.get(f"/api/users/{user['id']}/profile")
        owner_profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": first["access_token"]},
        )

    assert update.status_code == 200
    assert update.json()["display_name"] == "Renamed Player"
    assert update.json()["username"] == "lucky_one"
    assert update.json()["bio"] == "Люблю билеты"
    assert duplicate_username.status_code == 409
    assert privacy.status_code == 200
    assert public_profile.status_code == 200
    assert public_profile.json()["user"]["bio"] is None
    assert public_profile.json()["daily_stats"] == []
    assert public_profile.json()["tickets"] == []
    assert owner_profile.json()["user"]["bio"] == "Люблю билеты"


def test_uploading_avatar_changes_url_and_serves_latest_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(routes, "AVATAR_DIR", tmp_path)
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Avatar Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        headers = {"X-User-Token": registered["access_token"]}

        first = client.post(
            f"/api/users/{user['id']}/avatar",
            headers=headers,
            files={"file": ("avatar.png", b"first avatar", "image/png")},
        )
        second = client.post(
            f"/api/users/{user['id']}/avatar",
            headers=headers,
            files={"file": ("avatar.png", b"second avatar", "image/png")},
        )
        image = client.get(second.json()["avatar_url"], headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["avatar_url"].startswith(f"/api/users/{user['id']}/avatar?v=")
    assert second.json()["avatar_url"].startswith(f"/api/users/{user['id']}/avatar?v=")
    assert second.json()["avatar_url"] != first.json()["avatar_url"]
    assert image.status_code == 200
    assert image.content == b"second avatar"


def test_rejects_duplicate_ticket_for_same_or_other_user() -> None:
    ticket_text = """
09.04.2026 16:26

Серия билета
QR000000000040

Номер билета
20000101000000098

Дата и время поездки
09.04.2026 16:26
"""
    with TestClient(app) as client:
        first_registered = client.post(
            "/api/users/register",
            json={"display_name": "First Player", "source": "telegram", "external_id": "duplicate-1"},
        ).json()
        first_user = first_registered["user"]
        second_registered = client.post(
            "/api/users/register",
            json={"display_name": "Second Player", "source": "telegram", "external_id": "duplicate-2"},
        ).json()
        second_user = second_registered["user"]

        first_submit = client.post(
            f"/api/users/{first_user['id']}/tickets/submit",
            headers={"X-User-Token": first_registered["access_token"]},
            json={"text": ticket_text},
        )
        same_user_submit = client.post(
            f"/api/users/{first_user['id']}/tickets/submit",
            headers={"X-User-Token": first_registered["access_token"]},
            json={"text": ticket_text},
        )
        other_user_submit = client.post(
            f"/api/users/{second_user['id']}/tickets/submit",
            headers={"X-User-Token": second_registered["access_token"]},
            json={"text": ticket_text},
        )

    assert first_submit.status_code == 200
    assert same_user_submit.status_code == 409
    assert other_user_submit.status_code == 409


def test_rejects_ticket_submit_and_personal_rating_without_owner_token() -> None:
    ticket_text = """
11.04.2026 08:15

Серия билета
QR000000000043

Номер билета
20000101000000043

Дата и время поездки
11.04.2026 08:15
"""
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Protected Player", "source": "telegram", "external_id": "protected-1"},
        ).json()
        user = registered["user"]

        missing_token = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            json={"text": ticket_text},
        )
        submit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={"text": ticket_text},
        )
        ticket = submit.json()["ticket"]
        missing_rating_token = client.patch(
            f"/api/tickets/{ticket['id']}/personal-rating",
            json={"degree": 3},
        )

    assert missing_token.status_code == 403
    assert submit.status_code == 200
    assert missing_rating_token.status_code == 403


def test_owner_can_delete_unverified_ticket_but_not_verified_ticket() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Delete Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        unverified = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={"text": SAMPLE_EKARTA_TEXT.replace("0369", "0421").replace("00000001-052", "82832691-052")},
        )
        verified = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
09.04.2026 16:26

Серия билета
QR000000000091

Номер билета
20000101000000091

Дата и время поездки
09.04.2026 16:26
"""
            },
        )
        missing_token_delete = client.delete(f"/api/tickets/{unverified.json()['ticket']['id']}")
        delete_unverified = client.delete(
            f"/api/tickets/{unverified.json()['ticket']['id']}",
            headers={"X-User-Token": registered["access_token"]},
        )
        delete_verified = client.delete(
            f"/api/tickets/{verified.json()['ticket']['id']}",
            headers={"X-User-Token": registered["access_token"]},
        )
        resubmit = client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={"text": SAMPLE_EKARTA_TEXT.replace("0369", "0421").replace("00000001-052", "82832691-052")},
        )

    assert unverified.status_code == 200
    assert unverified.json()["ticket"]["status"] == "pending_check"
    assert verified.status_code == 200
    assert verified.json()["ticket"]["status"] == "verified"
    assert missing_token_delete.status_code == 403
    assert delete_unverified.status_code == 204
    assert delete_verified.status_code == 409
    assert resubmit.status_code == 200


def test_private_profile_is_hidden_from_public_profile_and_top() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={
                "display_name": "Private Player",
                "source": "telegram",
                "external_id": "778",
                "is_profile_public": False,
            },
        ).json()
        user = registered["user"]
        profile = client.get(f"/api/users/{user['id']}/profile")
        owner_profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": registered["access_token"]},
        )
        leaderboard = client.get("/api/leaderboard")

    assert profile.status_code == 403
    assert owner_profile.status_code == 200
    assert all(row["id"] != user["id"] for row in leaderboard.json())


def test_links_telegram_account_to_existing_web_user() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Web Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]

        code_response = client.post(
            f"/api/users/{user['id']}/telegram-link-code",
            headers={"X-User-Token": registered["access_token"]},
        )
        code = code_response.json()["code"]
        linked = client.post(
            "/api/bot/telegram/link",
            json={
                "code": code,
                "telegram_id": "998877",
                "username": "web_player",
                "display_name": "Telegram Name",
            },
        )
        telegram_register = client.post(
            "/api/users/register",
            json={
                "display_name": "Telegram Name",
                "source": "telegram",
                "external_id": "998877",
                "username": "web_player",
            },
        )

    assert code_response.status_code == 200
    assert linked.status_code == 200
    assert linked.json()["created"] is False
    assert linked.json()["user"]["id"] == user["id"]
    assert linked.json()["user"]["telegram_linked"] is True
    assert linked.json()["user"]["telegram_username"] == "web_player"
    assert telegram_register.json()["user"]["id"] == user["id"]


def test_links_vk_account_to_existing_web_user_and_reuses_registration() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Web VK Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]

        code_response = client.post(
            f"/api/users/{user['id']}/vk-link-code",
            headers={"X-User-Token": registered["access_token"]},
        )
        code = code_response.json()["code"]
        linked = client.post(
            "/api/bot/vk/link",
            json={
                "code": code,
                "vk_id": "665544",
                "username": "vk_player",
                "display_name": "VK Name",
            },
        )
        vk_register = client.post(
            "/api/users/register",
            json={
                "display_name": "VK Name",
                "source": "vk",
                "external_id": "665544",
                "username": "vk_player",
            },
        )

    assert code_response.status_code == 200
    assert linked.status_code == 200
    assert linked.json()["created"] is False
    assert linked.json()["user"]["id"] == user["id"]
    assert linked.json()["user"]["vk_linked"] is True
    assert linked.json()["user"]["vk_username"] == "vk_player"
    assert vk_register.json()["user"]["id"] == user["id"]


def test_linking_messenger_keeps_existing_profile_avatar() -> None:
    with TestClient(app) as client:
        telegram_registered = client.post(
            "/api/users/register",
            json={
                "display_name": "Avatar Telegram Player",
                "source": "web",
                "avatar_url": "https://example.test/original-telegram.jpg",
                "personal_data_consent": True,
            },
        ).json()
        telegram_user = telegram_registered["user"]
        telegram_code = client.post(
            f"/api/users/{telegram_user['id']}/telegram-link-code",
            headers={"X-User-Token": telegram_registered["access_token"]},
        ).json()["code"]
        telegram_linked = client.post(
            "/api/bot/telegram/link",
            json={
                "code": telegram_code,
                "telegram_id": "avatar-telegram-1",
                "username": "avatar_tg",
                "display_name": "Telegram Avatar",
                "avatar_url": "https://example.test/telegram.jpg",
            },
        )

        vk_registered = client.post(
            "/api/users/register",
            json={
                "display_name": "Avatar VK Player",
                "source": "web",
                "avatar_url": "https://example.test/original-vk.jpg",
                "personal_data_consent": True,
            },
        ).json()
        vk_user = vk_registered["user"]
        vk_code = client.post(
            f"/api/users/{vk_user['id']}/vk-link-code",
            headers={"X-User-Token": vk_registered["access_token"]},
        ).json()["code"]
        vk_linked = client.post(
            "/api/bot/vk/link",
            json={
                "code": vk_code,
                "vk_id": "avatar-vk-1",
                "username": "avatar_vk",
                "display_name": "VK Avatar",
                "avatar_url": "https://example.test/vk.jpg",
            },
        )

    assert telegram_linked.status_code == 200
    assert telegram_linked.json()["user"]["avatar_url"] == "https://example.test/original-telegram.jpg"
    assert vk_linked.status_code == 200
    assert vk_linked.json()["user"]["avatar_url"] == "https://example.test/original-vk.jpg"


def test_linking_provider_account_transfers_existing_bot_tickets() -> None:
    ticket_text = """
09.04.2026 16:26

Серия билета
QR000000000041

Номер билета
20000101000000041

Дата и время поездки
09.04.2026 16:26
"""
    with TestClient(app) as client:
        vk_registered = client.post(
            "/api/users/register",
            json={
                "display_name": "Temporary VK Player",
                "source": "vk",
                "external_id": "merge-vk-1",
                "username": "merge_vk_player",
            },
        ).json()
        vk_user = vk_registered["user"]
        submit = client.post(
            f"/api/users/{vk_user['id']}/tickets/submit",
            headers={"X-User-Token": vk_registered["access_token"]},
            json={"text": ticket_text},
        )
        web_registered = client.post(
            "/api/users/register",
            json={"display_name": "Main Web Player", "source": "web", "personal_data_consent": True},
        ).json()
        web_user = web_registered["user"]
        code = client.post(
            f"/api/users/{web_user['id']}/vk-link-code",
            headers={"X-User-Token": web_registered["access_token"]},
        ).json()["code"]

        linked = client.post(
            "/api/bot/vk/link",
            json={
                "code": code,
                "vk_id": "merge-vk-1",
                "username": "merge_vk_player",
                "display_name": "Temporary VK Player",
            },
        )
        profile = client.get(
            f"/api/users/{web_user['id']}/profile",
            headers={"X-User-Token": web_registered["access_token"]},
        )
        vk_register_again = client.post(
            "/api/users/register",
            json={
                "display_name": "Temporary VK Player",
                "source": "vk",
                "external_id": "merge-vk-1",
                "username": "merge_vk_player",
            },
        )

    assert submit.status_code == 200
    assert linked.status_code == 200
    assert linked.json()["user"]["id"] == web_user["id"]
    assert profile.json()["tickets"][0]["ticket_number"] == "20000101000000041"
    assert vk_register_again.json()["user"]["id"] == web_user["id"]


def test_relinking_vk_from_existing_web_user_detaches_old_profile() -> None:
    with TestClient(app) as client:
        old_registered = client.post(
            "/api/users/register",
            json={"display_name": "Old Web Player", "source": "web", "personal_data_consent": True},
        ).json()
        old_user = old_registered["user"]
        old_code = client.post(
            f"/api/users/{old_user['id']}/vk-link-code",
            headers={"X-User-Token": old_registered["access_token"]},
        ).json()["code"]
        first_link = client.post(
            "/api/bot/vk/link",
            json={
                "code": old_code,
                "vk_id": "relink-vk-1",
                "username": "relink_vk_player",
                "display_name": "VK Player",
            },
        )
        new_registered = client.post(
            "/api/users/register",
            json={"display_name": "New Web Player", "source": "web", "personal_data_consent": True},
        ).json()
        new_user = new_registered["user"]
        new_code = client.post(
            f"/api/users/{new_user['id']}/vk-link-code",
            headers={"X-User-Token": new_registered["access_token"]},
        ).json()["code"]

        second_link = client.post(
            "/api/bot/vk/link",
            json={
                "code": new_code,
                "vk_id": "relink-vk-1",
                "username": "relink_vk_player",
                "display_name": "VK Player",
            },
        )
        old_login = client.post("/api/users/login", json={"access_token": old_registered["access_token"]})
        vk_register_again = client.post(
            "/api/users/register",
            json={
                "display_name": "VK Player",
                "source": "vk",
                "external_id": "relink-vk-1",
                "username": "relink_vk_player",
            },
        )

    assert first_link.status_code == 200
    assert first_link.json()["user"]["id"] == old_user["id"]
    assert second_link.status_code == 200
    assert second_link.json()["user"]["id"] == new_user["id"]
    assert second_link.json()["user"]["vk_linked"] is True
    assert old_login.json()["user"]["vk_linked"] is False
    assert vk_register_again.json()["user"]["id"] == new_user["id"]


def test_public_profile_can_hide_messenger_links_completely() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={"display_name": "Messenger Player", "source": "web", "personal_data_consent": True},
        ).json()
        user = registered["user"]
        telegram_code = client.post(
            f"/api/users/{user['id']}/telegram-link-code",
            headers={"X-User-Token": registered["access_token"]},
        ).json()["code"]
        vk_code = client.post(
            f"/api/users/{user['id']}/vk-link-code",
            headers={"X-User-Token": registered["access_token"]},
        ).json()["code"]
        client.post(
            "/api/bot/telegram/link",
            json={
                "code": telegram_code,
                "telegram_id": "hide-tag-tg",
                "username": "hidden_tg",
                "display_name": "Telegram Name",
            },
        )
        client.post(
            "/api/bot/vk/link",
            json={
                "code": vk_code,
                "vk_id": "hide-tag-vk",
                "username": "hidden_vk",
                "display_name": "VK Name",
            },
        )
        client.patch(
            f"/api/users/{user['id']}/privacy",
            headers={"X-User-Token": registered["access_token"]},
            json={"show_telegram": False, "show_vk": False},
        )
        public_profile = client.get(f"/api/users/{user['id']}/profile")
        owner_profile = client.get(
            f"/api/users/{user['id']}/profile",
            headers={"X-User-Token": registered["access_token"]},
        )

    public_user = public_profile.json()["user"]
    assert public_user["telegram_linked"] is False
    assert public_user["vk_linked"] is False
    assert public_user["telegram_username"] is None
    assert public_user["vk_username"] is None
    assert public_user["privacy_settings"] == {}

    owner_user = owner_profile.json()["user"]
    assert owner_user["telegram_linked"] is True
    assert owner_user["vk_linked"] is True
    assert owner_user["telegram_username"] == "hidden_tg"
    assert owner_user["vk_username"] == "hidden_vk"
    assert owner_user["privacy_settings"]["show_telegram"] is False
    assert owner_user["privacy_settings"]["show_vk"] is False


def test_telegram_daily_digest_includes_day_tickets_even_for_private_profile() -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/api/users/register",
            json={
                "display_name": "Digest Player",
                "source": "telegram",
                "external_id": "779",
                "is_profile_public": False,
            },
        ).json()
        user = registered["user"]
        client.post(
            f"/api/users/{user['id']}/tickets/submit",
            headers={"X-User-Token": registered["access_token"]},
            json={
                "text": """
10.04.2026 08:15

Серия билета
QR000000000042

Номер билета
20000101000000042

Дата и время поездки
10.04.2026 08:15
"""
            },
        )
        digest = client.get("/api/bot/telegram/daily-digests", params={"day": "2026-04-10"})

    assert digest.status_code == 200
    rows = [row for row in digest.json() if row["user"]["id"] == user["id"]]
    assert rows[0]["chat_id"] == 779
    assert rows[0]["stats"]["tickets_count"] == 1
    assert rows[0]["tickets"][0]["day"] == "2026-04-10"


def test_telegram_daily_digest_respects_internal_token() -> None:
    os.environ["INTERNAL_API_TOKEN"] = "secret-test-token"
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            forbidden = client.get("/api/bot/telegram/daily-digests", params={"day": "2026-04-10"})
            allowed = client.get(
                "/api/bot/telegram/daily-digests",
                headers={"X-Internal-Token": "secret-test-token"},
                params={"day": "2026-04-10"},
            )
    finally:
        os.environ.pop("INTERNAL_API_TOKEN", None)
        get_settings.cache_clear()

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
