from datetime import datetime
from decimal import Decimal
import re

from app.fiscal.fns import parse_fiscal_qr
from app.tickets.models import TicketParseResult


def _mojibake(value: str) -> str:
    return value.encode("utf-8").decode("cp1251", errors="ignore")


RU_LABELS = {
    "ticket_type": "Вид билета",
    "series": "Серия билета",
    "number": "Номер билета",
    "inn": "ИНН перевозчика",
    "operator": "Наименование перевозчика",
    "vehicle_type": "Вид транспорта",
    "route": "Маршрут/Станция",
    "vehicle_id": "Номер ТС",
    "purchased_at": "Дата и время поездки",
    "price": "Стоимость",
}
LABEL_ALIASES = {
    key: [label, _mojibake(label)]
    for key, label in RU_LABELS.items()
}
ALL_LABELS = [label for labels in LABEL_ALIASES.values() for label in labels]

DATE_TICKET_RE = re.compile(
    r"(?P<day>\d{1,2})[.,\s]+(?P<month>\d{2})[.,\s]*(?P<year>\d{2,4})"
    r"\s+(?P<hour>\d{1,2})[:.](?P<minute>\d{2})"
    r".{0,32}?(?:Бил\.?|Вил\.?|Bil\.?|Bun\.?|Buin\.?)"
    r"\s*[-—:_]?\s*(?P<ticket>[0-9OО]{3,8})",
    re.IGNORECASE | re.DOTALL,
)
DATE_TIME_RE = re.compile(
    r"(?P<day>\d{1,2})[.,\s]+(?P<month>\d{2})[.,\s]*(?P<year>\d{2,4})"
    r"\s+(?P<hour>\d{1,2})[:.](?P<minute>\d{2})",
    re.IGNORECASE,
)
TICKET_HINT_RE = re.compile(
    r"(?:Бил\.?|Вил\.?|Bil\.?|Bun\.?|Buin\.?)"
    r"\s*[-—:_]?\s*(?P<ticket>[0-9OО]{3,8})",
    re.IGNORECASE,
)
INN_RE = re.compile(r"ИНН\s*(?P<inn>\d{10,12})", re.IGNORECASE)
SERIES_RE = re.compile(
    r"(?:Сер\.?|Cep\.?|Ban|вар|ИВ)\s*[:._-]?\s*(?P<series>[0-9OО\s.,=\-]{12,32})",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"(?:Цена|Чена)\s*(?P<price>\d+[.,]\d{2})", re.IGNORECASE)
ROUTE_RE = re.compile(r"Маршрут\s*(?P<route>[0-9A-ZА-ЯЁ-]+)", re.IGNORECASE)
VEHICLE_ID_RE = re.compile(r"\b[ТT]/?[НH]\s*(?P<vehicle>\d[0-9A-ZА-ЯЁ-]*)", re.IGNORECASE)
TERMINAL_RE = re.compile(r"Терминал\s*(?:N|№|N:|№:)?\s*(?P<terminal>\d+)", re.IGNORECASE)
CARD_MASK_RE = re.compile(r"(?P<mask>\d{4,6}\*{4,10}\d{4})")
NSPK_CARD_MASK_RE = re.compile(r"(?P<mask>(?:X{4}\s+){3}\d{4})", re.IGNORECASE)
URL_HINT_RE = re.compile(r"(?P<url>https?://[^\s]+)", re.IGNORECASE)

