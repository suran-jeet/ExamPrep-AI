from __future__ import annotations

from dataclasses import dataclass
import re
from typing import BinaryIO

from PyPDF2 import PdfReader


MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024


class PdfProcessingError(Exception):
    """Raised when a PDF cannot be validated or extracted."""


@dataclass(frozen=True)
class PdfExtractionResult:
    text: str
    page_count: int
    word_count: int


def validate_pdf_file(uploaded_file: BinaryIO, filename: str | None, size: int | None) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise PdfProcessingError("Upload a PDF file.")

    if size is not None and size > MAX_PDF_SIZE_BYTES:
        raise PdfProcessingError("PDF size must be 10 MB or less.")

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    header = uploaded_file.read(5)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    if header != b"%PDF-":
        raise PdfProcessingError("The selected file does not look like a valid PDF.")


def extract_text_from_pdf(uploaded_file: BinaryIO, filename: str | None = None, size: int | None = None) -> PdfExtractionResult:
    validate_pdf_file(uploaded_file, filename, size)

    try:
        reader = PdfReader(uploaded_file)
    except Exception as exc:
        raise PdfProcessingError(f"Could not read the PDF: {exc}") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise PdfProcessingError("Encrypted PDFs are not supported unless they open without a password.") from exc

    page_text: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise PdfProcessingError(f"Text extraction failed on page {index}: {exc}") from exc

        clean_text = text.strip()
        if clean_text:
            page_text.append(f"[Page {index}]\n{clean_text}")

    extracted_text = "\n\n".join(page_text).strip()
    if not extracted_text:
        raise PdfProcessingError("No selectable text was found. Scanned PDFs need OCR support.")

    word_count = len(re.findall(r"\b[\w'-]+\b", extracted_text))
    return PdfExtractionResult(text=extracted_text, page_count=len(reader.pages), word_count=word_count)
