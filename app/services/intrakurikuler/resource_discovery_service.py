from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, settings
from app.schemas.resource_discovery_schema import LearningResourceSchema


logger = logging.getLogger(__name__)


class ResourceDiscoveryService:
    def __init__(
        self,
        config: Settings = settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = config
        self.http_client = http_client

    async def discover(
        self,
        source_data: dict[str, Any],
    ) -> list[LearningResourceSchema]:
        stage3 = self._as_dict(source_data.get("stage3_learningStrategyFromKina"))
        existing = self._existing_resources(stage3.get("selectedResources"))
        if existing:
            return existing

        if not self.settings.resource_discovery_enabled:
            return []

        preferences = self._media_preferences(stage3)
        resource_types = self._resource_types(preferences, source_data)
        if not resource_types:
            return []

        query_context = self._query_context(source_data)
        tasks = []
        if "official_textbook" in resource_types:
            tasks.append(self._discover_books(query_context))
        if "youtube_video" in resource_types:
            tasks.append(self._discover_youtube(query_context))

        if not tasks:
            return []

        batches = await asyncio.gather(*tasks, return_exceptions=True)
        resources: list[LearningResourceSchema] = []
        for batch in batches:
            if isinstance(batch, Exception):
                logger.warning("Resource discovery provider gagal: %s", batch)
                continue
            resources.extend(batch)

        return sorted(resources, key=lambda item: item.confidence, reverse=True)

    def _existing_resources(self, value: Any) -> list[LearningResourceSchema]:
        if not isinstance(value, list):
            return []

        resources: list[LearningResourceSchema] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                resources.append(LearningResourceSchema.model_validate(item))
            except Exception:
                continue
        return resources

    def _media_preferences(self, stage3: dict[str, Any]) -> list[str]:
        raw = stage3.get("mediaPreferences")
        if isinstance(raw, list):
            values = [str(item).strip() for item in raw if str(item).strip()]
            if values:
                return values

        legacy = str(stage3.get("digitalPlatform") or "").casefold()
        preferences: list[str] = []
        if any(token in legacy for token in ("youtube", "video")):
            preferences.append("youtube_video")
        if any(token in legacy for token in ("buku", "modul", "kemendikdasmen")):
            preferences.append("official_textbook")
        if "tidak digunakan" in legacy:
            return ["non_digital"]
        return preferences

    def _resource_types(
        self,
        preferences: list[str],
        source_data: dict[str, Any],
    ) -> set[str]:
        selected = set(preferences)
        if "non_digital" in selected and len(selected) == 1:
            return set()

        if "auto" in selected or not selected:
            selected.add("official_textbook")
            if self._digital_access_available(source_data):
                selected.add("youtube_video")

        return selected.intersection(
            {"official_textbook", "youtube_video", "interactive_media"}
        )

    def _digital_access_available(self, source_data: dict[str, Any]) -> bool:
        stage1 = self._as_dict(source_data.get("stage1_basicContext"))
        stage3 = self._as_dict(source_data.get("stage3_learningStrategyFromKina"))
        context = " ".join(
            [
                self._text(stage1.get("fasilitasAwal")),
                self._text(stage3.get("facilityAndTechnologyUse")),
            ]
        ).casefold()
        return any(
            token in context
            for token in ("internet", "wifi", "wi-fi", "proyektor", "hp", "gawai")
        )

    def _query_context(self, source_data: dict[str, Any]) -> dict[str, str]:
        stage1 = self._as_dict(source_data.get("stage1_basicContext"))
        stage2 = self._as_dict(source_data.get("stage2_curriculumFoundation"))
        objectives = stage2.get("tujuanPembelajaranTerpilih") or []
        return {
            "subject": self._first_text(
                stage1.get("mataPelajaran"),
                self._as_dict(source_data.get("onboarding")).get("teacherSubject"),
            ),
            "topic": self._first_text(
                stage1.get("materiPokokBahasan"),
                stage1.get("topikMateriPokok"),
                stage1.get("topikMateriPokokBahasan"),
            ),
            "phase": self._first_text(stage1.get("fasePendidikan"), stage1.get("fase")),
            "grade": self._first_text(stage1.get("kelas"), stage1.get("gradeLevel")),
            "objective": self._text(objectives),
        }

    async def _discover_youtube(
        self,
        context: dict[str, str],
    ) -> list[LearningResourceSchema]:
        api_key = (self.settings.youtube_api_key or "").strip()
        if not api_key:
            return []

        query = " ".join(
            value
            for value in (
                context["subject"],
                context["topic"],
                context["grade"],
                "pembelajaran",
            )
            if value
        )
        base_url = self.settings.youtube_api_base_url.rstrip("/")
        search_data = await self._get_json(
            f"{base_url}/search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": self.settings.resource_discovery_max_results,
                "safeSearch": "strict",
                "videoDuration": "medium",
                "relevanceLanguage": "id",
                "regionCode": "ID",
                "key": api_key,
            },
        )
        items = search_data.get("items") if isinstance(search_data, dict) else []
        if not isinstance(items, list):
            return []

        video_ids = [
            str(
                self._as_dict(self._as_dict(item).get("id")).get("videoId")
                or ""
            )
            for item in items
            if isinstance(item, dict)
        ]
        video_ids = [item for item in video_ids if item]
        if not video_ids:
            return []

        details_data = await self._get_json(
            f"{base_url}/videos",
            {
                "part": "contentDetails,status",
                "id": ",".join(video_ids),
                "key": api_key,
            },
        )
        details = {
            str(item.get("id")): item
            for item in details_data.get("items", [])
            if isinstance(item, dict)
        }

        candidates: list[LearningResourceSchema] = []
        for item in items:
            item_dict = self._as_dict(item)
            video_id = str(self._as_dict(item_dict.get("id")).get("videoId") or "")
            snippet = self._as_dict(item_dict.get("snippet"))
            detail = self._as_dict(details.get(video_id))
            status = self._as_dict(detail.get("status"))
            if status and (
                status.get("privacyStatus") != "public"
                or status.get("embeddable") is False
            ):
                continue

            title = str(snippet.get("title") or "").strip()
            description = str(snippet.get("description") or "").strip()
            provider = str(snippet.get("channelTitle") or "YouTube").strip()
            if self._is_level_mismatch(
                f"{title} {description} {provider}",
                context,
            ):
                continue
            confidence = self._score_candidate(
                f"{title} {description} {provider}",
                context,
                official_bonus=self._looks_official(provider),
            )
            if confidence < 0.35:
                continue

            duration = self._duration_minutes(
                str(self._as_dict(detail.get("contentDetails")).get("duration") or "")
            )
            if duration is not None and duration > 20:
                continue
            candidates.append(
                LearningResourceSchema(
                    resourceType="youtube_video",
                    title=title,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    provider=provider,
                    description=description,
                    subject=context["subject"],
                    phase=context["phase"],
                    gradeLevel=context["grade"],
                    durationMinutes=duration,
                    usage="Pemantik atau penguatan konsep oleh guru.",
                    selectionReason=(
                        "Topik, mata pelajaran, jenjang, dan durasi paling dekat "
                        "dengan konteks pembelajaran yang dipilih guru."
                    ),
                    confidence=confidence,
                    verifiedAt=self._now_iso(),
                )
            )

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[:1]

    async def _discover_books(
        self,
        context: dict[str, str],
    ) -> list[LearningResourceSchema]:
        api_url = (self.settings.book_catalog_api_url or "").strip()
        if not api_url:
            return []

        data = await self._get_json(
            api_url,
            self._book_catalog_params(api_url, context),
        )
        items = self._catalog_items(data)
        allowed_domains = self._allowed_book_domains()
        target_grade = self._grade_number(context["grade"])
        candidates: list[LearningResourceSchema] = []
        for item in items:
            title = self._first_text(item.get("title"), item.get("name"))
            url = self._first_text(
                item.get("url"),
                item.get("downloadUrl"),
                item.get("detailUrl"),
                item.get("attachment"),
            )
            if not title or not url or not self._domain_allowed(url, allowed_domains):
                continue

            candidate_grade = self._grade_number(
                self._first_text(item.get("class"), item.get("gradeLevel"))
            )
            description = self._first_text(
                item.get("description"),
                item.get("summary"),
            ) or "Buku teks resmi yang tersedia melalui katalog SIBI."
            provider = self._first_text(
                item.get("publisher"),
                item.get("provider"),
                item.get("unit"),
            ) or "Pusat Perbukuan"
            confidence = self._score_candidate(
                f"{title} {description} {self._text(item)}",
                context,
                official_bonus=True,
            )
            confidence = self._book_confidence_adjustment(
                confidence,
                item,
                context,
                target_grade,
                candidate_grade,
            )
            if confidence < 0.35:
                continue

            candidates.append(
                LearningResourceSchema(
                    resourceType="official_textbook",
                    title=title,
                    url=url,
                    provider=provider,
                    description=description,
                    subject=self._first_text(item.get("subject"), context["subject"]),
                    phase=self._first_text(
                        item.get("phase"),
                        self._phase_for_grade(candidate_grade),
                        context["phase"],
                    ),
                    gradeLevel=self._first_text(
                        item.get("gradeLevel"),
                        self._grade_label(candidate_grade),
                        context["grade"],
                    ),
                    usage="Rujukan konsep dan latihan terarah.",
                    selectionReason=(
                        "Sumber resmi dengan mata pelajaran, fase, kelas, dan topik "
                        "yang paling dekat dengan konteks pembelajaran."
                    ),
                    confidence=confidence,
                    verifiedAt=self._now_iso(),
                )
            )

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[:1]

    def _book_catalog_params(
        self,
        api_url: str,
        context: dict[str, str],
    ) -> dict[str, Any]:
        hostname = (urlparse(api_url).hostname or "").casefold()
        if hostname == "api.buku.cloudapp.web.id":
            return {
                "title": context["subject"] or context["topic"],
                "limit": max(100, self.settings.resource_discovery_max_results),
                "offset": 0,
            }

        return {
            "q": " ".join(
                value
                for value in (context["subject"], context["topic"])
                if value
            ),
            "subject": context["subject"],
            "phase": context["phase"],
            "gradeLevel": context["grade"],
            "limit": self.settings.resource_discovery_max_results,
        }

    def _book_confidence_adjustment(
        self,
        confidence: float,
        item: dict[str, Any],
        context: dict[str, str],
        target_grade: int | None,
        candidate_grade: int | None,
    ) -> float:
        score = confidence
        if target_grade and candidate_grade:
            score += 0.25 if target_grade == candidate_grade else -0.2

        candidate_subject = self._first_text(item.get("subject")).casefold()
        expected_subject = context["subject"].casefold()
        if candidate_subject and expected_subject:
            if candidate_subject == expected_subject:
                score += 0.15
            elif expected_subject not in candidate_subject:
                score -= 0.1

        book_type = self._first_text(item.get("book_type")).casefold()
        title = self._first_text(item.get("title")).casefold()
        if book_type == "buku_siswa" and "panduan guru" not in title:
            score += 0.05
        elif "panduan guru" in title or book_type == "buku_guru":
            score -= 0.03

        resource_type = str(item.get("type") or "").casefold()
        attachment = self._first_text(item.get("attachment"), item.get("url"))
        if resource_type == "pdf" or attachment.casefold().endswith(".pdf"):
            score += 0.03
        else:
            score -= 0.08
        return round(max(0, min(score, 1.0)), 3)

    def _grade_number(self, value: str) -> int | None:
        normalized = value.casefold().strip()
        digits = re.findall(r"\d+", normalized)
        if digits:
            return int(digits[0])

        roman_values = {
            "xii": 12,
            "xi": 11,
            "x": 10,
            "ix": 9,
            "viii": 8,
            "vii": 7,
            "vi": 6,
            "v": 5,
            "iv": 4,
            "iii": 3,
            "ii": 2,
            "i": 1,
        }
        for token in re.findall(r"[a-z]+", normalized):
            if token in roman_values:
                return roman_values[token]
        return None

    def _grade_label(self, grade: int | None) -> str:
        if grade is None:
            return ""
        roman = {
            1: "I",
            2: "II",
            3: "III",
            4: "IV",
            5: "V",
            6: "VI",
            7: "VII",
            8: "VIII",
            9: "IX",
            10: "X",
            11: "XI",
            12: "XII",
        }
        return f"Kelas {roman.get(grade, grade)}"

    def _phase_for_grade(self, grade: int | None) -> str:
        if grade is None:
            return ""
        if grade <= 2:
            return "Fase A"
        if grade <= 4:
            return "Fase B"
        if grade <= 6:
            return "Fase C"
        if grade <= 9:
            return "Fase D"
        if grade == 10:
            return "Fase E"
        return "Fase F"

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.http_client is not None:
            response = await self.http_client.get(url, params=params)
            response.raise_for_status()
            return self._as_dict(response.json())

        timeout = self.settings.resource_discovery_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return self._as_dict(response.json())

    def _catalog_items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("items", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = value.get("items") or value.get("results")
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
        return []

    def _score_candidate(
        self,
        text: str,
        context: dict[str, str],
        *,
        official_bonus: bool,
    ) -> float:
        haystack = self._tokens(text)
        topic = self._tokens(context["topic"])
        subject = self._tokens(context["subject"])
        grade = self._tokens(context["grade"])
        phase = self._tokens(context["phase"])

        score = 0.2
        score += 0.35 * self._token_coverage(topic, haystack)
        score += 0.2 * self._token_coverage(subject, haystack)
        score += 0.1 * self._token_coverage(grade, haystack)
        score += 0.05 * self._token_coverage(phase, haystack)
        if official_bonus:
            score += 0.1
        return round(min(score, 1.0), 3)

    def _tokens(self, value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.casefold())
            if len(token) > 2
        }

    def _token_coverage(self, needles: set[str], haystack: set[str]) -> float:
        if not needles:
            return 0
        return len(needles.intersection(haystack)) / len(needles)

    def _duration_minutes(self, value: str) -> int | None:
        match = re.fullmatch(
            r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
            value,
        )
        if not match:
            return None
        seconds = (
            int(match.group("hours") or 0) * 3600
            + int(match.group("minutes") or 0) * 60
            + int(match.group("seconds") or 0)
        )
        return max(1, round(seconds / 60))

    def _looks_official(self, provider: str) -> bool:
        normalized = provider.casefold()
        return any(
            token in normalized
            for token in (
                "kemendikdasmen",
                "kemendikbud",
                "pusdatin",
                "direktorat",
                "balai",
                "rumah belajar",
            )
        )

    def _is_level_mismatch(self, text: str, context: dict[str, str]) -> bool:
        grade = self._grade_number(context["grade"])
        if grade is None or grade > 12:
            return False
        normalized = text.casefold()
        return any(
            token in normalized
            for token in (
                "matakuliah",
                "mata kuliah",
                "perkuliahan",
                "kuliah ",
                "mahasiswa",
                "dosen",
                "universitas",
                "tugas pertemuan",
                "video ini dibuat untuk memenuhi",
                " nim ",
                "prodi",
            )
        )

    def _allowed_book_domains(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.settings.book_catalog_allowed_domains.split(",")
            if item.strip()
        }

    def _domain_allowed(self, url: str, allowed_domains: set[str]) -> bool:
        hostname = (urlparse(url).hostname or "").casefold()
        return bool(
            hostname
            and any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _text(self, value: Any) -> str:
        if isinstance(value, list):
            return " ".join(self._text(item) for item in value)
        if isinstance(value, dict):
            return " ".join(self._text(item) for item in value.values())
        return str(value or "").strip()

    def _first_text(self, *values: Any) -> str:
        for value in values:
            text = self._text(value)
            if text:
                return text
        return ""
