from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TextChunk:
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    token_count: int
