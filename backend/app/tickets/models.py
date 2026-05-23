from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TicketParseResult(BaseModel):
    source_format: str = "unknown"
    operator: str | None = None
    inn: str | None = None
    purchased_at: datetime | None = None
    ticket_number: str | None = None
    fiscal_series: str | None = None
    fiscal_series_candidates: list[str] = Field(default_factory=list)
    fiscal_url_hint: str | None = None
    price_rub: Decimal | None = None
    route_number: str | None = None
    vehicle_type: str | None = None
    vehicle_id: str | None = None
    terminal_id: str | None = None
    payment_method: str | None = None
    card_mask: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    raw_text: str
