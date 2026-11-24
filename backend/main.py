
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import pymupdf
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import DESCENDING
from pymongo.errors import PyMongoError
from starlette.middleware.sessions import SessionMiddleware

from auth import (
    FRONTEND_URL,
    OAUTH_BASE_URL,
    SESSION_SECRET_KEY,
    get_current_user,
    router as auth_router,
)
from database import analyses_collection, analysis_translations_collection
from translation_service import (
    SUPPORTED_LANGUAGES,
    TranslationConfigurationError,
    TranslationLimitError,
    TranslationProviderError,
    translate_clauses,
)


# -----------------------------------------
# 1. FastAPI Application
# -----------------------------------------

app = FastAPI(
    title="NyayaLens API",
    description="Clause-wise Legal Document Analyzer",
    version="1.3.0"
)

app.include_router(auth_router)

# Authlib stores OAuth state and OIDC nonce in a signed, short-lived cookie.
# Email/password routes remain available if OAuth has not been configured yet.
if SESSION_SECRET_KEY:
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET_KEY,
        max_age=600,
        same_site="lax",
        https_only=OAUTH_BASE_URL.startswith("https://"),
    )


# -----------------------------------------
# 2. CORS Configuration
# -----------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# -----------------------------------------
# 3. Clause Detection
# -----------------------------------------

def split_into_clauses(text: str) -> list:
    lines = text.splitlines()

    clauses = []
    current_heading = "Introduction"
    current_text = []

    heading_pattern = re.compile(
        r"^\s*(?:(?:\d+(?:\.\d+)*[.)]?)|"
        r"(?:ARTICLE\s+[IVXLC\d]+)|"
        r"(?:SECTION\s+\d+))\s*[-:.)]?\s+.+$",
        re.IGNORECASE
    )

    def add_clause():
        if current_text:
            clauses.append({
                "heading": current_heading,
                "text": "\n".join(current_text).strip()
            })

    for line in lines:
        line = line.strip()

        if not line:
            continue

        if heading_pattern.match(line):
            add_clause()
            current_heading = line
            current_text = []
        else:
            current_text.append(line)

    add_clause()

    if not clauses and current_heading != "Introduction":
        clauses.append({
            "heading": current_heading,
            "text": current_heading
        })

    return clauses


# -----------------------------------------
# 4. Plain-English Clause Explanations
# -----------------------------------------

def simplify_clause(heading: str, text: str) -> str:
    content = f"{heading} {text}".lower()

    if any(phrase in content for phrase in [
        "automatically renew",
        "automatic renewal",
        "auto-renew"
    ]):
        return (
            "This agreement may renew automatically unless "
            "you cancel before the specified deadline."
        )

    if any(phrase in content for phrase in [
        "non-refundable",
        "no refunds",
        "not entitled to a refund"
    ]):
        return (
            "You may not receive your money back after payment. "
            "Check the original clause for exceptions."
        )

    if "without prior notice" in content:
        return (
            "The other party may take certain actions "
            "without informing you beforehand."
        )

    if any(phrase in content for phrase in [
        "indemnify",
        "hold harmless",
        "indemnification"
    ]):
        return (
            "One party may have to cover certain losses, "
            "expenses, or legal claims involving another party."
        )

    if (
        "arbitrator" in content
        and any(phrase in content for phrase in [
            "selected and paid by the provider",
            "no participation in the selection",
            "exclusively by an arbitrator selected"
        ])
    ):
        return (
            "Disputes may be decided by an arbitrator "
            "selected by the service provider."
        )

    if any(phrase in content for phrase in [
        "share customer data",
        "share personal information",
        "sell customer data",
        "third-party advertisers",
        "disclose customer information"
    ]):
        return (
            "The agreement may allow personal or customer "
            "information to be shared with other organizations."
        )

    if any(phrase in content for phrase in [
        "without providing any reason",
        "without cause",
        "at its sole discretion"
    ]):
        return (
            "One party may have broad power to end or change "
            "the agreement under the stated conditions."
        )

    if any(phrase in content for phrase in [
        "shall not be liable",
        "not responsible for any damages",
        "liability shall be limited",
        "limitation of liability"
    ]):
        return (
            "The agreement may limit the amount or type "
            "of compensation one party must pay."
        )

    return (
        "This section describes terms or responsibilities "
        "under the agreement. Read the original wording "
        "carefully for the specific conditions."
    )


