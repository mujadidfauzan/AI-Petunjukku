from __future__ import annotations

import bisect
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAMPIRAN_TO_DOMAIN = {
    "I": "PAUD",
    "II": "Reguler",
    "III": "SMK",
    "IV": "Paket",
    "V": "SLB",
}


@dataclass
class SubjectBlock:
    start: int
    content_start: int
    end: int
    section: str
    subject: str
    lampiran: str | None
    domain: str | None


@dataclass
class LampiranEvent:
    offset: int
    lampiran: str


def extract_cp_records_from_pdf_bytes(file_name: str, content: bytes) -> list[dict[str, Any]]:
    full_text, page_starts = _read_pdf_text(content)
    if not full_text.strip():
        return []

    lampiran_events = _detect_lampiran_events(full_text)
    subjects = _detect_subject_blocks(full_text, lampiran_events)
    if not subjects:
        return []

    for index, subject in enumerate(subjects):
        subject.end = subjects[index + 1].start if index + 1 < len(subjects) else len(full_text)

    records: list[dict[str, Any]] = []
    for subject in subjects:
        if _is_container_heading(subject.subject):
            continue
        records.extend(_extract_subject_records(file_name, full_text, page_starts, subject))

    return records


def cp_record_to_chunk_content(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Mata pelajaran: {record.get('subject')}",
            f"Fase: {record.get('phase')}",
            f"Jenjang: {record.get('jenjang')}",
            f"Domain: {record.get('domain')}",
            f"Lampiran: {record.get('lampiran')}",
            f"Deskripsi fase: {record.get('phase_class_description')}",
            "Capaian Pembelajaran:",
            record.get("cp_overall_text") or "",
        ]
    ).strip()


def _read_pdf_text(content: bytes) -> tuple[str, list[int]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF diperlukan untuk ekstraksi CP PDF terstruktur.") from exc

    parts: list[str] = []
    page_starts: list[int] = []
    offset = 0

    with fitz.open(stream=content, filetype="pdf") as document:
        for page in document:
            page_starts.append(offset)
            text = _clean_page_text(page.get_text())
            parts.append(text)
            offset += len(text) + 2

    return "\n\n".join(parts), page_starts


def _clean_page_text(text: str) -> str:
    text = (
        text.replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u00a0", " ")
        .replace("\xad", "")
    )
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"[ \t]+", " ", line).strip())
    return "\n".join(lines)


