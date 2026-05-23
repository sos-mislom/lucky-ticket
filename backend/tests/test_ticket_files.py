from io import BytesIO

from PIL import Image
import zxingcpp

from app.tickets.files import extract_image_text


def test_extract_image_text_reads_qr_payload_without_tesseract() -> None:
    payload = "https://f.ekarta-ek.ru/fiscal/?t=20260428T1938&s=0000000000&fn=111&fp=222&i=333&n=1&sum=4200"
    barcode = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode)
    qr_image = Image.fromarray(zxingcpp.write_barcode_to_image(barcode)).resize((410, 410))
    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")

    assert payload in extract_image_text(buffer.getvalue())