# -----------------------------------------
# 5. Rule-Based Risk Analysis
# -----------------------------------------

def analyze_clause(text: str) -> dict:
    text_lower = text.lower()
    detected_concerns = []

    # High: Actions without advance notice
    if "without prior notice" in text_lower:
        detected_concerns.append({
            "risk_level": "High",
            "reason": (
                "This clause may allow action "
                "without advance notice."
            ),
            "suggestion": (
                "Review whether reasonable "
                "notice should be required."
            )
        })

    # High: Data sharing and privacy
    if any(phrase in text_lower for phrase in [
        "share customer data",
        "share personal information",
        "sell customer data",
        "third-party advertisers",
        "disclose customer information",
        "without obtaining separate consent"
    ]):
        detected_concerns.append({
            "risk_level": "High",
            "reason": (
                "This clause may permit broad sharing "
                "or commercial use of customer information."
            ),
            "suggestion": (
                "Review consent, data recipients, "
                "sharing purposes, and privacy protections."
            )
        })

    # High: One-sided termination rights
    if any(phrase in text_lower for phrase in [
        "without providing any reason",
        "without cause",
        "at its sole discretion"
    ]):
        detected_concerns.append({
            "risk_level": "High",
            "reason": (
                "This clause may grant one party "
                "broad discretionary rights."
            ),
            "suggestion": (
                "Review fairness, notice periods, "
                "and protections for both parties."
            )
        })

    # Medium: Indemnification
    if any(phrase in text_lower for phrase in [
        "indemnify",
        "hold harmless",
        "indemnification"
    ]):
        detected_concerns.append({
            "risk_level": "Medium",
            "reason": (
                "This clause may require one party "
                "to compensate another for losses "
                "or legal claims."
            ),
            "suggestion": (
                "Review indemnification scope, "
                "exclusions, and balanced obligations."
            )
        })

    # Medium: Limitation of liability
    if any(phrase in text_lower for phrase in [
        "shall not be liable",
        "not responsible for any damages",
        "liability shall be limited",
        "limitation of liability"
    ]):
        detected_concerns.append({
            "risk_level": "Medium",
            "reason": (
                "This clause may limit legal "
                "or financial responsibility."
            ),
            "suggestion": (
                "Review liability caps, exclusions, "
                "and whether limitations are reasonable."
            )
        })

    # Medium: Refund restrictions
    if any(phrase in text_lower for phrase in [
        "non-refundable",
        "no refunds",
        "not entitled to a refund"
    ]):
        detected_concerns.append({
            "risk_level": "Medium",
            "reason": (
                "This clause may restrict "
                "refund eligibility."
            ),
            "suggestion": (
                "Review refund conditions, "
                "exceptions, and cancellation terms."
            )
        })

    # Medium: Automatic renewal
    if any(phrase in text_lower for phrase in [
        "automatically renew",
        "automatic renewal",
        "auto-renew"
    ]):
        detected_concerns.append({
            "risk_level": "Medium",
            "reason": (
                "This clause contains an "
                "automatic renewal provision."
            ),
            "suggestion": (
                "Review renewal periods, "
                "cancellation deadlines, and notice."
            )
        })

    # High: One-sided dispute resolution
    arbitration_terms = [
        "arbitrator",
        "arbitration",
        "dispute resolution"
    ]

    one_sided_terms = [
        "selected and paid by the provider",
        "no participation in the selection",
        "sole discretion",
        "exclusively by an arbitrator selected"
    ]

    if (
        any(term in text_lower for term in arbitration_terms)
        and any(term in text_lower for term in one_sided_terms)
    ):
        detected_concerns.append({
            "risk_level": "High",
            "reason": (
                "This clause may give one party "
                "unfair control over dispute resolution."
            ),
            "suggestion": (
                "Review whether both parties have "
                "a fair opportunity to participate "
                "in selecting an independent arbitrator."
            )
        })

    # No predefined concern matched
    if not detected_concerns:
        return {
            "risk_level": "Low",
            "reason": "No predefined concern was detected.",
            "suggestion": (
                "Review this clause in the context "
                "of the complete agreement."
            ),
            "detected_concerns": []
        }

    # Highest detected risk takes priority
    risk_priority = {
        "Low": 1,
        "Medium": 2,
        "High": 3
    }

    highest_concern = max(
        detected_concerns,
        key=lambda concern: risk_priority[
            concern["risk_level"]
        ]
    )

    return {
        "risk_level": highest_concern["risk_level"],
        "reason": highest_concern["reason"],
        "suggestion": highest_concern["suggestion"],
        "detected_concerns": detected_concerns
    }


