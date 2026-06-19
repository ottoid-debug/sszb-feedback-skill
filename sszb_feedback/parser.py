"""PDF text extraction using pdfplumber."""
from pathlib import Path
import pdfplumber


def parse_pdf(pdf_path: Path, max_chars: int = 0) -> str:
    """Extract text from a PDF file.

    Args:
        pdf_path: Path to the PDF file.
        max_chars: Maximum characters to return (0 = no limit).

    Returns:
        Extracted text as a single string.
    """
    if not pdf_path.exists():
        return f"[File not found: {pdf_path}]"

    try:
        with pdfplumber.open(pdf_path) as pdf:
            texts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)

            full_text = "\n\n".join(texts)

            if max_chars and len(full_text) > max_chars:
                full_text = full_text[:max_chars] + "\n\n[... truncated ...]"

            return full_text
    except Exception as e:
        return f"[PDF parse error: {e}]"
