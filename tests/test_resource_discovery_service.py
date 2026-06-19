from __future__ import annotations

import asyncio
import unittest

import httpx

from app.core.config import Settings
from app.services.intrakurikuler.resource_discovery_service import (
    ResourceDiscoveryService,
)


def source_data(preferences: list[str]) -> dict:
    return {
        "stage1_basicContext": {
            "mataPelajaran": "Matematika",
            "materiPokokBahasan": "diskrit",
            "fase": "Fase E",
            "kelas": "Kelas X",
            "fasilitasAwal": ["Proyektor", "Internet"],
        },
        "stage2_curriculumFoundation": {
            "tujuanPembelajaranTerpilih": [
                "Murid mampu membedakan data diskrit dan kontinu."
            ]
        },
        "stage3_learningStrategyFromKina": {
            "mediaPreferences": preferences,
            "mediaUsage": "Pemantik dan penguatan konsep oleh guru.",
            "resourceDiscoveryMode": "automatic",
            "selectedResources": [],
        },
    }


class ResourceDiscoveryServiceTest(unittest.TestCase):
    def test_non_digital_does_not_call_provider(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        async def run() -> list:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                service = ResourceDiscoveryService(
                    Settings(YOUTUBE_API_KEY="test-key"),
                    client,
                )
                return await service.discover(source_data(["non_digital"]))

        self.assertEqual(asyncio.run(run()), [])
        self.assertEqual(calls, 0)

    def test_youtube_uses_api_and_returns_verified_candidate(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search"):
                self.assertEqual(request.url.params.get("videoDuration"), "medium")
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": {"videoId": "college-video"},
                                "snippet": {
                                    "title": "Kuliah Matematika Diskrit",
                                    "description": "Materi untuk mahasiswa dan dosen.",
                                    "channelTitle": "Kuliah Teknokrat",
                                },
                            },
                            {
                                "id": {"videoId": "video-1"},
                                "snippet": {
                                    "title": "Matematika Diskrit Kelas X",
                                    "description": "Membedakan data diskrit dan kontinu.",
                                    "channelTitle": "Kemendikdasmen RI",
                                },
                            }
                        ]
                    },
                )
            if request.url.path.endswith("/videos"):
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": "college-video",
                                "contentDetails": {"duration": "PT12M"},
                                "status": {
                                    "privacyStatus": "public",
                                    "embeddable": True,
                                },
                            },
                            {
                                "id": "video-1",
                                "contentDetails": {"duration": "PT8M30S"},
                                "status": {
                                    "privacyStatus": "public",
                                    "embeddable": True,
                                },
                            }
                        ]
                    },
                )
            return httpx.Response(404)

        async def run() -> list:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                service = ResourceDiscoveryService(
                    Settings(YOUTUBE_API_KEY="test-key"),
                    client,
                )
                return await service.discover(source_data(["youtube_video"]))

        resources = asyncio.run(run())
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].resourceType, "youtube_video")
        self.assertEqual(resources[0].durationMinutes, 8)
        self.assertEqual(
            resources[0].url,
            "https://www.youtube.com/watch?v=video-1",
        )
        self.assertGreaterEqual(resources[0].confidence, 0.35)

    def test_book_catalog_rejects_non_allowed_download_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "title": "Matematika Kelas X",
                            "url": "https://untrusted.example/book.pdf",
                            "subject": "Matematika",
                            "phase": "Fase E",
                            "gradeLevel": "Kelas X",
                        }
                    ]
                },
            )

        async def run() -> list:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                service = ResourceDiscoveryService(
                    Settings(
                        BOOK_CATALOG_API_URL="https://catalog.internal/books",
                        BOOK_CATALOG_ALLOWED_DOMAINS="buku.kemendikdasmen.go.id",
                    ),
                    client,
                )
                return await service.discover(
                    source_data(["official_textbook"])
                )

        self.assertEqual(asyncio.run(run()), [])

    def test_sibi_catalog_prefers_matching_student_book_and_grade(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params.get("title"), "Matematika")
            self.assertEqual(request.url.params.get("limit"), "100")
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "results": [
                        {
                            "title": "Buku Interaktif Matematika Kelas X",
                            "attachment": "https://static-sc.cloudapp.web.id/matematika-x/",
                            "subject": "matematika",
                            "class": "10",
                            "level": "SMA/SMK",
                            "book_type": "buku_siswa",
                            "publisher": "Pusat Perbukuan",
                            "type": "interactive",
                        },
                        {
                            "title": "Matematika untuk SMA Kelas XII",
                            "attachment": "https://static.sc.cloudapp.web.id/xii.pdf",
                            "subject": "matematika",
                            "class": "12",
                            "level": "SMA",
                            "book_type": "buku_siswa",
                            "publisher": "Pusat Perbukuan",
                            "type": "pdf",
                        },
                        {
                            "title": "Matematika untuk SMA/SMK Kelas X",
                            "attachment": "https://static-sc.cloudapp.web.id/x.pdf",
                            "subject": "matematika",
                            "class": "10",
                            "level": "SMA/SMK",
                            "book_type": "buku_siswa",
                            "publisher": "Pusat Perbukuan",
                            "type": "pdf",
                        },
                    ],
                },
            )

        async def run() -> list:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                service = ResourceDiscoveryService(
                    Settings(
                        BOOK_CATALOG_API_URL=(
                            "https://api.buku.cloudapp.web.id/api/catalogue/"
                            "getPenggerakTextBooks"
                        ),
                        BOOK_CATALOG_ALLOWED_DOMAINS=(
                            "static.sc.cloudapp.web.id,"
                            "static-sc.cloudapp.web.id"
                        ),
                    ),
                    client,
                )
                return await service.discover(
                    source_data(["official_textbook"])
                )

        resources = asyncio.run(run())
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].title, "Matematika untuk SMA/SMK Kelas X")
        self.assertEqual(resources[0].gradeLevel, "Kelas X")
        self.assertEqual(resources[0].phase, "Fase E")
        self.assertEqual(resources[0].url, "https://static-sc.cloudapp.web.id/x.pdf")


if __name__ == "__main__":
    unittest.main()