def parse_ticket_text(raw_text: str) -> TicketParseResult:
    normalized = normalize_ocr_text(raw_text)
    if is_ekarta_qr_pdf(normalized):
        return parse_ekarta_qr_pdf(raw_text, normalized)
    fiscal_qr = parse_fiscal_qr(raw_text)
    if fiscal_qr is not None:
        return TicketParseResult(
            source_format="fns_fiscal_qr_v1",
            operator=None,
            inn=None,
            purchased_at=fiscal_qr.fiscal_time,
            ticket_number=fiscal_qr.fiscal_document_number,
            fiscal_series=fiscal_qr.fiscal_drive_number,
            fiscal_series_candidates=[fiscal_qr.fiscal_drive_number],
            fiscal_url_hint=fiscal_qr.raw_payload,
            price_rub=fiscal_qr.amount,
            route_number=None,
            vehicle_type=None,
            vehicle_id=None,
            terminal_id=None,
            payment_method=None,
            card_mask=None,
            confidence=0.8,
            raw_text=raw_text,
        )
    if is_nspk_sbp_email(normalized):
        return parse_nspk_sbp_email(raw_text, normalized)

    operator = parse_operator(normalized)
    inn = _first_group(INN_RE, normalized, "inn")
    date_match = DATE_TICKET_RE.search(normalized)
    matched_datetime = parse_datetime_match_safe(date_match)
    purchased_at = matched_datetime or parse_first_datetime(normalized)
    ticket_number = (
        normalize_digits(date_match.group("ticket"))
        if date_match and matched_datetime is not None
        else parse_ticket_number_hint(normalized)
    )
    fiscal_series_candidates = parse_series_candidates(normalized, purchased_at)
    fiscal_series = fiscal_series_candidates[0] if fiscal_series_candidates else None
    fiscal_url_hint = _first_group(URL_HINT_RE, normalized, "url")
    price_rub = parse_decimal(_first_group(PRICE_RE, normalized, "price"))
    route_number = _first_group(ROUTE_RE, normalized, "route")
    vehicle_type = parse_vehicle_type(normalized)
    vehicle_id = _first_group(VEHICLE_ID_RE, normalized, "vehicle")
    terminal_id = _first_group(TERMINAL_RE, normalized, "terminal")
    card_mask = _first_group(CARD_MASK_RE, normalized, "mask")
    payment_method = (
        "bank_card"
        if card_mask or "КАРТА БАНКА" in normalized.upper()
        else None
    )

    fields_found = sum(
        value is not None
        for value in [
            operator,
            inn,
            purchased_at,
            ticket_number,
            fiscal_series,
            price_rub,
            route_number,
            vehicle_type,
            vehicle_id,
            card_mask,
        ]
    )
    confidence = min(1.0, fields_found / 10)

    return TicketParseResult(
        source_format=detect_source_format(normalized),
        operator=operator,
        inn=inn,
        purchased_at=purchased_at,
        ticket_number=ticket_number,
        fiscal_series=fiscal_series,
        fiscal_series_candidates=fiscal_series_candidates,
        fiscal_url_hint=fiscal_url_hint,
        price_rub=price_rub,
        route_number=route_number,
        vehicle_type=vehicle_type,
        vehicle_id=vehicle_id,
        terminal_id=terminal_id,
        payment_method=payment_method,
        card_mask=card_mask,
        confidence=confidence,
        raw_text=raw_text,
    )


def normalize_ocr_text(text: str) -> str:
    text = repair_mojibake_text(text)
    lines = []
    for line in text.replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def repair_mojibake_text(text: str) -> str:
    current = text
    for _ in range(2):
        if not _looks_mojibake(current):
            return current
        try:
            candidate = current.encode("cp1251").decode("utf-8")
        except UnicodeError:
            return current
        if candidate == current:
            return current
        current = candidate
    return current


def _looks_mojibake(text: str) -> bool:
    markers = [_mojibake(char) for char in "аеиклнопрст"]
    marker_hits = sum(text.count(marker) for marker in markers)
    return marker_hits >= 3


def normalize_digits(value: str | None) -> str | None:
    if value is None:
        return None
    for bad_zero in ["О", "O", "o"]:
        value = value.replace(bad_zero, "0")
    return value


def normalize_series(value: str | None, purchased_at: datetime | None = None) -> str | None:
    if value is None:
        return None
    value = normalize_digits(value) or ""
    compact = re.sub(r"\s+", "-", value.strip())
    compact = re.sub(r"-{2,}", "-", compact)
    if re.fullmatch(r"\d{6}-\d{8}-\d{3}", compact):
        return compact
    digits = re.sub(r"\D", "", compact)
    digits = repair_series_digits_with_date(digits, purchased_at)
    if len(digits) >= 17:
        return f"{digits[:6]}-{digits[6:14]}-{digits[14:17]}"
    return compact


def parse_series_candidates(text: str, purchased_at: datetime | None) -> list[str]:
    candidates: dict[str, tuple[int, int, int]] = {}
    date_prefix = purchased_at.strftime("%y%m%d") if purchased_at else ""
    for match in SERIES_RE.finditer(text):
        raw_value = match.group("series")
        candidate = normalize_series(raw_value, purchased_at)
        if candidate is None:
            continue
        digits = re.sub(r"\D", "", normalize_digits(raw_value) or "")
        canonical_digits = re.sub(r"\D", "", candidate)
        if len(canonical_digits) < 17:
            continue
        rank = (
            int(bool(date_prefix and digits.startswith(date_prefix))),
            int(len(digits) >= 17),
            -match.start(),
        )
        if candidate not in candidates or rank > candidates[candidate]:
            candidates[candidate] = rank
    return [candidate for candidate, _ in sorted(candidates.items(), key=lambda item: item[1], reverse=True)]


