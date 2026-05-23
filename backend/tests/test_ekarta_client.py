from app.fiscal.ekarta import (
    EkartaFiscalClient,
    EkartaReceiptRequest,
    parse_ekarta_response,
)


def test_builds_public_ekarta_lookup_url() -> None:
    client = EkartaFiscalClient()

    url = client.build_lookup_url(EkartaReceiptRequest("260428 00000001-052", "0369"))

    assert url == "http://f.ekarta-ek.ru/fiscal/api/v1/cheque/260428000000010520369"


def test_builds_public_ekarta_qr_lookup_url() -> None:
    client = EkartaFiscalClient()

    url = client.build_lookup_url(
        EkartaReceiptRequest("QR000000000040", "20000101000000098", is_qr=True)
    )

    assert (
        url
        == "http://f.ekarta-ek.ru/fiscal/api/v1/cheque/qr/QR000000000040%2020000101000000098"
    )


def test_parses_not_found_response() -> None:
    result = parse_ekarta_response(
        {"error": {"resultCode": 100, "resultCodeText": "Билет не найден"}, "format": "URL"},
        "http://example.test",
    )

    assert result.status == "not_found"
    assert result.message == "Билет не найден"


def test_parses_verified_response() -> None:
    result = parse_ekarta_response(
        {
            "error": None,
            "format": "URL",
            "data": {"url": "https://consumer.1-ofd.ru/ticket?t=20260428T1746"},
        },
        "http://example.test",
    )

    assert result.status == "verified"
    assert result.receipt_url == "https://consumer.1-ofd.ru/ticket?t=20260428T1746"