# -----------------------------------------
# 6. Home Endpoint
# -----------------------------------------

@app.get("/")
async def home():
    return {
        "message": "NyayaLens backend is running"
    }


# -----------------------------------------
# 7. Document Upload and Analysis
# -----------------------------------------

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_PAGE_PREVIEWS = 20
PAGE_PREVIEW_CHARS = 240
DEMO_ANALYSIS_ENABLED = os.getenv(
    "NYAYALENS_ENABLE_DEMO_ANALYSIS", "true"
).strip().lower() in {"1", "true", "yes", "on"}


class TranslationRequest(BaseModel):
    target_language: str
    source_language: str | None = None


def authenticated_user_id(user: dict) -> str:
    user_id = user.get("_id")
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Your account could not be identified. Please sign in again.",
        )
    return str(user_id)


def serialize_analysis(record: dict) -> dict:
    result = dict(record)
    result["analysis_id"] = str(result.pop("_id"))
    result.pop("user_id", None)

    created_at = result.get("created_at")
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        result["created_at"] = created_at.astimezone(timezone.utc).isoformat()

    return result


def serialize_translation(record: dict) -> dict:
    result = dict(record)
    result["translation_id"] = str(result.pop("_id"))
    result.pop("user_id", None)

    created_at = result.get("created_at")
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        result["created_at"] = created_at.astimezone(timezone.utc).isoformat()

    return result


def find_owned_analysis(analysis_id: str, user_id: str) -> dict:
    try:
        object_id = ObjectId(analysis_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Analysis not found.")

    try:
        record = analyses_collection.find_one(
            {"_id": object_id, "user_id": user_id}
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not load this analysis. Please try again.",
        ) from exc

    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return record


def translation_cache_id(
    user_id: str,
    analysis_id: str,
    source_language: str | None,
    target_language: str,
    clauses: list[dict],
) -> str:
    source_snapshot = [
        {
            "heading": str(clause.get("heading", "") or ""),
            "text": str(clause.get("text", "") or ""),
        }
        for clause in clauses
        if isinstance(clause, dict)
    ]
    canonical_source = json.dumps(
        source_snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    source_fingerprint = hashlib.sha256(
        canonical_source.encode("utf-8")
    ).hexdigest()
    cache_material = "|".join(
        [
            user_id,
            analysis_id,
            source_language or "auto",
            target_language,
            source_fingerprint,
        ]
    )
    return hashlib.sha256(cache_material.encode("utf-8")).hexdigest()


@app.get("/analyses", summary="List the signed-in user's analysis history")
def list_analyses(
    user: dict = Depends(get_current_user),
    limit: int = Query(default=25, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
):
    user_id = authenticated_user_id(user)
    query = {"user_id": user_id}

    try:
        total = analyses_collection.count_documents(query)
        records = (
            analyses_collection.find(
                query,
                {"clauses": 0, "text_preview": 0},
            )
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        items = [serialize_analysis(record) for record in records]
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not load analysis history. Please try again.",
        ) from exc

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "skip": skip,
    }


@app.get("/analyses/{analysis_id}", summary="Open one saved analysis")
def get_analysis(
    analysis_id: str,
    user: dict = Depends(get_current_user),
):
    try:
        object_id = ObjectId(analysis_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=404,
            detail="Analysis not found.",
        )

    query = {
        "_id": object_id,
        "user_id": authenticated_user_id(user),
    }

    try:
        record = analyses_collection.find_one(query)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not load this analysis. Please try again.",
        ) from exc

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found.",
        )

    return serialize_analysis(record)


