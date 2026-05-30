from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import httpx

from app.config import settings


class OpenRouterClient:
    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.base_url = settings.openrouter_base_url

    async def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self.api_key:
            return self._mock_stage_3_response(user_prompt)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Kina MVP Backend",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return self._safe_json_loads(content)

    def _safe_json_loads(self, text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError(f"LLM tidak mengembalikan JSON valid: {text}")
            return json.loads(match.group(0))

    # def _mock_stage_3_response(self, _: str) -> Dict[str, Any]:
    #     return {
    #         "assistant_message": (
    #             "Baik, saya susun rancangan Stage 3 berbasis data dummy Stage 1 dan Stage 2. "
    #             "Rancangannya memakai pembelajaran kontekstual dan aktivitas kelompok agar siswa aktif berdiskusi."
    #         ),
    #         "structured_update": {
    #             "pendekatan_pembelajaran": "Kontekstual",
    #             "model_pembelajaran": "Problem Based Learning",
    #             "metode_pembelajaran": ["Diskusi kelompok", "Latihan kontekstual", "Presentasi singkat"],
    #             "kegiatan_pembuka": [
    #                 "Guru menampilkan masalah harga beberapa barang dengan jumlah berbeda.",
    #                 "Guru mengajukan pertanyaan pemantik tentang hubungan jumlah barang dan harga.",
    #             ],
    #             "kegiatan_inti": [
    #                 "Siswa mengamati tabel jumlah barang dan harga total.",
    #                 "Siswa berdiskusi dalam kelompok untuk menemukan pola perbandingan senilai.",
    #                 "Siswa mengerjakan LKPD berisi masalah sehari-hari tentang rasio dan proporsi.",
    #                 "Perwakilan kelompok mempresentasikan strategi penyelesaian.",
    #             ],
    #             "kegiatan_penutup": [
    #                 "Guru dan siswa menyimpulkan ciri-ciri perbandingan senilai.",
    #                 "Siswa menulis refleksi singkat tentang cara menentukan nilai yang belum diketahui.",
    #             ],
    #             "diferensiasi": {
    #                 "dukungan": "Siswa yang membutuhkan bantuan diberi tabel rasio dan contoh langkah penyelesaian.",
    #                 "tantangan": "Siswa cepat diberi masalah variasi dengan angka lebih kompleks.",
    #             },
    #             "pertanyaan_pemantik": [
    #                 "Jika 3 buku harganya Rp15.000, bagaimana menentukan harga 5 buku?",
    #                 "Apa tanda bahwa dua besaran memiliki hubungan senilai?",
    #             ],
    #             "aktivitas_lkpd_modul": [
    #                 "Mengisi tabel jumlah barang dan harga.",
    #                 "Menyelesaikan masalah rasio dalam kelompok.",
    #                 "Menyampaikan alasan penyelesaian di depan kelas.",
    #             ],
    #         },
    #         "missing_fields": [],
    #         "next_question": "Apakah rancangan ini ingin dibuat lebih sederhana, lebih menantang, atau langsung lanjut ke Stage 4?",
    #     }
    def _mock_stage_3_response(self, _: str) -> Dict[str, Any]:
        return {
            "assistant_message": (
                "Baik, kita mulai Stage 3 secara bertahap. "
                "Pertama, saya perlu tahu gaya pembelajaran yang diinginkan."
            ),
            "structured_update": {
                "teacher_inputs": {},
                "ai_outputs": {},
                "progress": {
                    "active_field": "gaya_pembelajaran",
                    "completed_fields": [],
                    "is_ready_to_generate_outputs": False,
                    "is_stage_3_complete": False,
                },
            },
            "missing_fields": ["gaya_pembelajaran"],
            "next_question": (
                "Guru ingin pembelajaran lebih banyak diskusi, eksperimen, "
                "studi kasus, proyek kecil, atau campuran?"
            ),
    }
