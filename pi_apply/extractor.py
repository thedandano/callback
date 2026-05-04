"""Resume text extraction — PDF, DOCX, TXT. Pure I/O, no scoring logic."""

from __future__ import annotations

from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def extract(path: str | Path) -> str:
    """Extract plain text from a resume file.

    Supports .pdf, .docx, and .txt.
    Raises FileNotFoundError, ValueError (bad format / too large), or RuntimeError.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"extractor: file not found: {p}")

    size = p.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"extractor: file too large ({size} bytes, max {MAX_FILE_BYTES})")

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(p)
    if suffix in (".docx", ".doc"):
        return _extract_docx(p)
    if suffix == ".txt":
        return p.read_text(encoding="utf-8").strip()

    raise ValueError(f"extractor: unsupported format {suffix!r} — expected .pdf, .docx, or .txt")


def _extract_pdf(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise RuntimeError(f"extractor: PDF yielded no text: {path}")
    return text


def _extract_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs).strip()
    if not text:
        raise RuntimeError(f"extractor: DOCX yielded no text: {path}")
    return text
