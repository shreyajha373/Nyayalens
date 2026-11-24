"""Google Cloud Translation adapter for NyayaLens clause translations."""

from __future__ import annotations

import os
from functools import lru_cache

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError, GoogleAuthError
from google.cloud import translate_v3


SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

PROVIDER_NAME = "Google Cloud Translation Advanced v3"
MODEL_ID = "general/nmt"
MAX_REQUEST_CHARS = 20_000  # Google v3 allows at most 30,000 code points.
MAX_SEGMENT_CHARS = 5_000  # Smaller segments keep synchronous calls responsive.
MAX_CONTENTS_PER_REQUEST = 900  # The API accepts at most 1,024 contents.
MAX_CONFIGURABLE_CHARS = 200_000


class TranslationConfigurationError(Exception):
    """Provider configuration or credentials are unavailable."""


class TranslationLimitError(Exception):
    """The source text exceeds the configured per-analysis cost limit."""


class TranslationProviderError(Exception):
    """The translation service did not return a usable translation."""


def get_translation_settings() -> tuple[str, str, str]:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID", "").strip()
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip() or "global"
    model_id = os.getenv("GOOGLE_TRANSLATE_MODEL", MODEL_ID).strip() or MODEL_ID

    if not project_id:
        raise TranslationConfigurationError(
            "Set GOOGLE_CLOUD_PROJECT_ID in the backend .env file."
        )
    if model_id != MODEL_ID:
        raise TranslationConfigurationError(
            "GOOGLE_TRANSLATE_MODEL must be general/nmt in this version."
        )

    return project_id, location, model_id


def translation_character_limit() -> int:
    raw_limit = os.getenv("NYAYALENS_TRANSLATION_MAX_CHARS", "100000")
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise TranslationConfigurationError(
            "NYAYALENS_TRANSLATION_MAX_CHARS must be a whole number."
        ) from exc
    if not 1_000 <= limit <= MAX_CONFIGURABLE_CHARS:
        raise TranslationConfigurationError(
            "NYAYALENS_TRANSLATION_MAX_CHARS must be between 1000 and 200000."
        )
    return limit


@lru_cache(maxsize=1)
def _translation_client() -> translate_v3.TranslationServiceClient:
    # The client uses Google Application Default Credentials (ADC). Credentials
    # are supplied by the local gcloud login or the deployed workload identity.
    return translate_v3.TranslationServiceClient()


def _split_text(text: str) -> list[str]:
    """Split long clause fields at paragraph or word boundaries."""
    remaining = text.strip()
    chunks: list[str] = []

    while len(remaining) > MAX_SEGMENT_CHARS:
        window = remaining[:MAX_SEGMENT_CHARS]
        split_at = max(
            window.rfind("\n\n"),
            window.rfind("\n"),
            window.rfind(" "),
        )
        if split_at < MAX_SEGMENT_CHARS // 2:
            split_at = MAX_SEGMENT_CHARS

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


def translate_clauses(
    clauses: list[dict],
    target_language: str,
    source_language: str | None = None,
) -> dict:
    """Translate only source headings and source clause text, preserving order."""
    project_id, location, model_id = get_translation_settings()
    max_chars = translation_character_limit()

    source_character_count = sum(
        len(str(clause.get(field, "") or ""))
        for clause in clauses
        if isinstance(clause, dict)
        for field in ("heading", "text")
    )
    if source_character_count > max_chars:
        raise TranslationLimitError(
            f"This analysis has {source_character_count:,} translatable characters; "
            f"the configured limit is {max_chars:,}."
        )

    translated_parts: list[dict[str, list[str]]] = [
        {"heading": [], "text": []} for _ in clauses
    ]
    pending: list[tuple[int, str, str]] = []

    for index, clause in enumerate(clauses):
        if not isinstance(clause, dict):
            continue
        for field in ("heading", "text"):
            value = str(clause.get(field, "") or "")
            for chunk in _split_text(value):
                pending.append((index, field, chunk))

    parent = f"projects/{project_id}/locations/{location}"
    model = f"{parent}/models/{model_id}"
    detected_languages: set[str] = set()

    batches: list[list[tuple[int, str, str]]] = []
    current_batch: list[tuple[int, str, str]] = []
    current_chars = 0
    for item in pending:
        chunk_chars = len(item[2])
        if current_batch and (
            current_chars + chunk_chars > MAX_REQUEST_CHARS
            or len(current_batch) >= MAX_CONTENTS_PER_REQUEST
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(item)
        current_chars += chunk_chars
    if current_batch:
        batches.append(current_batch)

    try:
        client = _translation_client()
        for batch in batches:
            request = {
                "parent": parent,
                "contents": [item[2] for item in batch],
                "mime_type": "text/plain",
                "target_language_code": target_language,
                "model": model,
            }
            if source_language:
                request["source_language_code"] = source_language

            response = client.translate_text(request=request)
            if len(response.translations) != len(batch):
                raise TranslationProviderError(
                    "The translation provider returned an incomplete response."
                )

            for item, translation in zip(batch, response.translations):
                translated_parts[item[0]][item[1]].append(
                    translation.translated_text or ""
                )
                detected = getattr(translation, "detected_language_code", "")
                if detected:
                    detected_languages.add(detected)
    except DefaultCredentialsError as exc:
        raise TranslationConfigurationError(
            "Google Cloud credentials are unavailable. Configure Application Default Credentials."
        ) from exc
    except GoogleAuthError as exc:
        raise TranslationConfigurationError(
            "Google Cloud authentication failed. Check the configured account and IAM access."
        ) from exc
    except GoogleAPICallError as exc:
        raise TranslationProviderError(
            "Google Cloud Translation could not complete this request. Check API, billing, quotas, and language settings."
        ) from exc

    translated_clauses = []
    for index, clause in enumerate(clauses):
        original = clause if isinstance(clause, dict) else {}
        pieces = translated_parts[index]
        translated_clauses.append(
            {
                "clause_number": original.get("clause_number", index + 1),
                "translated_heading": "\n".join(pieces["heading"]),
                "translated_text": "\n".join(pieces["text"]),
            }
        )

    return {
        "provider": PROVIDER_NAME,
        "model": model_id,
        "source_character_count": source_character_count,
        "detected_source_languages": sorted(detected_languages),
        "translated_clauses": translated_clauses,
    }