def repair_series_digits_with_date(digits: str, purchased_at: datetime | None) -> str:
    if purchased_at is None or len(digits) != 16:
        return digits
    date_prefix = purchased_at.strftime("%y%m%d")
    if digits.startswith(date_prefix):
        return f"{date_prefix}8{digits[len(date_prefix):]}"
    for missing_index in range(len(date_prefix)):
        shortened_prefix = date_prefix[:missing_index] + date_prefix[missing_index + 1 :]
        if digits.startswith(shortened_prefix):
            return f"{date_prefix}{digits[len(shortened_prefix):]}"
    return digits


def parse_ticket_number_hint(text: str) -> str | None:
    matches = list(TICKET_HINT_RE.finditer(text))
    if not matches:
        return None
    match = sorted(matches, key=_ticket_hint_rank, reverse=True)[0]
    value = normalize_digits(match.group("ticket")) or ""
    digits = re.sub(r"\D", "", value)
    return digits or None


def _ticket_hint_rank(match: re.Match[str]) -> tuple[int, int, int]:
    label = match.group(0).lower()
    value = normalize_digits(match.group("ticket")) or ""
    digits = re.sub(r"\D", "", value)
    cyrillic_label = int("бил" in label or "вил" in label)
    leading_zero = int(digits.startswith("0"))
    return cyrillic_label, leading_zero, int(len(digits) >= 4), match.start()


def parse_operator(text: str) -> str | None:
    for line in text.splitlines()[:4]:
        upper_line = line.upper()
        if "ГОРТРАНС" in upper_line:
            return upper_line
    return None


def parse_vehicle_type(text: str) -> str | None:
    lowered = text.lower()
    if "трамвай" in lowered:
        return "tram"
    if "автобус" in lowered:
        return "bus"
    if "троллейбус" in lowered:
        return "trolleybus"
    if "метро" in lowered:
        return "metro"
    return None


def parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value.replace(",", "."))


def parse_datetime_match(match: re.Match[str]) -> datetime:
    year = int(match.group("year"))
    if year < 100:
        year += 2000
    second = int(match.groupdict().get("second") or 0)
    return datetime(
        year=year,
        month=int(match.group("month")),
        day=int(match.group("day")),
        hour=int(match.group("hour")),
        minute=int(match.group("minute")),
        second=second,
    )


def parse_datetime_match_safe(match: re.Match[str] | None) -> datetime | None:
    if match is None:
        return None
    try:
        return parse_datetime_match(match)
    except ValueError:
        return None


def detect_source_format(text: str) -> str:
    if is_nspk_sbp_email(text):
        return "nspk_sbp_email_v1"
    if is_ekarta_qr_pdf(text):
        return "ekarta_ek_qr_pdf_v1"
    upper_text = text.upper()
    if "ЕКАРТА" in upper_text or "EKARTA" in upper_text or "ГОРТРАНС" in upper_text:
        return "ekarta_ek_gortrans_thermal_v1"
    return "unknown"


