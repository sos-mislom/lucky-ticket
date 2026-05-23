from __future__ import annotations

from io import BytesIO
import shutil

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pypdf import PdfReader
import pytesseract


class TicketFileError(ValueError):
    pass


def extract_ticket_text(content: bytes, filename: str = "", content_type: str = "") -> str:
    lowered_name = filename.lower()
    lowered_type = content_type.lower()
    if lowered_name.endswith(".pdf") or lowered_type == "application/pdf":
        return extract_pdf_text(content)
    if lowered_type.startswith("image/") or lowered_name.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return extract_image_text(content)
    raise TicketFileError("Unsupported ticket file type")


def extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise TicketFileError("PDF text was not recognized")
    return text


def extract_image_text(content: bytes) -> str:
    image = Image.open(BytesIO(content)).convert("RGB")
    text_parts = _decode_qr_payloads(image)

    if shutil.which("tesseract") is None:
        text = "\n".join(dict.fromkeys(text_parts)).strip()
        if text:
            return text
        raise TicketFileError("OCR engine is not installed")

    for prepared, config in _ocr_variants(image):
        text = pytesseract.image_to_string(prepared, lang="rus+eng", config=config).strip()
        if text:
            text_parts.append(text)

    text = "\n".join(dict.fromkeys(text_parts)).strip()
    if not text:
        raise TicketFileError("Image text was not recognized")
    return text


def _decode_qr_payloads(image: Image.Image) -> list[str]:
    payloads: list[str] = []
    candidates = [
        image,
        ImageOps.autocontrast(image.convert("L")),
        _prepare_receipt_image(image),
    ]
    for candidate in list(candidates):
        width, height = candidate.size
        if max(width, height) < 600:
            scale = max(2, min(8, 600 // max(width, height)))
            candidates.append(candidate.resize((width * scale, height * scale), Image.Resampling.NEAREST))

    payloads.extend(_decode_qr_payloads_with_zxing(candidates))
    payloads.extend(_decode_qr_payloads_with_pyzbar(candidates))
    payloads.extend(_decode_qr_payloads_with_opencv(candidates))
    return list(dict.fromkeys(payloads))


def _decode_qr_payloads_with_zxing(candidates: list[Image.Image]) -> list[str]:
    try:
        import zxingcpp
    except ImportError:
        return []

    payloads: list[str] = []
    for candidate in candidates:
        for barcode in zxingcpp.read_barcodes(candidate):
            if str(barcode.format).lower().startswith("qr") and barcode.text.strip():
                payloads.append(barcode.text.strip())
    return payloads


def _decode_qr_payloads_with_pyzbar(candidates: list[Image.Image]) -> list[str]:
    try:
        from pyzbar.pyzbar import decode
    except Exception:
        return []

    payloads: list[str] = []
    for candidate in candidates:
        for decoded in decode(candidate):
            if decoded.type == "QRCODE":
                payloads.append(decoded.data.decode("utf-8", errors="ignore").strip())
    return [payload for payload in payloads if payload]


def _decode_qr_payloads_with_opencv(candidates: list[Image.Image]) -> list[str]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    detector = cv2.QRCodeDetector()
    payloads: list[str] = []
    for candidate in candidates:
        array = np.array(candidate)
        try:
            success, decoded_info, _, _ = detector.detectAndDecodeMulti(array)
        except cv2.error:
            success = False
            decoded_info = []
        if success:
            payloads.extend(payload.strip() for payload in decoded_info if payload and payload.strip())

        try:
            payload, _, _ = detector.detectAndDecode(array)
        except cv2.error:
            payload = ""
        if payload.strip():
            payloads.append(payload.strip())

    return payloads


def _ocr_variants(image: Image.Image) -> list[tuple[Image.Image, str]]:
    prepared = _prepare_receipt_image(image)
    threshold = prepared.point(lambda pixel: 255 if pixel > 170 else 0)
    variants = [
        (image, "--oem 3 --psm 6"),
        (prepared, "--oem 3 --psm 6"),
        (prepared, "--oem 3 --psm 4"),
        (prepared, "--oem 3 --psm 11"),
        (threshold, "--oem 3 --psm 6"),
    ]
    for angle in (8, -5):
        variants.append((prepared.rotate(angle, expand=True, fillcolor=255), "--oem 3 --psm 6"))
    return variants


def _prepare_receipt_image(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.autocontrast(image.convert("L"))
    grayscale = ImageEnhance.Contrast(grayscale).enhance(2.4)
    grayscale = grayscale.filter(ImageFilter.SHARPEN)

    width, height = grayscale.size
    scale = 3 if max(width, height) < 700 else 2 if max(width, height) < 1200 else 1
    if scale > 1:
        grayscale = grayscale.resize((width * scale, height * scale))
    return grayscale
