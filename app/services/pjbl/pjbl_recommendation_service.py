from __future__ import annotations

import json
from typing import Any

from app.schemas.recommendation_schema import (
    RecommendStageRequest,
    RecommendStageResponse,
)
from app.services.llm_client import LLMClient
from app.services.pjbl.pjbl_prompt_templates import (
    get_pjbl_recommendation_system_prompt,
)
from fastapi import HTTPException, status

MIN_PJBL_SUBJECTS = 3
MAX_PJBL_SUBJECTS = 5


class PjblRecommendationService:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.llm_client = llm_client or LLMClient()

    async def recommend(self, payload: RecommendStageRequest) -> RecommendStageResponse:
        target_stage = payload.targetStage
        selected_theme = self._selected_theme(payload)
        recommendation_type = self._recommendation_type(payload, selected_theme)
        target_stage_number = target_stage.get("stageNumber")
        references = []
        stage_context = self._flatten_stage_context(
            next(
                (
                    stage.contentJson
                    for stage in payload.previousStages
                    if stage.stageNumber == 1
                ),
                {},
            )
        )
        subjects = self._subjects(payload, stage_context)
        environment_context = self._environment_context(
            payload,
            stage_context,
            subjects,
        )
        required_response_shape = self._required_response_shape(recommendation_type)
        project_input = payload.project.model_dump()
        if subjects and self._is_generic_subject(project_input.get("subject")):
            project_input["resolvedSubject"] = ", ".join(subjects)
        llm_input = {
            "project": project_input,
            "subjectContext": {
                "mainSubjects": subjects,
                "subjectLens": ", ".join(subjects) if subjects else "",
                "instruction": (
                    "Tema dan opsi wajib selaras dengan mainSubjects. Abaikan kategori "
                    "tempat mentah yang hanya cocok untuk mata pelajaran lain."
                ),
            },
            "teacherProfile": (
                payload.teacherProfile.model_dump() if payload.teacherProfile else {}
            ),
            "school": payload.school.model_dump() if payload.school else {},
            "teacherClass": (
                payload.teacherClass.model_dump() if payload.teacherClass else {}
            ),
            "previousStages": [stage.model_dump() for stage in payload.previousStages],
            "targetStage": target_stage,
            "selectedTheme": selected_theme,
            "environmentContext": environment_context,
            "ragReferences": [reference.model_dump() for reference in references],
            "requiredResponseShape": required_response_shape,
        }
        system_prompt = get_pjbl_recommendation_system_prompt(recommendation_type)
        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(llm_input, ensure_ascii=False),
            },
        ]
        # logger.debug(
        #     "[PjBL Recommend] LLM input (%s):\n%s",
        #     recommendation_type,
        #     json.dumps(llm_input, ensure_ascii=False, indent=2, default=str),
        # )
        try:
            generated = await self.llm_client.generate_json_strict(
                messages,
                model=self._recommendation_model(),
                temperature=0.7,
            )
            print("Generated LLM output :", generated)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ada error pada output LLM. JSON rekomendasi tidak valid.",
            ) from exc
        except Exception as exc:
            # logger.warning(
            #     "[PjBL Recommend] LLM error (%s): %s",
            #     recommendation_type,
            #     exc,
            # )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ada error saat memanggil LLM. Rekomendasi belum dapat dibuat.",
            ) from exc
        # logger.debug(
        #     "[PjBL Recommend] LLM raw output (%s):\n%s",
        #     recommendation_type,
        #     json.dumps(generated, ensure_ascii=False, indent=2, default=str),
        # )
        try:
            recommendations = self._normalize_recommendations(
                generated,
                recommendation_type,
            )
            self._assert_llm_output_valid(recommendations, recommendation_type)
        except HTTPException as exc:
            print("\n=== PJBL VALIDATION ERROR ===")
            print(exc.detail)
            print("Generated output:")
            print(json.dumps(generated, ensure_ascii=False, indent=2, default=str))
            print("=============================\n")
            raise
        # logger.debug(
        #     "[PjBL Recommend] API normalized output (%s):\n%s",
        #     recommendation_type,
        #     json.dumps(recommendations, ensure_ascii=False, indent=2, default=str),
        # )
        print("Normalized recommendations :", recommendations)
        return RecommendStageResponse(
            rppType=payload.project.rppType,
            recommendationType=recommendation_type,
            targetStageNumber=(
                int(target_stage_number) if target_stage_number is not None else None
            ),
            ragReferences=references,
            recommendations=recommendations,
        )

    def _recommendation_model(self) -> str:
        settings = self.llm_client.settings
        return (
            settings.pjbl_recommendation_model
            or settings.kina_solver_model
            or settings.kina_llm_model
            or settings.llm_model
        )

    def _recommendation_type(
        self,
        payload: RecommendStageRequest,
        selected_theme: Any,
    ) -> str:
        requested_type = self._first_text(
            (
                payload.targetStage.get("recommendationType")
                if isinstance(payload.targetStage, dict)
                else None
            ),
            (
                payload.options.get("recommendationType")
                if isinstance(payload.options, dict)
                else None
            ),
            "",
        )
        allowed_types = {
            "project_theme_recommendation",
            "project_recommendation",
        }
        if requested_type:
            if requested_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "recommendationType PjBL tidak didukung: " f"{requested_type}"
                    ),
                )
            if requested_type == "project_recommendation" and not selected_theme:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "selectedTheme wajib dikirim untuk recommendationType "
                        "project_recommendation."
                    ),
                )
            return requested_type

        return (
            "project_recommendation"
            if selected_theme
            else "project_theme_recommendation"
        )

    def _required_response_shape(self, recommendation_type: str) -> dict[str, Any]:
        if recommendation_type == "project_theme_recommendation":
            return {
                "projectThemes": [
                    {"label": ""},
                    {"label": ""},
                    {"label": ""},
                ]
            }
        return {
            "projectOptions": [
                {
                    "id": "",
                    "title": "",
                    "themeId": "",
                    "themeLabel": "",
                    "description": "",
                    "lens": "",
                    "overview": "",
                    "confirmationTags": [{"id": "", "label": ""}],
                    "clarificationQuestions": [{"id": "", "label": ""}],
                }
            ],
        }

    def _assert_llm_output_valid(
        self,
        generated: dict[str, Any],
        recommendation_type: str,
    ) -> None:
        if recommendation_type == "project_theme_recommendation":
            themes = generated.get("projectThemes")
            if not isinstance(themes, list) or len(themes) != 3:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. projectThemes harus berisi "
                        "tepat 3 tema."
                    ),
                )
            for theme in themes:
                if not isinstance(theme, dict):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "Ada error pada output LLM. Setiap tema harus object "
                            "dengan field label."
                        ),
                    )
                extra_theme_keys = [key for key in theme.keys() if str(key) != "label"]
                if extra_theme_keys:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "Ada error pada output LLM. Tema hanya boleh memiliki "
                            "field label."
                        ),
                    )
                if not self._first_text(theme.get("label"), ""):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "Ada error pada output LLM. Setiap tema wajib memiliki label."
                        ),
                    )
            return

        options = generated.get("projectOptions")
        if not isinstance(options, list) or len(options) != 3:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Ada error pada output LLM. projectOptions harus berisi "
                    "tepat 3 opsi proyek."
                ),
            )

        required_text_fields = (
            "id",
            "title",
            "themeId",
            "themeLabel",
            "description",
            "lens",
            "overview",
        )
        for option in options:
            if not isinstance(option, dict):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Ada error pada output LLM. Setiap opsi proyek harus object.",
                )
            missing_text = [
                field
                for field in required_text_fields
                if not self._first_text(option.get(field), "")
            ]
            if missing_text:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. Field opsi proyek belum lengkap: "
                        + ", ".join(missing_text)
                    ),
                )
            if not isinstance(option.get("confirmationTags"), list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. confirmationTags harus berupa list."
                    ),
                )
            self._assert_confirmation_tags_valid(option["confirmationTags"])
            if not isinstance(option.get("clarificationQuestions"), list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. clarificationQuestions harus berupa list."
                    ),
                )
            self._assert_clarification_questions_valid(option["clarificationQuestions"])



    def _assert_confirmation_tags_valid(self, tags: list[Any]) -> None:
        if not 0 <= len(tags) <= 5:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Ada error pada output LLM. confirmationTags harus berisi "
                    "0-5 item."
                ),
            )
        for tag in tags:
            if not isinstance(tag, dict):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. Setiap confirmationTag harus object."
                    ),
                )
            missing = [
                field
                for field in ("id", "label")
                if not self._first_text(tag.get(field), "")
            ]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. Field confirmationTag belum lengkap: "
                        + ", ".join(missing)
                    ),
                )

    def _assert_clarification_questions_valid(self, questions: list[Any]) -> None:
        if not 0 <= len(questions) <= 5:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Ada error pada output LLM. clarificationQuestions harus berisi "
                    "0-5 item."
                ),
            )
        required_fields = ("id", "label")
        for question in questions:
            if not isinstance(question, dict):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. Setiap clarificationQuestion "
                        "harus object."
                    ),
                )
            missing = [
                field
                for field in required_fields
                if not self._first_text(question.get(field), "")
            ]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. Field clarificationQuestion "
                        "belum lengkap: " + ", ".join(missing)
                    ),
                )

    def _normalize_recommendations(
        self,
        generated: dict[str, Any],
        recommendation_type: str,
    ) -> dict[str, Any]:
        if not isinstance(generated, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ada error pada output LLM. Respons rekomendasi harus JSON object.",
            )

        if recommendation_type == "project_theme_recommendation":
            return {
                "projectThemes": generated.get("projectThemes"),
            }

        options = generated.get("projectOptions")

        return {
            "projectOptions": options if isinstance(options, list) else [],
        }

    def _assert_allowed_top_level_keys(
        self,
        generated: dict[str, Any],
        recommendation_type: str,
    ) -> None:
        allowed_keys = (
            {"projectThemes"}
            if recommendation_type == "project_theme_recommendation"
            else {"projectOptions"}
        )
        extra_keys = [str(key) for key in generated if key not in allowed_keys]
        if extra_keys:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Ada error pada output LLM. Key tidak sesuai kontrak "
                    f"{recommendation_type}: {', '.join(extra_keys)}."
                ),
            )

    def _has_rigid_project_option_pattern(self, options: list[dict[str, Any]]) -> bool:
        if len(options) < 3:
            return False
        title_prefixes = [
            self._first_text(option.get("title"), "").casefold()
            for option in options[:3]
        ]
        rigid_sets = (
            ("pemetaan", "kampanye", "audit"),
            ("analisis", "kampanye", "audit"),
            ("pemetaan", "proyek kampanye", "audit"),
        )
        for rigid_set in rigid_sets:
            if all(
                title_prefixes[index].startswith(prefix)
                for index, prefix in enumerate(rigid_set)
            ):
                return True
        formulaic_starters = (
            "festival mini",
            "rancang layanan",
            "dokumenter pendek",
            "jejak waktu",
            "tur narasi",
            "prototipe solusi",
            "panduan praktik",
            "simulasi keputusan",
            "eksperimen lapangan",
            "galeri cerita",
        )
        formulaic_count = sum(
            1
            for title in title_prefixes
            if any(title.startswith(starter) for starter in formulaic_starters)
        )
        if formulaic_count >= 2:
            return True
        return False

    def _environment_context(
        self,
        payload: RecommendStageRequest,
        stage_context: dict[str, Any],
        subjects: list[str] | None = None,
    ) -> dict[str, Any]:
        sources: list[Any] = []
        if isinstance(payload.placesContext, dict):
            sources.append(payload.placesContext)
            payload_value = payload.placesContext.get("payload")
            if isinstance(payload_value, dict):
                sources.append(payload_value)
        scanner_context = stage_context.get("environmentScanner")
        if isinstance(scanner_context, dict):
            sources.append(scanner_context)

        summary = ""
        places: list[dict[str, Any]] = []
        category_groups: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        radius_meters: Any = None
        source_name = ""
        fetched_at = ""

        for source in sources:
            if not isinstance(source, dict):
                continue
            summary = self._first_text(summary, source.get("summary"))
            radius_meters = radius_meters or source.get("radiusMeters")
            source_name = self._first_text(source_name, source.get("source"))
            fetched_at = self._first_text(fetched_at, source.get("fetchedAt"))
            raw_places = source.get("places")
            if isinstance(raw_places, list) and not places:
                places = [
                    {
                        "name": (
                            self._first_text(place.get("name"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "categoryId": (
                            self._first_text(place.get("categoryId"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "category": (
                            self._first_text(place.get("category"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "distanceLabel": (
                            self._first_text(place.get("distanceLabel"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "relevanceNote": (
                            self._first_text(place.get("relevanceNote"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                    }
                    for place in raw_places[:6]
                    if isinstance(place, dict)
                    and self._first_text(place.get("name"), "")
                ]
            raw_category_groups = source.get("categoryGroups")
            if isinstance(raw_category_groups, list) and not category_groups:
                category_groups = [
                    {
                        "id": (
                            self._first_text(group.get("id"), "")
                            if isinstance(group, dict)
                            else ""
                        ),
                        "label": (
                            self._first_text(group.get("label"), "")
                            if isinstance(group, dict)
                            else ""
                        ),
                        "description": (
                            self._first_text(group.get("description"), "")
                            if isinstance(group, dict)
                            else ""
                        ),
                        "learningUses": (
                            group.get("learningUses", [])
                            if isinstance(group, dict)
                            and isinstance(group.get("learningUses"), list)
                            else []
                        ),
                        "places": (
                            [
                                {
                                    "name": self._first_text(place.get("name"), ""),
                                    "categoryId": self._first_text(
                                        place.get("categoryId"), ""
                                    ),
                                    "category": self._first_text(
                                        place.get("category"), ""
                                    ),
                                    "distanceLabel": self._first_text(
                                        place.get("distanceLabel"), ""
                                    ),
                                    "relevanceNote": self._first_text(
                                        place.get("relevanceNote"), ""
                                    ),
                                }
                                for place in group.get("places", [])[:4]
                                if isinstance(place, dict)
                                and self._first_text(place.get("name"), "")
                            ]
                            if isinstance(group, dict)
                            and isinstance(group.get("places"), list)
                            else []
                        ),
                        "subjectFitScore": (
                            self._subject_fit_score(group, subjects or [])
                            if isinstance(group, dict)
                            else 0
                        ),
                    }
                    for group in raw_category_groups[:6]
                    if isinstance(group, dict)
                    and self._first_text(group.get("label"), "")
                ]
            raw_risks = source.get("risks")
            if isinstance(raw_risks, list) and not risks:
                risks = [
                    {
                        "title": (
                            self._first_text(risk.get("title"), "")
                            if isinstance(risk, dict)
                            else ""
                        ),
                        "level": (
                            self._first_text(risk.get("level"), "")
                            if isinstance(risk, dict)
                            else ""
                        ),
                        "description": (
                            self._first_text(risk.get("description"), "")
                            if isinstance(risk, dict)
                            else ""
                        ),
                    }
                    for risk in raw_risks[:3]
                    if isinstance(risk, dict)
                    and self._first_text(risk.get("title"), "")
                ]

        category_groups, places, omitted_labels = self._filter_environment_context(
            category_groups,
            places,
            subjects or [],
        )
        return {
            "summary": summary,
            "categoryGroups": category_groups,
            "places": places,
            "risks": risks,
            "radiusMeters": radius_meters,
            "source": source_name,
            "fetchedAt": fetched_at,
            "subjectAlignment": {
                "mainSubjects": subjects or [],
                "includedCategoryLabels": [
                    self._first_text(group.get("label"), "")
                    for group in category_groups
                    if isinstance(group, dict)
                    and self._first_text(group.get("label"), "")
                ],
                "omittedCategoryLabels": omitted_labels,
            },
        }

    def _filter_environment_context(
        self,
        category_groups: list[dict[str, Any]],
        places: list[dict[str, Any]],
        subjects: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        if not subjects:
            return category_groups, places, []

        scored_groups: list[tuple[int, dict[str, Any]]] = [
            (self._subject_fit_score(group, subjects), group)
            for group in category_groups
        ]
        has_aligned_group = any(score > 0 for score, _group in scored_groups)
        omitted_labels: list[str] = []
        if has_aligned_group:
            filtered_groups = [
                dict(group, subjectFitScore=score)
                for score, group in sorted(
                    scored_groups,
                    key=lambda item: (
                        -item[0],
                        self._first_text(item[1].get("label"), ""),
                    ),
                )
                if score > 0
            ]
            omitted_labels = [
                self._first_text(group.get("label"), "")
                for score, group in scored_groups
                if score <= 0 and self._first_text(group.get("label"), "")
            ]
        else:
            filtered_groups = category_groups

        scored_places = [
            (self._subject_fit_score(place, subjects), place) for place in places
        ]
        has_aligned_place = any(score > 0 for score, _place in scored_places)
        if has_aligned_place:
            filtered_places = [
                dict(place, subjectFitScore=score)
                for score, place in sorted(
                    scored_places,
                    key=lambda item: (
                        -item[0],
                        self._first_text(item[1].get("distanceLabel"), ""),
                    ),
                )
                if score > 0
            ]
        else:
            filtered_places = places

        return filtered_groups[:6], filtered_places[:6], omitted_labels[:6]

    def _subject_fit_score(self, value: Any, subjects: list[str]) -> int:
        if not subjects:
            return 0
        text = self._searchable_context_text(value).casefold()
        if isinstance(value, dict):
            text = " ".join(
                [
                    text,
                    self._first_text(value.get("id"), ""),
                    self._first_text(value.get("categoryId"), ""),
                    self._first_text(value.get("category"), ""),
                    self._first_text(value.get("label"), ""),
                    self._summarize_context_value(value.get("learningUses")),
                    self._summarize_context_value(value.get("places")),
                ]
            ).casefold()
        focus_terms = self._subject_focus_terms(subjects)
        score = sum(3 for term in focus_terms if term in text)
        score += sum(1 for subject in subjects if subject.casefold() in text)
        return score

    def _subject_focus_terms(self, subjects: list[str]) -> list[str]:
        subject_text = " ".join(subjects).casefold()
        terms: list[str] = []
        if any(keyword in subject_text for keyword in ("matematika", "statistika")):
            terms.extend(
                [
                    "data",
                    "harga",
                    "jarak",
                    "ukur",
                    "survei",
                    "statistik",
                    "grafik",
                    "diagram",
                    "tabel",
                    "perbandingan",
                    "persentase",
                    "biaya",
                    "keputusan",
                ]
            )
        if any(
            keyword in subject_text for keyword in ("ekonomi", "bisnis", "wirausaha")
        ):
            terms.extend(
                [
                    "ekonomi",
                    "umkm",
                    "usaha",
                    "jual",
                    "beli",
                    "pasar",
                    "harga",
                    "biaya",
                    "transaksi",
                    "kebutuhan",
                    "pembeli",
                    "pengunjung",
                    "keputusan",
                ]
            )
        if any(
            keyword in subject_text for keyword in ("ipa", "biologi", "kimia", "fisika")
        ):
            terms.extend(["sains", "ipa", "kesehatan", "air", "tanaman", "cuaca"])
        if any(keyword in subject_text for keyword in ("sejarah", "seni", "budaya")):
            terms.extend(["budaya", "sejarah", "tradisi", "karya", "visual"])
        if any(keyword in subject_text for keyword in ("ppkn", "pkn", "sosiologi")):
            terms.extend(["warga", "sosial", "layanan", "kesehatan", "publik"])
        return list(dict.fromkeys(term for term in terms if term))

    def _selected_theme(self, payload: RecommendStageRequest) -> Any:
        target_stage = payload.targetStage or {}
        options = payload.options or {}
        return (
            target_stage.get("selectedTheme")
            or target_stage.get("selectedThemeId")
            or target_stage.get("selectedProjectTheme")
            or target_stage.get("projectTheme")
            or options.get("selectedTheme")
            or options.get("selectedThemeId")
            or options.get("selectedProjectTheme")
            or options.get("projectTheme")
        )

    def _flatten_stage_context(self, stage_one: Any) -> dict[str, Any]:
        if not isinstance(stage_one, dict):
            return {}
        merged: dict[str, Any] = {}
        for key in ("inputs", "spec", "mission"):
            value = stage_one.get(key)
            if isinstance(value, dict):
                merged.update(value)
        wizard = stage_one.get("wizard")
        if isinstance(wizard, dict):
            konteks = wizard.get("konteks")
            if isinstance(konteks, dict):
                for key in ("spec", "mission"):
                    value = konteks.get(key)
                    if isinstance(value, dict):
                        merged.update(value)
                environment_scanner = konteks.get("environmentScanner")
                if isinstance(environment_scanner, dict):
                    merged.setdefault("environmentScanner", environment_scanner)
                    merged.setdefault(
                        "localContext",
                        self._summarize_context_value(environment_scanner),
                    )
                    merged.setdefault(
                        "localIssue",
                        self._summarize_context_value(environment_scanner),
                    )
        merged.update(
            {
                key: value
                for key, value in stage_one.items()
                if key not in {"inputs", "spec", "mission", "wizard"}
            }
        )
        self._merge_stage_one_sections(merged, stage_one)
        return merged

    def _merge_stage_one_sections(
        self,
        merged: dict[str, Any],
        stage_one: dict[str, Any],
    ) -> None:
        school_info = self._first_section(
            stage_one,
            "schoolInformation",
            "informasiSekolah",
        )
        environment_scanner = self._first_section(
            stage_one,
            "environmentScanner",
            "pemindaiLingkungan",
        )
        risk_monitoring = self._first_section(
            stage_one,
            "riskMonitoring",
            "pemantauanRisiko",
        )
        mission_spec = self._first_section(
            stage_one,
            "missionSpec",
            "spesifikasiMisi",
        )

        if school_info:
            merged.setdefault(
                "schoolName",
                self._first_text(
                    school_info.get("schoolName"),
                    school_info.get("namaSekolah"),
                    school_info.get("name"),
                ),
            )
            merged.setdefault(
                "schoolAddress",
                self._first_text(
                    school_info.get("address"),
                    school_info.get("alamat"),
                ),
            )

        environment_summary = self._summarize_context_value(environment_scanner)
        if environment_summary:
            merged.setdefault("localContext", environment_summary)
            merged.setdefault("localIssue", environment_summary)

        risk_summary = self._summarize_context_value(risk_monitoring)
        if risk_summary:
            merged.setdefault("riskNotes", risk_summary)
            merged.setdefault("implementationConstraints", risk_summary)

        if mission_spec:
            merged.setdefault(
                "mainSubjects",
                mission_spec.get("relatedSubjects")
                or mission_spec.get("muatanMataPelajaranTerkait")
                or mission_spec.get("mataPelajaranTerkait"),
            )
            merged.setdefault(
                "fase",
                self._first_text(
                    mission_spec.get("educationPhase"),
                    mission_spec.get("fasePendidikan"),
                    mission_spec.get("fase"),
                ),
            )
            merged.setdefault(
                "educationLevel",
                self._first_text(
                    mission_spec.get("educationLevel"),
                    mission_spec.get("jenjangPendidikan"),
                    mission_spec.get("jenjang"),
                ),
            )
            merged.setdefault(
                "projectDuration",
                self._summarize_context_value(
                    mission_spec.get("learningDuration")
                    or mission_spec.get("durasiPembelajaran")
                ),
            )
            merged.setdefault(
                "kondisiKelas",
                self._summarize_context_value(
                    mission_spec.get("classCondition")
                    or mission_spec.get("kondisiKelas")
                ),
            )

    def _first_section(self, data: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _searchable_context_text(self, value: Any, depth: int = 0) -> str:
        if depth > 4:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return " ".join(
                self._searchable_context_text(item, depth + 1) for item in value[:10]
            )
        if isinstance(value, dict):
            parts: list[str] = []
            for key, item in list(value.items())[:20]:
                parts.append(str(key))
                parts.append(self._searchable_context_text(item, depth + 1))
            return " ".join(part for part in parts if part)
        if value is not None:
            return str(value).strip()
        return ""

    def _summarize_context_value(self, value: Any) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            items = [self._summarize_context_value(item) for item in value[:6]]
            return "; ".join(item for item in items if item)
        if isinstance(value, dict):
            direct = self._first_text(
                value.get("summary"),
                value.get("description"),
                value.get("deskripsi"),
                value.get("localIssue"),
                value.get("context"),
                value.get("konteks"),
                value.get("name"),
                value.get("nama"),
                value.get("title"),
                value.get("judul"),
            )
            if direct:
                return direct
            parts = []
            for key, item in value.items():
                summary = self._summarize_context_value(item)
                if summary:
                    parts.append(f"{key}: {summary}")
                if len(parts) >= 6:
                    break
            return "; ".join(parts)
        if value is not None:
            return str(value).strip()
        return ""

    def _subjects(
        self,
        payload: RecommendStageRequest,
        stage_context: dict[str, Any],
    ) -> list[str]:
        subjects = self._string_list(stage_context.get("mainSubjects"))
        if not subjects:
            subjects = self._string_list(stage_context.get("collabSubjects"))
        project_subject = self._first_text(payload.project.subject, "")
        if not subjects and not self._is_generic_subject(project_subject):
            subjects = self._string_list(project_subject)
        return self._normalize_subject_count(subjects)

    def _normalize_subject_count(
        self,
        subjects: list[str],
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        def add(subject: Any) -> None:
            text = self._first_text(subject, "")
            if not text:
                return
            key = text.casefold()
            if key in seen:
                return
            seen.add(key)
            normalized.append(text)

        for subject in subjects:
            add(subject)

        normalized = normalized[:MAX_PJBL_SUBJECTS]
        if len(normalized) < MIN_PJBL_SUBJECTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Stage 1 harus memuat {MIN_PJBL_SUBJECTS}-"
                    f"{MAX_PJBL_SUBJECTS} mata pelajaran pilihan guru."
                ),
            )
        return normalized

    def _is_generic_subject(self, value: Any) -> bool:
        text = self._first_text(value, "").casefold()
        return not text or text in {
            "umum",
            "general",
            "lintas disiplin",
            "mata pelajaran terkait",
        }

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def _first_text(self, *values: Any) -> str:
        default = ""
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list, tuple, set)):
                text = str(value).strip()
                if text:
                    return text
        return default