@app.post(
    "/analyses/{analysis_id}/translations",
    summary="Translate saved source clauses into a supported language",
)
def create_analysis_translation(
    analysis_id: str,
    request: TranslationRequest,
    user: dict = Depends(get_current_user),
):
    target_language = request.target_language.strip().lower()
    source_language = (request.source_language or "").strip().lower() or None

    if target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail="Choose one of the nine supported target languages.",
        )
    if source_language and source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail="Choose a supported source language or leave it on auto-detect.",
        )
    if source_language == target_language:
        raise HTTPException(
            status_code=422,
            detail="Source and target languages must be different.",
        )

    user_id = authenticated_user_id(user)
    analysis = find_owned_analysis(analysis_id, user_id)
    clauses = analysis.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise HTTPException(
            status_code=422,
            detail="This saved analysis has no source clauses available to translate.",
        )

    cache_id = translation_cache_id(
        user_id,
        analysis_id,
        source_language,
        target_language,
        clauses,
    )
    try:
        cached = analysis_translations_collection.find_one(
            {"_id": cache_id, "user_id": user_id, "analysis_id": analysis_id}
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not check saved translations. Please try again.",
        ) from exc
    if cached:
        return serialize_translation(cached)

    try:
        translated = translate_clauses(
            clauses,
            target_language=target_language,
            source_language=source_language,
        )
    except TranslationLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except TranslationConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TranslationProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    created_at = datetime.now(timezone.utc)
    translation_record = {
        "_id": cache_id,
        "analysis_id": analysis_id,
        "user_id": user_id,
        "source_language": source_language or "auto",
        "target_language": target_language,
        "target_language_name": SUPPORTED_LANGUAGES[target_language],
        **translated,
        "created_at": created_at,
    }

    try:
        analysis_translations_collection.update_one(
            {"_id": cache_id},
            {
                "$setOnInsert": {
                    key: value
                    for key, value in translation_record.items()
                    if key != "_id"
                }
            },
            upsert=True,
        )
        saved_translation = analysis_translations_collection.find_one(
            {"_id": cache_id, "user_id": user_id, "analysis_id": analysis_id}
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="The translation completed, but could not be saved. Please try again.",
        ) from exc

    return serialize_translation(saved_translation or translation_record)


@app.get(
    "/analyses/{analysis_id}/translations/{target_language}",
    summary="Load a saved translation for one analysis",
)
def get_analysis_translation(
    analysis_id: str,
    target_language: str,
    user: dict = Depends(get_current_user),
):
    target_language = target_language.strip().lower()
    if target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail="Choose one of the nine supported target languages.",
        )

    user_id = authenticated_user_id(user)
    find_owned_analysis(analysis_id, user_id)
    try:
        record = analysis_translations_collection.find_one(
            {
                "user_id": user_id,
                "analysis_id": analysis_id,
                "target_language": target_language,
            },
            sort=[("created_at", DESCENDING)],
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not load this translation. Please try again.",
        ) from exc

    if not record:
        raise HTTPException(status_code=404, detail="No saved translation was found.")
    return serialize_translation(record)