def _first_group(pattern: re.Pattern[str], text: str, group: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(group).strip()


def is_ekarta_qr_pdf(text: str) -> bool:
    return "QR" in text.upper() and _has_label(text, "series") and _has_label(text, "number")


def is_nspk_sbp_email(text: str) -> bool:
    return (
        "Серия билета" in text
        and "Номер билета" in text
        and "Дата проезда" in text
        and "Статус оплаты" in text
        and "Карта" in text
    )


def parse_nspk_sbp_email(raw_text: str, normalized: str) -> TicketParseResult:
    fiscal_series = value_after_label(normalized, "Серия билета")
    ticket_number = value_after_label(normalized, "Номер билета")
    purchased_at = parse_label_datetime(value_after_label(normalized, "Дата проезда"))
    price_rub = parse_decimal_from_text(value_after_label(normalized, "Стоимость"))
    vehicle_type_text = value_after_label(normalized, "Вид транспорта")
    card_mask = value_after_label(normalized, "Карта") or _first_group(
        NSPK_CARD_MASK_RE, normalized, "mask"
    )
    if card_mask:
        card_mask = re.sub(r"\s+", " ", card_mask.strip())
    terminal_id = value_after_label(normalized, "Идентификатор банковского терминала")

    fields_found = sum(
        value is not None
        for value in [
            value_after_label(normalized, "Наименование перевозчика"),
            value_after_label(normalized, "ИНН перевозчика"),
            purchased_at,
            ticket_number,
            fiscal_series,
            price_rub,
            value_after_label(normalized, "Маршрут/Станция"),
            vehicle_type_text,
            terminal_id,
            card_mask,
        ]
    )

    return TicketParseResult(
        source_format="nspk_sbp_email_v1",
        operator=value_after_label(normalized, "Наименование перевозчика"),
        inn=value_after_label(normalized, "ИНН перевозчика"),
        purchased_at=purchased_at,
        ticket_number=ticket_number,
        fiscal_series=fiscal_series,
        fiscal_series_candidates=[fiscal_series] if fiscal_series else [],
        fiscal_url_hint="https://bilet.nspk.ru/private",
        price_rub=price_rub,
        route_number=value_after_label(normalized, "Маршрут/Станция"),
        vehicle_type=parse_vehicle_type(vehicle_type_text or ""),
        vehicle_id=None,
        terminal_id=terminal_id,
        payment_method="sbp",
        card_mask=card_mask,
        confidence=min(1.0, fields_found / 10),
        raw_text=raw_text,
    )


def value_after_label(text: str, label: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if line == label:
            return lines[index + 1].strip()
    return None


def parse_ekarta_qr_pdf(raw_text: str, normalized: str) -> TicketParseResult:
    values = parse_label_values(normalized)
    fiscal_series = label_value(values, "series")
    ticket_number = label_value(values, "number")
    purchased_at = parse_label_datetime(label_value(values, "purchased_at")) or parse_first_datetime(
        normalized
    )
    price_rub = parse_decimal_from_text(label_value(values, "price"))
    vehicle_type_text = label_value(values, "vehicle_type")

    fields_found = sum(
        value is not None
        for value in [
            label_value(values, "operator"),
            label_value(values, "inn"),
            purchased_at,
            ticket_number,
            fiscal_series,
            price_rub,
            label_value(values, "route"),
            vehicle_type_text,
            label_value(values, "vehicle_id"),
        ]
    )

    return TicketParseResult(
        source_format="ekarta_ek_qr_pdf_v1",
        operator=label_value(values, "operator"),
        inn=label_value(values, "inn"),
        purchased_at=purchased_at,
        ticket_number=ticket_number,
        fiscal_series=fiscal_series,
        fiscal_series_candidates=[fiscal_series] if fiscal_series else [],
        fiscal_url_hint="http://www.ekarta-ek.ru/fc",
        price_rub=price_rub,
        route_number=label_value(values, "route"),
        vehicle_type=parse_vehicle_type(vehicle_type_text or ""),
        vehicle_id=label_value(values, "vehicle_id"),
        terminal_id=None,
        payment_method=None,
        card_mask=None,
        confidence=min(1.0, fields_found / 9),
        raw_text=raw_text,
    )


def parse_label_values(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, str] = {}

    for index, line in enumerate(lines):
        if line not in ALL_LABELS:
            continue
        value_parts: list[str] = []
        for next_line in lines[index + 1 :]:
            if next_line in ALL_LABELS:
                break
            value_parts.append(next_line)
        if value_parts:
            result[line] = " ".join(value_parts).strip()

    return result


def label_value(values: dict[str, str], key: str) -> str | None:
    for label in LABEL_ALIASES[key]:
        value = values.get(label)
        if value:
            return value
    return None


def _has_label(text: str, key: str) -> bool:
    return any(label in text for label in LABEL_ALIASES[key])


def parse_label_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    iso_match = re.search(
        r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
        r"(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?",
        value,
    )
    if iso_match:
        return parse_datetime_match(iso_match)
    match = re.search(
        r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})\s+"
        r"(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?",
        value,
    )
    if not match:
        return None
    return parse_datetime_match(match)


def parse_first_datetime(text: str) -> datetime | None:
    iso_match = re.search(
        r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
        r"(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?",
        text,
    )
    if iso_match:
        return parse_datetime_match(iso_match)
    for match in DATE_TIME_RE.finditer(text):
        parsed = parse_datetime_match_safe(match)
        if parsed is not None:
            return parsed
    return None


def parse_decimal_from_text(value: str | None) -> Decimal | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    amount = match.group(0)
    return Decimal(amount.replace(",", "."))
