from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.settings import Settings
from app.db.models import Ticket
from app.fiscal.ekarta import EkartaFiscalClient, EkartaReceiptRequest, EkartaReceiptResult
from app.fiscal.types import FiscalCheckOutcome, FiscalCheckProvider
from app.tickets.parser import normalize_series


OCR_SERIES_REPLACEMENTS = {
    "0": ("8",),
    "3": ("8",),
    "5": ("8", "6"),
    "6": ("8",),
    "8": ("6", "5"),
    "9": ("0",),
}


def build_fiscal_check_providers(settings: Settings) -> list[FiscalCheckProvider]:
    factories: dict[str, Callable[[Settings], FiscalCheckProvider]] = {
        "ekarta": lambda current_settings: EkartaFiscalProvider(
            EkartaFiscalClient(base_url=current_settings.ekarta_fiscal_base_url),
        ),
    }
    provider_names = [
        name.strip().casefold()
        for name in settings.fiscal_check_providers.split(",")
        if name.strip()
    ]
    return [factories[name](settings) for name in provider_names if name in factories]


def select_fiscal_check_provider(
    providers: list[FiscalCheckProvider],
    ticket: Ticket,
) -> tuple[FiscalCheckProvider, list[str]] | None:
    for provider in providers:
        candidates = provider.candidates_for(ticket)
        if provider.can_check(ticket, candidates):
            return provider, candidates
    return None


class EkartaFiscalProvider:
    name = "ekarta"

    def __init__(self, client: EkartaFiscalClient):
        self.client = client

    def candidates_for(self, ticket: Ticket) -> list[str]:
        candidates: list[str] = []

        def add_candidate(value: Any) -> None:
            if not isinstance(value, str):
                return
            normalized = normalize_series(value, ticket.purchased_at)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        add_candidate(ticket.fiscal_series)
        payload = dict(ticket.parsed_payload) if isinstance(ticket.parsed_payload, dict) else {}
        payload_candidates = payload.get("fiscal_series_candidates")
        if isinstance(payload_candidates, list):
            for candidate in payload_candidates:
                add_candidate(candidate)

        for candidate in list(candidates):
            for variant in _ocr_series_variants(candidate):
                add_candidate(variant)

        return candidates[:20]

    def can_check(self, ticket: Ticket, candidates: list[str]) -> bool:
        if not candidates or not ticket.ticket_number:
            return False
        if ticket.source_format.startswith("ekarta_"):
            return True
        if ticket.source_format == "fns_fiscal_qr_v1":
            return False
        series_digits = "".join(char for char in candidates[0] if char.isdigit())
        number_digits = "".join(char for char in ticket.ticket_number if char.isdigit())
        return len(series_digits) >= 17 and 3 <= len(number_digits) <= 8

    async def check(self, ticket: Ticket, candidates: list[str]) -> FiscalCheckOutcome:
        first_result: EkartaReceiptResult | None = None
        first_series = candidates[0] if candidates else None
        for series in candidates:
            result = await self.client.check(
                EkartaReceiptRequest(
                    series=series,
                    number=ticket.ticket_number,
                    is_qr=_is_ekarta_qr_ticket(ticket),
                )
            )
            if first_result is None:
                first_result = result
                first_series = series
            if result.status == "verified":
                return FiscalCheckOutcome(
                    result=result,
                    checked_series=series,
                    checked_candidates=candidates,
                )
        if first_result is None:
            raise RuntimeError("No EKARTA fiscal series candidates")
        return FiscalCheckOutcome(
            result=first_result,
            checked_series=first_series,
            checked_candidates=candidates,
        )


def _is_ekarta_qr_ticket(ticket: Ticket) -> bool:
    return ticket.source_format.startswith("ekarta_ek_qr") or (
        ticket.fiscal_series or ""
    ).strip().upper().startswith("QR")


def _ocr_series_variants(series: str) -> list[str]:
    digits = "".join(char for char in series if char.isdigit())
    if len(digits) != 17:
        return []

    variants: list[str] = []
    for index in range(6, 17):
        for replacement in OCR_SERIES_REPLACEMENTS.get(digits[index], ()):
            if replacement == digits[index]:
                continue
            mutated = f"{digits[:index]}{replacement}{digits[index + 1:]}"
            formatted = f"{mutated[:6]}-{mutated[6:14]}-{mutated[14:17]}"
            if formatted != series and formatted not in variants:
                variants.append(formatted)
    return variants[:16]
