from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.environment_schema import (
    SchoolEnvironmentCurationRequest,
    SchoolEnvironmentCurationResponse,
    SchoolEnvironmentPlace,
)
from app.services.llm_client import LLMClient


COLOR_KEYS = {"emerald", "amber", "blue", "violet", "rose", "slate", "cyan", "gray"}
CANDIDATE_LIMIT = 500
ROUTE_NAME_PATTERN = re.compile(
    r"^(gg\.?|gang|jl\.?|jalan|jln\.?|lorong|kp\.?|kampung|blok)\b",
    re.IGNORECASE,
)
PRIVATE_OR_NOISY_NAME_PATTERN = re.compile(
    r"\b(rumah|kontrakan|kost|kos|basecamp|secretariat|sekretariat|mberr|test|dummy|mansion|residence|residences|apartment|apartemen|tower|cluster|villa)\b",
    re.IGNORECASE,
)
EXCLUDED_TYPES = {
    "parking",
    "parking_lot",
    "gas_station",
    "car_wash",
    "atm",
    "bus_stop",
    "lodging",
    "hotel",
    "motel",
    "night_club",
    "bar",
    "car_repair",
    "car_dealer",
    "route",
    "street_address",
    "intersection",
    "neighborhood",
    "sublocality",
    "political",
}
TRUSTED_TYPES = {
    "restaurant",
    "cafe",
    "bakery",
    "meal_takeaway",
    "supermarket",
    "grocery_store",
    "convenience_store",
    "store",
    "shopping_mall",
    "market",
    "park",
    "playground",
    "garden",
    "museum",
    "library",
    "tourist_attraction",
    "historical_landmark",
    "cultural_landmark",
    "school",
    "primary_school",
    "secondary_school",
    "university",
    "hospital",
    "pharmacy",
    "doctor",
    "dentist",
    "clinic",
    "mosque",
    "church",
    "hindu_temple",
    "place_of_worship",
    "local_government_office",
    "post_office",
    "police",
    "bank",
    "gym",
    "sports_complex",
    "stadium",
}


