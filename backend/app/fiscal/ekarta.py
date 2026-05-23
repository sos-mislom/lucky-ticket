from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin
import argparse
import asyncio
import json

from app.fiscal.types import FiscalReceiptResult


@dataclass(frozen=True)
class EkartaReceiptRequest:
    series: str
    number: str
    is_qr: bool = False


class EkartaReceiptResult(FiscalReceiptResult):
    provider: str = "ekarta"


class EkartaFiscalClient:
    """Client for EKARTA's official fiscal receipt lookup page.

    The public Angular app calls:
    /fiscal/api/v1/cheque/{17_digit_series}{number}
    /fiscal/api/v1/cheque/qr/QR{qr_series}%20{qr_number}
    """

    def __init__(self, base_url: str = "http://f.ekarta-ek.ru/fiscal/", timeout: float = 20.0):
        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.timeout = timeout

    def build_lookup_url(self, request: EkartaReceiptRequest) -> str:
        if request.is_qr:
            payload = f"QR{normalize_qr_series(request.series)} {normalize_number(request.number)}"
            return urljoin(self.base_url, f"api/v1/cheque/qr/{quote(payload, safe='')}")
        payload = f"{normalize_series(request.series)}{normalize_number(request.number)}"
        return urljoin(self.base_url, f"api/v1/cheque/{quote(payload, safe='-')}")

    async def check(self, request: EkartaReceiptRequest) -> EkartaReceiptResult:
        import httpx

        url = self.build_lookup_url(request)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        return parse_ekarta_response(data, url)


def parse_ekarta_response(data: dict[str, Any], request_url: str) -> EkartaReceiptResult:
    error = data.get("error")
    if error:
        return EkartaReceiptResult(
            status="not_found" if error.get("resultCode") == 100 else "error",
            request_url=request_url,
            message=error.get("resultCodeText") or "Unknown EKARTA error",
            raw=data,
        )

    receipt_url = data.get("data", {}).get("url") if isinstance(data.get("data"), dict) else None
    return EkartaReceiptResult(
        status="verified" if receipt_url else "unknown",
        request_url=request_url,
        receipt_url=receipt_url,
        raw=data,
    )


def normalize_series(value: str) -> str:
    compact = value.strip().replace(" ", "-")
    digits = "".join(char for char in compact if char.isdigit())
    if len(digits) >= 17:
        return digits[:17]
    return compact


def normalize_number(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def normalize_qr_series(value: str) -> str:
    value = value.strip().upper()
    if value.startswith("QR"):
        value = value[2:]
    return normalize_number(value)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Probe EKARTA fiscal receipt lookup")
    parser.add_argument("series")
    parser.add_argument("number")
    parser.add_argument("--qr", action="store_true")
    args = parser.parse_args()

    client = EkartaFiscalClient()
    result = await client.check(EkartaReceiptRequest(args.series, args.number, args.qr))
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())
