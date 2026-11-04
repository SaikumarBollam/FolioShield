"""Tests for PDF first-page rendering used by the Vision AI scan check."""

import io
import unittest

from core.extractor import DocumentExtractor, ExtractionError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _make_pdf(pages: int = 1) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for index in range(pages):
        pdf.drawString(72, 720, f"Test page {index + 1}")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class TestPdfFirstPageToImage(unittest.TestCase):
    def test_renders_first_page_to_png(self):
        png = DocumentExtractor.pdf_first_page_to_image(_make_pdf(pages=2))
        self.assertTrue(png.startswith(PNG_MAGIC), "Rendered output is not PNG bytes")
        self.assertGreater(len(png), 1000)

    def test_invalid_pdf_raises_extraction_error(self):
        with self.assertRaises(ExtractionError):
            DocumentExtractor.pdf_first_page_to_image(b"this is not a pdf")

    def test_empty_input_raises_extraction_error(self):
        with self.assertRaises(ExtractionError):
            DocumentExtractor.pdf_first_page_to_image(b"")


if __name__ == "__main__":
    unittest.main()
