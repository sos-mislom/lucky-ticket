from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from app.db.models import Ticket


class FiscalReceiptResult(BaseModel):
    provider: str
    status: str
    request_url: str
    receipt_url: str | None = None
    message: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class FiscalCheckOutcome:
    result: FiscalReceiptResult
    checked_series: str | None = None
    checked_candidates: list[str] | None = None


class FiscalCheckProvider(Protocol):
    name: str

    def candidates_for(self, ticket: Ticket) -> list[str]:
        """Return provider-specific lookup candidates for this ticket."""

    def can_check(self, ticket: Ticket, candidates: list[str]) -> bool:
        """Return whether this provider can check the ticket."""

    async def check(self, ticket: Ticket, candidates: list[str]) -> FiscalCheckOutcome:
        """Check the ticket through the provider API."""