def _line_offsets(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        lines.append((offset, line.rstrip("\r\n")))
        offset += len(line)
    return lines


def _detect_lampiran_events(text: str) -> list[LampiranEvent]:
    events: list[LampiranEvent] = []
    pattern = re.compile(r"(?im)^\s*LAMPIRAN\s+(III|II|IV|V|I)\s*$")
    for match in pattern.finditer(text):
        events.append(LampiranEvent(offset=match.start(), lampiran=match.group(1).upper()))
    return events


def _detect_subject_blocks(text: str, lampiran_events: list[LampiranEvent]) -> list[SubjectBlock]:
    lines = _line_offsets(text)
    blocks: list[SubjectBlock] = []
    section_re = re.compile(r"^(?:[IVXLCDM]+(?:\.\d+)?\.?|\d+(?:\.\d+)*\.?)$", re.IGNORECASE)

    for index, (offset, _) in enumerate(lines):
        if not _is_cp_heading_start(lines, index):
            continue

        previous = _previous_non_empty_line(lines, index)
        if previous.upper() in {"A.", "B.", "C.", "D."}:
            continue
        if not section_re.match(previous):
            continue

        subject = _collect_subject_name(lines, index)
        if not _looks_like_subject(subject):
            continue

        lampiran = _lampiran_for_offset(lampiran_events, offset)
        blocks.append(
            SubjectBlock(
                start=offset,
                content_start=_content_start_after_subject(lines, index),
                end=len(text),
                section=previous,
                subject=subject,
                lampiran=lampiran,
                domain=LAMPIRAN_TO_DOMAIN.get(lampiran or ""),
            )
        )

    return blocks


def _is_cp_heading_start(lines: list[tuple[int, str]], index: int) -> bool:
    upper = lines[index][1].strip().upper()
    if "CAPAIAN PEMBELAJARAN" in upper:
        return True
    if upper != "CAPAIAN":
        return False

    next_line = _next_non_empty_line_after(lines, index)
    return next_line.upper().startswith("PEMBELAJARAN")


def _next_non_empty_line_after(lines: list[tuple[int, str]], index: int) -> str:
    cursor = index + 1
    while cursor < len(lines):
        candidate = lines[cursor][1].strip()
        if candidate:
            return candidate
        cursor += 1
    return ""


def _previous_non_empty_line(lines: list[tuple[int, str]], index: int) -> str:
    for cursor in range(index - 1, max(-1, index - 6), -1):
        candidate = lines[cursor][1].strip()
        if candidate:
            return candidate
    return ""


def _collect_subject_name(lines: list[tuple[int, str]], index: int) -> str:
    _, line = lines[index]
    upper = line.upper()
    phrase_start = upper.find("CAPAIAN PEMBELAJARAN")
    if phrase_start >= 0:
        subject_start = phrase_start + len("CAPAIAN PEMBELAJARAN")
        chunks = [line[subject_start:].strip()] if line[subject_start:].strip() else []
        cursor = index + 1
    else:
        chunks = []
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor][1].strip()
            if not candidate:
                cursor += 1
                continue
            candidate_upper = candidate.upper()
            if candidate_upper.startswith("PEMBELAJARAN"):
                remainder = candidate[len("PEMBELAJARAN") :].strip()
                if remainder:
                    chunks.append(remainder)
                cursor += 1
            break

    while cursor < len(lines):
        candidate = lines[cursor][1].strip()
        candidate_upper = candidate.upper()
        if not candidate:
            cursor += 1
            continue
        if candidate_upper in {"A.", "B.", "C.", "D."}:
            break
        if candidate_upper.startswith("RASIONAL"):
            break
        if "CAPAIAN PEMBELAJARAN" in candidate_upper:
            break

        chunks.append(candidate)
        if len(" ".join(chunks)) > 180:
            break
        cursor += 1

    return _squash(" ".join(chunks))


def _content_start_after_subject(lines: list[tuple[int, str]], index: int) -> int:
    cursor = index + 1
    while cursor < len(lines):
        candidate = lines[cursor][1].strip()
        if candidate.upper() in {"A.", "B.", "C.", "D."}:
            return lines[cursor][0]
        cursor += 1
    return lines[index][0]


def _looks_like_subject(subject: str) -> bool:
    if not subject:
        return False

    upper = subject.upper()
    if upper.startswith(("PADA ", "UNTUK ", "FASE ", "1. FASE", "2. FASE", "3. FASE", "4. FASE", "5. FASE", "6. FASE")):
        return False
    if any(marker in upper for marker in ("PADA PENDIDIKAN", "UNTUK SD", "FASE FONDASI DI AKHIR")):
        return False

    letters = [char for char in subject if char.isalpha()]
    if not letters:
        return False
    uppercase_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
    return uppercase_ratio >= 0.65


def _is_container_heading(subject: str) -> bool:
    return subject.upper().strip() in {"MATA PELAJARAN PILIHAN SMK/MAK"}


def _lampiran_for_offset(events: list[LampiranEvent], offset: int) -> str | None:
    if not events:
        return None
    offsets = [event.offset for event in events]
    index = bisect.bisect_right(offsets, offset) - 1
    return events[index].lampiran if index >= 0 else None