class EnvironmentCurationService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    async def curate(
        self, payload: SchoolEnvironmentCurationRequest
    ) -> SchoolEnvironmentCurationResponse:
        candidates = [
            candidate
            for candidate in payload.candidates[:CANDIDATE_LIMIT]
            if self._is_sensible_candidate(candidate)
        ]
        fallback = self._fallback_response(payload, candidates)
        if not candidates:
            return fallback

        messages = [
            {
                "role": "system",
                "content": (
                    "Anda adalah analis konteks lingkungan sekolah untuk guru Indonesia. "
                    "Tugas Anda memilih tempat sekitar sekolah yang paling bermakna untuk "
                    "pembelajaran kontekstual. Kategorikan sendiri secara pedagogis, bukan "
                    "sekadar mengikuti tipe Google Places. Return hanya JSON object valid."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "schoolName": payload.schoolName,
                        "schoolAddress": payload.schoolAddress,
                        "radiusMeters": payload.radiusMeters,
                        "rules": [
                            "Pilih maksimal maxPlaces tempat dari candidates.",
                            "Jika kandidatnya tersedia, hasilkan beberapa kategori berbeda, minimal minCategories kategori.",
                            "Setiap kategori berisi 2 sampai 3 tempat jika kandidatnya tersedia.",
                            "Jangan gunakan id yang tidak ada di candidates.",
                            "Boleh membuat kategori sendiri yang cocok untuk pembelajaran.",
                            "Validasi nama tempat: jangan pilih nama yang terlihat seperti gang, jalan, alamat, rumah pribadi, komentar, slang, atau teks iseng.",
                            "Contoh yang harus ditolak: nama diawali Gg/Gang/Jl/Jalan tanpa jenis usaha/fasilitas yang jelas.",
                            "Hindari tempat yang terlalu berisiko atau kurang relevan untuk observasi murid.",
                            "categoryId harus kebab-case singkat.",
                            "colorKey harus salah satu: emerald, amber, blue, violet, rose, slate, cyan, gray.",
                            "relevanceScore harus integer 0-100.",
                        ],
                        "maxPlaces": payload.maxPlaces,
                        "maxPlacesPerCategory": payload.maxPlacesPerCategory,
                        "minCategories": payload.minCategories,
                        "responseShape": {
                            "summary": "ringkasan singkat bahasa Indonesia",
                            "places": [
                                {
                                    "id": "id kandidat",
                                    "categoryId": "kebab-case",
                                    "category": "label kategori",
                                    "colorKey": "emerald|amber|blue|violet|rose|slate|cyan|gray",
                                    "relevanceNote": "alasan singkat untuk pembelajaran",
                                    "relevanceScore": 0,
                                }
                            ],
                        },
                        "candidates": [
                            self._candidate_for_prompt(candidate)
                            for candidate in candidates
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        generated = await self.llm_client.generate_json(
            messages,
            fallback.model_dump(),
            temperature=0.2,
            max_tokens=4500,
        )
        return self._normalize_response(payload, generated, candidates)

    def _normalize_response(
        self,
        payload: SchoolEnvironmentCurationRequest,
        generated: dict[str, Any],
        candidates: list[Any],
    ) -> SchoolEnvironmentCurationResponse:
        valid_ids = {candidate.id for candidate in candidates}
        category_counts: dict[str, int] = {}
        places: list[SchoolEnvironmentPlace] = []

        raw_places = generated.get("places")
        if not isinstance(raw_places, list):
            raw_places = []

        for raw in raw_places:
            if not isinstance(raw, dict):
                continue
            place_id = str(raw.get("id") or "").strip()
            if not place_id or place_id not in valid_ids:
                continue
            if any(place.id == place_id for place in places):
                continue

            category = str(raw.get("category") or "").strip() or "Lingkungan sekitar"
            category_id = self._slug(str(raw.get("categoryId") or category))
            current_count = category_counts.get(category_id, 0)
            if current_count >= max(1, payload.maxPlacesPerCategory):
                continue

            color_key = str(raw.get("colorKey") or "gray").strip()
            if color_key not in COLOR_KEYS:
                color_key = "gray"

            score = raw.get("relevanceScore")
            if not isinstance(score, (int, float)):
                score = 70
            score = max(0, min(100, int(round(score))))

            note = str(raw.get("relevanceNote") or "").strip()
            if not note:
                note = "Relevan sebagai konteks observasi dan diskusi pembelajaran."

            places.append(
                SchoolEnvironmentPlace(
                    id=place_id,
                    categoryId=category_id,
                    category=category,
                    colorKey=color_key,
                    relevanceNote=note,
                    relevanceScore=score,
                )
            )
            category_counts[category_id] = current_count + 1
            if len(places) >= max(1, payload.maxPlaces):
                break

        if not places:
            return self._fallback_response(payload, candidates)

        places = self._augment_sparse_categories(payload, candidates, places)

        summary = str(generated.get("summary") or "").strip()
        if not summary:
            school = payload.schoolName or "sekolah"
            category_labels = []
            for place in places:
                if place.category not in category_labels:
                    category_labels.append(place.category)
            summary = (
                f"Ditemukan {len(places)} tempat sekitar {school} dalam radius "
                f"{payload.radiusMeters / 1000:g} km yang dikelompokkan menjadi "
                f"{len(category_labels)} kategori konteks belajar."
            )

        return SchoolEnvironmentCurationResponse(summary=summary, places=places)

    def _fallback_response(
        self,
        payload: SchoolEnvironmentCurationRequest,
        candidates: list[Any] | None = None,
    ) -> SchoolEnvironmentCurationResponse:
        candidates = candidates or [
            candidate
            for candidate in payload.candidates[:CANDIDATE_LIMIT]
            if self._is_sensible_candidate(candidate)
        ]
        places = self._fallback_places(payload, candidates)

        if not places:
            fallback_limit = min(
                max(1, payload.maxPlaces), max(1, payload.maxPlacesPerCategory)
            )
            places = [
                SchoolEnvironmentPlace(
                    id=candidate.id,
                    categoryId="lingkungan-sekitar",
                    category="Lingkungan sekitar",
                    colorKey="gray",
                    relevanceNote="Dapat dipakai untuk observasi umum di sekitar sekolah.",
                    relevanceScore=60,
                )
                for candidate in candidates[:fallback_limit]
            ]

        school = payload.schoolName or "sekolah"
        return SchoolEnvironmentCurationResponse(
            summary=(
                f"Ditemukan {len(places)} tempat sekitar {school} dalam radius "
                f"{payload.radiusMeters / 1000:g} km yang dapat menjadi konteks belajar."
            ),
            places=places,
        )

    def _fallback_places(
        self,
        payload: SchoolEnvironmentCurationRequest,
        candidates: list[Any],
        exclude_ids: set[str] | None = None,
    ) -> list[SchoolEnvironmentPlace]:
        exclude_ids = exclude_ids or set()
        buckets = [
            {
                "categoryId": "ekonomi-lokal",
                "category": "Ekonomi lokal",
                "colorKey": "amber",
                "signals": (
                    "restaurant",
                    "cafe",
                    "store",
                    "market",
                    "shop",
                    "warung",
                ),
            },
            {
                "categoryId": "ruang-terbuka",
                "category": "Ruang terbuka & lingkungan",
                "colorKey": "emerald",
                "signals": ("park", "playground", "garden"),
            },
            {
                "categoryId": "pendidikan-literasi",
                "category": "Pendidikan & literasi",
                "colorKey": "blue",
                "signals": ("school", "library", "university"),
            },
            {
                "categoryId": "layanan-publik",
                "category": "Layanan publik",
                "colorKey": "cyan",
                "signals": (
                    "office",
                    "post_office",
                    "police",
                    "transit",
                    "station",
                    "bank",
                ),
            },
            {
                "categoryId": "kesehatan",
                "category": "Kesehatan warga",
                "colorKey": "rose",
                "signals": ("hospital", "pharmacy", "doctor", "clinic", "health"),
            },
            {
                "categoryId": "tempat-ibadah",
                "category": "Tempat ibadah & nilai sosial",
                "colorKey": "slate",
                "signals": (
                    "worship",
                    "mosque",
                    "church",
                    "temple",
                ),
            },
            {
                "categoryId": "budaya-sejarah",
                "category": "Budaya & sejarah",
                "colorKey": "violet",
                "signals": (
                    "museum",
                    "tourist",
                    "historical",
                    "cultural",
                ),
            },
        ]
        places: list[SchoolEnvironmentPlace] = []
        counts: dict[str, int] = {}

        for candidate in candidates:
            if candidate.id in exclude_ids:
                continue
            text = " ".join(
                [
                    candidate.name,
                    candidate.primaryType or "",
                    *candidate.types,
                ]
            ).casefold()
            bucket = next(
                (
                    item
                    for item in buckets
                    if any(signal in text for signal in item["signals"])
                ),
                None,
            )
            if not bucket:
                continue
            category_id = str(bucket["categoryId"])
            count = counts.get(category_id, 0)
            if count >= max(1, payload.maxPlacesPerCategory):
                continue
            places.append(
                SchoolEnvironmentPlace(
                    id=candidate.id,
                    categoryId=category_id,
                    category=str(bucket["category"]),
                    colorKey=str(bucket["colorKey"]),
                    relevanceNote="Dipilih sebagai konteks sekitar sekolah yang mudah diamati murid.",
                    relevanceScore=max(55, 90 - int(candidate.distanceMeters / 250)),
                )
            )
            counts[category_id] = count + 1
            if len(places) >= max(1, payload.maxPlaces):
                break

        return places

    def _augment_sparse_categories(
        self,
        payload: SchoolEnvironmentCurationRequest,
        candidates: list[Any],
        places: list[SchoolEnvironmentPlace],
    ) -> list[SchoolEnvironmentPlace]:
        max_places = max(1, payload.maxPlaces)
        min_categories = max(1, min(payload.minCategories, max_places // 2))
        selected_ids = {place.id for place in places}
        category_ids = {place.categoryId for place in places}
        category_counts = self._category_counts(places)

        if self._visible_category_count(category_counts) >= min_categories:
            return places[:max_places]

        fallback_places = self._fallback_places(payload, candidates, selected_ids)

        for place in fallback_places:
            if len(places) >= max_places:
                break
            if place.id in selected_ids:
                continue

            category_count = category_counts.get(place.categoryId, 0)
            if category_count >= max(1, payload.maxPlacesPerCategory):
                continue

            need_new_category = (
                self._visible_category_count(category_counts) < min_categories
                and len(category_ids) < min_categories
            )
            if need_new_category and place.categoryId in category_ids:
                continue

            places.append(place)
            selected_ids.add(place.id)
            category_ids.add(place.categoryId)
            category_counts[place.categoryId] = category_count + 1

        return places[:max_places]

    def _category_counts(
        self, places: list[SchoolEnvironmentPlace]
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for place in places:
            counts[place.categoryId] = counts.get(place.categoryId, 0) + 1
        return counts

    def _visible_category_count(self, counts: dict[str, int]) -> int:
        return sum(1 for count in counts.values() if count >= 2)

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        return slug or "lingkungan-sekitar"

    def _candidate_for_prompt(self, candidate: Any) -> dict[str, Any]:
        return {
            "id": candidate.id,
            "name": candidate.name,
            "primaryType": candidate.primaryType,
            "types": candidate.types[:8],
            "distanceMeters": round(candidate.distanceMeters),
            "distanceLabel": candidate.distanceLabel,
        }

    def _is_sensible_candidate(self, candidate: Any) -> bool:
        name = re.sub(r"\s+", " ", str(candidate.name or "")).strip()
        types = [
            str(value).strip().casefold()
            for value in [candidate.primaryType or "", *candidate.types]
            if str(value).strip()
        ]
        has_trusted_type = any(value in TRUSTED_TYPES for value in types)

        if len(name) < 3 or len(name) > 90 or not re.search(r"[A-Za-zÀ-ÿ]", name):
            return False
        if any(value in EXCLUDED_TYPES for value in types):
            return False
        if PRIVATE_OR_NOISY_NAME_PATTERN.search(name):
            return False
        if ROUTE_NAME_PATTERN.search(name) and not has_trusted_type:
            return False
        if (
            not has_trusted_type
            and re.fullmatch(r"[\w\s.'-]+", name)
            and len(name.split()) > 5
        ):
            return False
        return True
