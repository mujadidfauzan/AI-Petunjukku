from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def validate_embedding(embedding: Iterable[Any], expected_dimensions: int) -> list[float]:
    values = list(embedding)
    if len(values) != expected_dimensions:
        raise ValueError(
            f"Dimensi embedding tidak sesuai. Expected {expected_dimensions}, got {len(values)}."
        )

    try:
        return [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Embedding harus berupa list angka.") from exc


def preview_text(text: str, limit: int = 240) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."