async def analyze_document_file(file: UploadFile) -> dict:
    """Extract and analyze a file without deciding where its result is saved."""
    filename = file.filename or ""

    if not filename.lower().endswith((".pdf", ".txt")):
        raise HTTPException(
            status_code=400,
            detail="Choose a PDF or TXT file."
        )

    contents = await file.read(MAX_FILE_SIZE + 1)

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="The file must be smaller than 10 MB."
        )

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="The file is empty."
        )

    pdf_extraction = None
    try:
        if filename.lower().endswith(".pdf"):
            with pymupdf.open(
                stream=contents,
                filetype="pdf"
            ) as document:
                if document.is_encrypted and not document.authenticate(""):
                    raise HTTPException(
                        status_code=400,
                        detail="This PDF is password protected. Remove its password and upload it again.",
                    )

                page_texts = [
                    page.get_text("text", sort=True)
                    for page in document
                ]
                extracted_text = "\n\n".join(page_texts)
                pages_with_text = sum(bool(text.strip()) for text in page_texts)
                pdf_extraction = {
                    "page_count": len(page_texts),
                    "pages_with_text": pages_with_text,
                    "pages_without_text": len(page_texts) - pages_with_text,
                    "ocr_available": False,
                    "page_previews": [
                        {
                            "page_number": page_number,
                            "character_count": len(page_text),
                            "preview": page_text.strip()[:PAGE_PREVIEW_CHARS],
                        }
                        for page_number, page_text in enumerate(page_texts[:MAX_PAGE_PREVIEWS], start=1)
                    ],
                    "previews_truncated": len(page_texts) > MAX_PAGE_PREVIEWS,
                }
        else:
            extracted_text = contents.decode("utf-8-sig")

    except (
        pymupdf.FileDataError,
        RuntimeError,
        UnicodeDecodeError,
        ValueError
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The document could not be read. "
                "Use a valid PDF or UTF-8 TXT file."
            )
        )

    if not extracted_text.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "No readable text was found. "
                "Scanned PDFs may require OCR."
            )
        )

    # Split document into clauses
    clauses = split_into_clauses(extracted_text)

    risk_summary = {
        "Low": 0,
        "Medium": 0,
        "High": 0
    }

    for index, clause in enumerate(clauses, start=1):
        analysis = analyze_clause(clause["text"])

        # NEW: Plain-English explanation
        clause["simplified_text"] = simplify_clause(
            clause["heading"],
            clause["text"]
        )

        clause["clause_number"] = index
        clause["risk_level"] = analysis["risk_level"]
        clause["reason"] = analysis["reason"]
        clause["suggestion"] = analysis["suggestion"]
        clause["detected_concerns"] = (
            analysis["detected_concerns"]
        )

        risk_summary[analysis["risk_level"]] += 1

    created_at = datetime.now(timezone.utc)
    analysis_record = {
        "filename": filename,
        "character_count": len(extracted_text),
        "clause_count": len(clauses),
        "risk_summary": risk_summary,
        "clauses": clauses,
        "text_preview": extracted_text[:500],
        "analysis_method": "rule_based_v2",
        "created_at": created_at,
        "message": (
            "Text extracted, segmented, "
            "and screened successfully!"
        )
    }
    if pdf_extraction is not None:
        analysis_record["pdf_extraction"] = pdf_extraction

    return analysis_record


@app.post("/demo/analyze", summary="Analyze a file in the non-persistent demo workspace")
async def demo_analyze_document(file: UploadFile = File(...)):
    """Demo analyses are returned to the browser and are not written to MongoDB."""
    if not DEMO_ANALYSIS_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Sign in before uploading a document on this public website.",
        )
    analysis_record = await analyze_document_file(file)
    response = dict(analysis_record)
    response["created_at"] = analysis_record["created_at"].isoformat()
    return response


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    analysis_record = await analyze_document_file(file)
    analysis_record["user_id"] = authenticated_user_id(user)

    try:
        saved_analysis = analyses_collection.insert_one(analysis_record)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "The document was analyzed, but its history could not be saved. "
                "Please try again."
            ),
        ) from exc

    response = dict(analysis_record)
    response.pop("user_id", None)
    response["analysis_id"] = str(saved_analysis.inserted_id)
    response["created_at"] = analysis_record["created_at"].isoformat()
    return response
