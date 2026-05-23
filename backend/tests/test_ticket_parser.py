from decimal import Decimal

from app.tickets.parser import parse_ticket_text


SAMPLE_EKARTA_TEXT = """
ЕМУП ГОРТРАНС
ИНН 0000000000

28.04.26 19:38 Бил. 0369
Сер. 260428 00000001-052
Получить фискальный чек
http://www.ekarta-ek.ru/fc
Цена 42.00 руб.
Маршрут 17              Т/Н 358
Трамвай
Терминал N:
MIR
A000000000000
000000******0000
ОДОБРЕНО КОД:00
"""


def test_parse_ekarta_ticket_text() -> None:
    parsed = parse_ticket_text(SAMPLE_EKARTA_TEXT)

    assert parsed.source_format == "ekarta_ek_gortrans_thermal_v1"
    assert parsed.operator == "ЕМУП ГОРТРАНС"
    assert parsed.inn == "0000000000"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.year == 2026
    assert parsed.ticket_number == "0369"
    assert parsed.fiscal_series == "260428-00000001-052"
    assert parsed.price_rub == Decimal("42.00")
    assert parsed.route_number == "17"
    assert parsed.vehicle_type == "tram"
    assert parsed.vehicle_id == "358"
    assert parsed.payment_method == "bank_card"
    assert parsed.card_mask == "000000******0000"


def test_parse_ekarta_qr_pdf_text() -> None:
    parsed = parse_ticket_text(
        """
09.04.2026 16:26

Вид билета
Разовый билет (QR) в Екатеринбурге

Серия билета
QR000000000040

Номер билета
20000101000000098

ИНН перевозчика
0000000000

Наименование перевозчика
ТЕСТОВЫЙ ПЕРЕВОЗЧИК

Вид транспорта
Автобус

Маршрут/Станция
86

Номер ТС
578

Дата и время поездки
09.04.2026 16:26

Стоимость
42.0 руб.
"""
    )

    assert parsed.source_format == "ekarta_ek_qr_pdf_v1"
    assert parsed.operator == "ТЕСТОВЫЙ ПЕРЕВОЗЧИК"
    assert parsed.inn == "0000000000"
    assert parsed.ticket_number == "20000101000000098"
    assert parsed.fiscal_series == "QR000000000040"
    assert parsed.route_number == "86"
    assert parsed.vehicle_type == "bus"
    assert parsed.vehicle_id == "578"
    assert parsed.price_rub == Decimal("42.0")


def test_parse_ekarta_qr_chat_text() -> None:
    parsed = parse_ticket_text(
        """
09.04.2026 16:26

Вид билета
Разовый билет (QR) в Екатеринбурге

Серия билета
QR000000000040

Номер билета
20000101000000098

Дата и время поездки
09.04.2026 16:26

Стоимость
42.0 руб.
"""
    )

    assert parsed.source_format == "ekarta_ek_qr_pdf_v1"
    assert parsed.ticket_number == "20000101000000098"
    assert parsed.fiscal_series == "QR000000000040"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.date().isoformat() == "2026-04-09"
    assert parsed.price_rub == Decimal("42.0")


def test_parse_nspk_sbp_email_ticket_text() -> None:
    parsed = parse_ticket_text(
        """
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
    )

    assert parsed.source_format == "nspk_sbp_email_v1"
    assert parsed.operator == "ТЕСТОВЫЙ ПЕРЕВОЗЧИК"
    assert parsed.inn == "0000000000"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.isoformat() == "2026-04-30T09:32:15"
    assert parsed.ticket_number == "0930"
    assert parsed.fiscal_series == "260430-00000009-023"
    assert parsed.price_rub == Decimal("42")
    assert parsed.route_number == "101"
    assert parsed.vehicle_type == "metro"
    assert parsed.terminal_id == "00000001"
    assert parsed.payment_method == "sbp"
    assert parsed.card_mask == "XXXX XXXX XXXX 0000"


def test_parse_ekarta_qrpay_pdf_text() -> None:
    parsed = parse_ticket_text(
        """
2025-02-21T12:18:55

Вид билета
Разовый билет QRPay (Акция)

Серия билета
QR000000000637

Номер билета
20000101000000637

ИНН перевозчика
0000000000

Наименование перевозчика
ТЕСТОВЫЙ ПЕРЕВОЗЧИК

Вид транспорта
Автобус

Маршрут/Станция
65

Номер ТС
322

Дата и время поездки
2025-02-21T12:18:55

Стоимость
29.0 руб.
"""
    )

    assert parsed.source_format == "ekarta_ek_qr_pdf_v1"
    assert parsed.operator == "ТЕСТОВЫЙ ПЕРЕВОЗЧИК"
    assert parsed.inn == "0000000000"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.year == 2025
    assert parsed.purchased_at.month == 2
    assert parsed.purchased_at.day == 21
    assert parsed.ticket_number == "20000101000000637"
    assert parsed.fiscal_series == "QR000000000637"


def test_parse_universal_fiscal_qr_payload() -> None:
    parsed = parse_ticket_text(
        "https://consumer.1-ofd.ru/ticket?t=20260428T1746&s=42.00&fn=0000000000000000&i=00001&fp=0000000000&n=1"
    )

    assert parsed.source_format == "fns_fiscal_qr_v1"
    assert parsed.ticket_number == "00001"
    assert parsed.fiscal_series == "0000000000000000"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.isoformat() == "2026-04-28T17:46:00"
    assert parsed.price_rub is not None
    assert str(parsed.price_rub) == "42.00"
    assert parsed.confidence == 0.8


def test_parse_noisy_thermal_photo_ocr_text() -> None:
    parsed = parse_ticket_text(
        """
ИНН 0000000000
28.04.26 19:38 Бил. 0369
р Ban 260428 - 00000002052
Цена 42.00 руб.
Mapupyt 17 Т/Н 358
"""
    )

    assert parsed.ticket_number == "0369"
    assert parsed.fiscal_series == "260428-00000002-052"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.isoformat() == "2026-04-28T19:38:00"
    assert parsed.price_rub == Decimal("42.00")
    assert parsed.vehicle_id == "358"


def test_repairs_thermal_series_date_prefix_from_trip_date() -> None:
    parsed = parse_ticket_text(
        """
28.04.26 19:38 Бил. 0369
Сер. 26042,-00000003-952-.
Цена 42.00 руб.
"""
    )

    assert parsed.ticket_number == "0369"
    assert parsed.purchased_at is not None
    assert parsed.purchased_at.isoformat() == "2026-04-28T19:38:00"
    assert parsed.fiscal_series == "260428-00000003-952"


def test_prefers_full_date_prefix_series_candidate_from_noisy_ocr() -> None:
    parsed = parse_ticket_text(
        """
28.04.26 19:38 Бил. 0369
Сер. 26042, 00000003 952
Цена 42.00 руб.
ИНН 0000000000
28.04.26 19:38 Бил. 0369
Сер. 260428-00000002-052
Цена 42.00 руб.
"""
    )

    assert parsed.fiscal_series == "260428-00000002-052"
    assert parsed.fiscal_series_candidates[:2] == [
        "260428-00000002-052",
        "260428-00000003-952",
    ]


def test_prefers_cyrillic_ticket_hint_when_noisy_ocr_disagrees() -> None:
    parsed = parse_ticket_text(
        """
523.426 19:38 “Bun. 0368
сер “280426. 32832618=052
-23,64206`19:38*Вил. 0369 —
Цена 42.00 руб.
"""
    )

    assert parsed.ticket_number == "0369"
    assert parsed.price_rub == Decimal("42.00")
