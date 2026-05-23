from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import Any

from sqlalchemy import select

from app.core.settings import get_settings
from app.db.models import Ticket
from app.db.session import SessionLocal
from app.fiscal.providers import build_fiscal_check_providers, select_fiscal_check_provider
from app.fiscal.types import FiscalReceiptResult
from app.notifications import notify_ticket_check_status


LOGGER = logging.getLogger(__name__)
CHECKABLE_STATUSES = ("pending_check", "parsed", "unknown", "not_found", "check_error")


async def check_pending_tickets_once(limit: int = 200) -> int:
    settings = get_settings()
    providers = build_fiscal_check_providers(settings)
    checked_count = 0

    with SessionLocal() as db:
        tickets = db.scalars(
            select(Ticket)
            .where(Ticket.status.in_(CHECKABLE_STATUSES))
            .order_by(Ticket.created_at.desc())
            .limit(limit)
        ).all()

        for ticket in tickets:
            provider_selection = select_fiscal_check_provider(providers, ticket)
            if provider_selection is None:
                continue
            provider, series_candidates = provider_selection
            try:
                outcome = await provider.check(
                    ticket,
                    series_candidates,
                )
                result = outcome.result
                checked_series = outcome.checked_series
                if checked_series is not None and ticket.fiscal_series != checked_series:
                    ticket.fiscal_series = checked_series
                ticket.parsed_payload = _payload_with_check_result(
                    _payload_with_checked_candidates(
                        ticket.parsed_payload,
                        outcome.checked_candidates or series_candidates,
                        provider.name,
                    ),
                    result,
                )
                if isinstance(ticket.parsed_payload, dict):
                    if checked_series is not None:
                        ticket.parsed_payload["fiscal_series"] = checked_series
                    ticket.parsed_payload["fiscal_series_candidates"] = outcome.checked_candidates or series_candidates
                if result.status == "verified":
                    ticket.status = "verified"
                elif result.status == "not_found":
                    ticket.status = "not_found"
                elif result.status in {"unknown", "error"}:
                    ticket.status = "check_error"
                checked_count += 1
                ticket_id = ticket.id
                result_status = result.status
                result_message = result.message
                db.commit()
                await _notify_ticket_check_status(ticket_id, result_status, result_message)
            except Exception as error:
                LOGGER.exception("Ticket fiscal check failed for ticket %s", ticket.id)
                ticket.parsed_payload = _payload_with_check_error(ticket.parsed_payload, error)
                ticket.status = "check_error"
                checked_count += 1
                ticket_id = ticket.id
                db.commit()
                await _notify_ticket_check_status(ticket_id, "error", str(error))

    return checked_count


async def pending_ticket_check_loop(interval_seconds: int = 900) -> None:
    if interval_seconds <= 0:
        return

    startup_delay = min(10, max(1, interval_seconds))
    await asyncio.sleep(startup_delay)
    while True:
        try:
            checked_count = await check_pending_tickets_once()
            if checked_count:
                LOGGER.info("Checked %s pending tickets", checked_count)
        except Exception:
            LOGGER.exception("Pending ticket check loop failed")
        await asyncio.sleep(interval_seconds)


def _payload_with_check_result(
    payload: dict[str, Any] | None,
    result: FiscalReceiptResult,
) -> dict[str, Any]:
    data = dict(payload) if isinstance(payload, dict) else {}
    attempts = int(data.get("official_check_attempts") or 0) + 1
    check = result.model_dump(mode="json")
    data["official_check_attempts"] = attempts
    data["last_official_check_at"] = datetime.now(UTC).isoformat()
    data["last_official_check"] = check
    checks = data.get("official_checks")
    if not isinstance(checks, list):
        checks = []
    data["official_checks"] = [*checks[-9:], check]
    data.pop("last_official_check_error", None)
    return data


def _payload_with_checked_candidates(
    payload: dict[str, Any] | None,
    candidates: list[str],
    provider_name: str,
) -> dict[str, Any]:
    data = dict(payload) if isinstance(payload, dict) else {}
    data["last_checked_series_candidates"] = candidates
    data["last_official_check_provider"] = provider_name
    return data


def _payload_with_check_error(payload: dict[str, Any] | None, error: Exception) -> dict[str, Any]:
    data = dict(payload) if isinstance(payload, dict) else {}
    data["official_check_attempts"] = int(data.get("official_check_attempts") or 0) + 1
    data["last_official_check_at"] = datetime.now(UTC).isoformat()
    data["last_official_check_error"] = str(error)
    return data


async def _notify_ticket_check_status(ticket_id: str, status: str, detail: str | None) -> None:
    try:
        await notify_ticket_check_status(ticket_id, status, detail)
    except Exception:
        LOGGER.exception("Ticket status notification failed for ticket %s", ticket_id)