def _extract_subject_records(
    file_name: str,
    text: str,
    page_starts: list[int],
    subject: SubjectBlock,
) -> list[dict[str, Any]]:
    subject_text = text[subject.content_start : subject.end]
    d_match = re.search(r"(?m)^\s*D\.\s*\n?\s*Capaian\s+Pembelajaran", subject_text, re.IGNORECASE)
    if not d_match:
        return []

    d_absolute_start = subject.content_start + d_match.start()
    d_text = subject_text[d_match.start() :]
    phases = list(_find_phase_headers(d_text))

    records: list[dict[str, Any]] = []
    if phases:
        for index, phase in enumerate(phases):
            next_start = phases[index + 1]["start"] if index + 1 < len(phases) else len(d_text)
            phase_text = d_text[phase["start"] : next_start].strip()
            records.append(
                _build_record(
                    file_name=file_name,
                    subject=subject,
                    phase=phase["phase"],
                    phase_description=phase["description"],
                    cp_text=phase_text,
                    start_offset=d_absolute_start + phase["start"],
                    end_offset=d_absolute_start + next_start,
                    page_starts=page_starts,
                    sequence=index + 1,
                )
            )
        return records

    fallback_phase = _infer_phase_from_body(d_text, subject.subject)
    if not fallback_phase:
        return []

    records.append(
        _build_record(
            file_name=file_name,
            subject=subject,
            phase=fallback_phase,
            phase_description=None,
            cp_text=d_text.strip(),
            start_offset=d_absolute_start,
            end_offset=subject.end,
            page_starts=page_starts,
            sequence=1,
        )
    )
    return records


def _find_phase_headers(d_text: str):
    pattern = re.compile(
        r"(?m)(?:^|\n)\s*(?:(?P<number>\d{1,2})\.\s*\n?\s*)?"
        r"Fase\s*\n?\s*(?P<phase>Fondasi|[A-F])\s*(?P<desc>\([^)]{0,500}\))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(d_text):
        yield {
            "start": match.start(),
            "phase": _normalize_phase(match.group("phase")),
            "description": _clean_description(match.group("desc")),
        }


def _infer_phase_from_body(d_text: str, subject: str) -> str | None:
    match = re.search(r"Pada\s+akhir\s+[Ff]ase\s+(Fondasi|[A-F])", d_text, re.IGNORECASE)
    if match:
        return _normalize_phase(match.group(1))
    if "PAUD" in subject.upper():
        return "Fondasi"
    return None


def _build_record(
    *,
    file_name: str,
    subject: SubjectBlock,
    phase: str,
    phase_description: str | None,
    cp_text: str,
    start_offset: int,
    end_offset: int,
    page_starts: list[int],
    sequence: int,
) -> dict[str, Any]:
    subject_normalized = _normalize_key(subject.subject)
    page_start = _page_for_offset(page_starts, start_offset)
    page_end = _page_for_offset(page_starts, max(start_offset, end_offset - 1))
    record_id = _record_id(file_name, subject_normalized, phase, page_start, sequence)

    return {
        "id": record_id,
        "domain": subject.domain,
        "lampiran": subject.lampiran,
        "jenjang": _infer_jenjang(phase, subject.domain),
        "subject": subject.subject,
        "subject_normalized": subject_normalized,
        "phase": phase,
        "phase_class_description": phase_description,
        "cp_overall_text": cp_text,
        "elements": [],
        "context": None,
        "source": {
            "pdf_path": file_name,
            "file_name": file_name,
            "page_start": page_start,
            "page_end": page_end,
            "anchors": [
                f"CAPAIAN PEMBELAJARAN {subject.subject}",
                f"Fase {phase}",
            ],
            "source_format": "pdf",
        },
        "parse_confidence": 1.0,
        "issues": [],
        "extraction_run_id": None,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def _page_for_offset(page_starts: list[int], offset: int) -> int:
    index = bisect.bisect_right(page_starts, offset) - 1
    return max(index + 1, 1)


def _normalize_phase(value: str) -> str:
    return "Fondasi" if value.lower() == "fondasi" else value.upper()


def _clean_description(value: str | None) -> str | None:
    if not value:
        return None
    return _squash(value.strip()[1:-1])


def _normalize_key(value: str) -> str:
    text = value.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _infer_jenjang(phase: str, domain: str | None) -> str | None:
    if domain == "PAUD" or phase == "Fondasi":
        return "PAUD"
    if domain == "SMK":
        return "SMK"
    if phase in {"A", "B", "C"}:
        return "SD"
    if phase == "D":
        return "SMP"
    if phase in {"E", "F"}:
        return "SMA"
    return None


def _record_id(file_name: str, subject_key: str, phase: str, page_start: int, sequence: int) -> str:
    raw = f"{Path(file_name).name}|{subject_key}|{phase}|{page_start}|{sequence}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
