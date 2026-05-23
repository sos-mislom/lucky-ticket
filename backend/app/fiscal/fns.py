from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
import re


FISCAL_QR_RE = re.compile(
    r"(?:^|[?\s])"
    r"(?=.*(?:^|[&\s])t=(?P<time>\d{8}T\d{4}(?:\d{2})?))"
    r"(?=.*(?:^|[&\s])s=(?P<amount>\d+(?:[.,]\d{1,2})?))"
    r"(?=.*(?:^|[&\s])fn=(?P<fn>\d{10,20}))"
    r"(?=.*(?:^|[&\s])i=(?P<fiscal_document>\d{1,12}))"
    r"(?=.*(?:^|[&\s])fp=(?P<fiscal_sign>\d{5,12}))"
    r"(?P<payload>[^\s]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FiscalQrData:
    fiscal_time: datetime
    amount: Decimal
    fiscal_drive_number: str
    fiscal_document_number: str
    fiscal_sign: str
    operation_type: str | None
    raw_payload: str


def parse_fiscal_qr(text: str) -> FiscalQrData | None:
    normalized = text.replace("\r", "\n").replace("\n", " ")
    candidates = _fiscal_candidates(normalized)
    for candidate in candidates:
        data = _parse_candidate(candidate)
        if data is not None:
            return data
    return None


def _fiscal_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"https?://[^\s]+", text, flags=re.IGNORECASE):
        candidates.append(match.group(0))
    for match in re.finditer(r"t=\d{8}T\d{4}(?:\d{2})?(?:[&\s][a-z]+=[^\s&]+){3,}", text, flags=re.IGNORECASE):
        candidates.append(match.group(0))
    fiscal_match = FISCAL_QR_RE.search(text)
    if fiscal_match:
        candidates.append(fiscal_match.group("payload"))
    return candidates


def _parse_candidate(candidate: str) -> FiscalQrData | None:
    parsed_url = urlparse(candidate)
    query = parsed_url.query if parsed_url.query else candidate
    query = query.replace(" ", "&")
    params = {key.lower(): values[-1] for key, values in parse_qs(query).items() if values}

    required = ["t", "s", "fn", "i", "fp"]
    if any(key not in params for key in required):
        return None

    try:
        return FiscalQrData(
            fiscal_time=_parse_fiscal_time(params["t"]),
            amount=Decimal(params["s"].replace(",", ".")),
            fiscal_drive_number=re.sub(r"\D", "", params["fn"]),
            fiscal_document_number=re.sub(r"\D", "", params["i"]),
            fiscal_sign=re.sub(r"\D", "", params["fp"]),
            operation_type=params.get("n"),
            raw_payload=candidate,
        )
    except (ValueError, ArithmeticError):
        return None


def _parse_fiscal_time(value: str) -> datetime:
    compact = value.strip()
    if len(compact) == 13:
        compact = f"{compact}00"
    return datetime.strptime(compact, "%Y%m%dT%H%M%S")
