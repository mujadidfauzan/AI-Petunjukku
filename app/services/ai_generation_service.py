from __future__ import annotations

from typing import Any, Dict

from app.data_store import store


class AIGenerationService:
    """Generate dokumen final dari Stage 1, 2, 3, dan 4 untuk MVP."""

    def generate_document(self, project_id: str, output_type: str = "lkpd") -> Dict[str, Any]:
        project = store.get_project(project_id)
        planning_state = store.get_planning_state(project_id)

        learning_brief = planning_state.get("learning_brief", {})
        curriculum = planning_state.get("curriculum", {})
        strategy = planning_state.get("strategy", {})
        assessment = planning_state.get("assessment", {})

        missing = []
        if not learning_brief:
            missing.append("Stage 1 / learning_brief")
        if not curriculum:
            missing.append("Stage 2 / curriculum")
        if not strategy:
            missing.append("Stage 3 / strategy")
        if not assessment:
            missing.append("Stage 4 / assessment")

        if missing:
            raise ValueError(f"Belum bisa generate. Data belum lengkap: {', '.join(missing)}")

        document = {
            "judul": project.get("title", "Dokumen Pembelajaran"),
            "output_type": output_type,
            "identitas": {
                "jenjang": learning_brief.get("jenjang_pendidikan"),
                "fase": learning_brief.get("fase_pendidikan"),
                "kelas": learning_brief.get("kelas"),
                "mata_pelajaran": learning_brief.get("mapel_utama"),
                "durasi": learning_brief.get("durasi_pembelajaran"),
            },
            "konteks_peserta_didik": learning_brief.get("karakter_siswa"),
            "tujuan_pembelajaran": curriculum.get("tujuan_pembelajaran"),
            "profil_pelajar_pancasila": curriculum.get("profil_pelajar_pancasila", []),
            "rancangan_pembelajaran": {
                "pendekatan": strategy.get("pendekatan_pembelajaran"),
                "model": strategy.get("model_pembelajaran"),
                "metode": strategy.get("metode_pembelajaran", []),
                "pertanyaan_pemantik": strategy.get("pertanyaan_pemantik", []),
                "langkah_pembelajaran": {
                    "pembuka": strategy.get("kegiatan_pembuka", []),
                    "inti": strategy.get("kegiatan_inti", []),
                    "penutup": strategy.get("kegiatan_penutup", []),
                },
                "diferensiasi": strategy.get("diferensiasi", {}),
            },
            "aktivitas_lkpd_modul": strategy.get("aktivitas_lkpd_modul", []),
            "asesmen": {
                "jenis": assessment.get("jenis_asesmen"),
                "teknik": assessment.get("teknik_penilaian", []),
                "rubrik": assessment.get("rubrik_penilaian", []),
            },
            "media_alat_bahan": {
                "media": assessment.get("media_pembelajaran", []),
                "alat_bahan": assessment.get("alat_bahan", []),
            },
            "refleksi": {
                "siswa": assessment.get("refleksi_siswa"),
                "guru": assessment.get("refleksi_guru"),
            },
        }

        saved = store.save_generated_document(project_id, output_type, document)
        planning_state["generated_documents"][output_type] = saved
        planning_state["content_json"] = document
        planning_state["content_markdown"] = self._to_markdown(document)
        store.save_planning_state(project_id, planning_state)
        return saved

    def _to_markdown(self, document: Dict[str, Any]) -> str:
        lines = [f"# {document['judul']}", ""]
        lines.append("## Identitas")
        for key, value in document["identitas"].items():
            lines.append(f"- {key}: {value}")
        lines.append("\n## Tujuan Pembelajaran")
        lines.append(str(document.get("tujuan_pembelajaran", "-")))
        lines.append("\n## Langkah Pembelajaran")
        langkah = document["rancangan_pembelajaran"]["langkah_pembelajaran"]
        for bagian, items in langkah.items():
            lines.append(f"### {bagian.title()}")
            for item in items:
                lines.append(f"- {item}")
        lines.append("\n## Asesmen")
        for teknik in document["asesmen"].get("teknik", []):
            lines.append(f"- {teknik}")
        return "\n".join(lines)


ai_generation_service = AIGenerationService()
