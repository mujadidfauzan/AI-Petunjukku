from __future__ import annotations

import re


def clean_text(text: str) -> str:
    text = (
        text.replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u00a0", " ")
        .replace("\xad", "")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def compact_text(value: object, max_length: int = 1200) -> str:
    text = clean_text(str(value or ""))
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}..."


def split_text_into_chunks(text: str, chunk_size: int = 1200, overlap: int = 160) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            chunks.extend(_split_large_text(paragraph, chunk_size, overlap))
            current = ""
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = _tail(current, overlap)
        current = f"{current}\n\n{paragraph}".strip() if current else paragraph

    if current:
        chunks.append(current)

    return chunks


def _split_large_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _tail(text: str, max_chars: int) -> str:
    if not text or max_chars <= 0:
        return ""
    return text[-max_chars:].strip()
