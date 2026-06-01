from __future__ import annotations

from pathlib import Path

from app.utils.text_cleaner import clean_text


def read_document_text(path: Path) -> tuple[str, dict[str, object]]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Dokumen tidak ditemukan: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf_text(path)

    text = path.read_text(encoding="utf-8", errors="ignore")
    return clean_text(text), {"fileName": path.name}


def _read_pdf_text(path: Path) -> tuple[str, dict[str, object]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF diperlukan untuk membaca PDF.") from exc

    parts: list[str] = []
    page_count = 0
    with fitz.open(path) as document:
        page_count = document.page_count
        for page in document:
            parts.append(page.get_text())

    return clean_text("\n\n".join(parts)), {"fileName": path.name, "pageCount": page_count}
