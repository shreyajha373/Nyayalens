import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError, PyMongoError

from database import (
    EMAIL_COLLATION,
    ensure_session_indexes,
    ensure_oauth_handoff_indexes,
    ensure_oauth_identity_indexes,
    ensure_user_email_index,
    oauth_handoffs_collection,
    oauth_identities_collection,
    otp_collection,
    sessions_collection,
    users_collection,
)


load_dotenv()

AUTH_METHOD_PASSWORD_NO_OTP = "password_no_otp"
OTP_SECRET_KEY = os.getenv("OTP_SECRET_KEY", "")
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 30
OAUTH_BASE_URL = (
    os.getenv("OAUTH_BASE_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or "http://127.0.0.1:8000"
).rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "")

try:
    SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "60"))
except ValueError as exc:
    raise RuntimeError("SESSION_TTL_MINUTES must be a whole number") from exc
if not 5 <= SESSION_TTL_MINUTES <= 10_080:
    raise RuntimeError("SESSION_TTL_MINUTES must be between 5 and 10080")

router = APIRouter()
password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)
oauth = OAuth()
oauth.register(
    name="github",
    client_id=os.getenv("GITHUB_CLIENT_ID", ""),
    client_secret=os.getenv("GITHUB_CLIENT_SECRET", ""),
    authorize_url="https://github.com/login/oauth/authorize",
    access_token_url="https://github.com/login/oauth/access_token",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)
oauth.register(
    name="linkedin",
    client_id=os.getenv("LINKEDIN_CLIENT_ID", ""),
    client_secret=os.getenv("LINKEDIN_CLIENT_SECRET", ""),
    server_metadata_url="https://www.linkedin.com/oauth/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid profile email",
        "token_endpoint_auth_method": "client_secret_post",
    },
)


class UserSignup(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class EmailOTPVerify(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class EmailOTPResend(BaseModel):
    email: EmailStr


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class OAuthCodeExchange(BaseModel):
    code: str = Field(min_length=32, max_length=256)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_user_by_email(email: str, projection: dict | None = None) -> dict | None:
    return users_collection.find_one(
        {"email": normalize_email(email)},
        projection,
        collation=EMAIL_COLLATION,
    )


def user_can_sign_in(user: dict) -> bool:
    # Password-only signups deliberately keep is_verified=False. The explicit
    # auth_method distinguishes them from legacy accounts awaiting verification.
    return (
        user.get("is_verified") is True
        or user.get("auth_method") == AUTH_METHOD_PASSWORD_NO_OTP
    )


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not isinstance(hashed_password, str) or not hashed_password:
        return False
    try:
        return password_hash.verify(plain_password, hashed_password)
    except (TypeError, ValueError):
        return False


def _require_otp_secret() -> str:
    if not OTP_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Legacy email verification is unavailable until OTP_SECRET_KEY "
                "is configured in the backend .env file."
            ),
        )
    return OTP_SECRET_KEY


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(email: str, otp: str) -> str:
    key = _require_otp_secret().encode("utf-8")
    message = f"{normalize_email(email)}:{otp}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def smtp_settings() -> dict:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM_EMAIL", username).strip()

    if not all((host, username, password, sender)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Legacy email verification needs SMTP settings in the "
                "backend .env file."
            ),
        )

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP_PORT must be a valid port number in the backend .env file.",
        ) from exc

    use_ssl = _env_flag("SMTP_USE_SSL", False)
    use_starttls = _env_flag("SMTP_STARTTLS", not use_ssl)
    if not use_ssl and not use_starttls:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure SMTP with SSL or STARTTLS for legacy verification.",
        )

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "sender": sender,
        "sender_name": os.getenv("SMTP_FROM_NAME", "NyayaLens").strip() or "NyayaLens",
        "use_ssl": use_ssl,
        "use_starttls": use_starttls,
    }


def send_verification_email(settings: dict, email: str, name: str, otp: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Verify your NyayaLens email"
    message["From"] = f"{settings['sender_name']} <{settings['sender']}>"
    message["To"] = email
    message.set_content(
        f"Hello {name},\n\n"
        f"Your NyayaLens verification code is {otp}.\n"
        f"It expires in {OTP_TTL_MINUTES} minutes.\n\n"
        "If you did not request this code, you can ignore this email."
    )

    smtp_client = (
        smtplib.SMTP_SSL(
            settings["host"],
            settings["port"],
            timeout=15,
            context=ssl.create_default_context(),
        )
        if settings["use_ssl"]
        else smtplib.SMTP(settings["host"], settings["port"], timeout=15)
    )
    with smtp_client as server:
        server.ehlo()
        if settings["use_starttls"] and not settings["use_ssl"]:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        server.login(settings["username"], settings["password"])
        server.send_message(message)


def issue_legacy_email_otp(email: str, name: str, enforce_cooldown: bool = False) -> None:
    email = normalize_email(email)
    _require_otp_secret()
    settings = smtp_settings()

    if enforce_cooldown:
        previous = otp_collection.find_one({"email": email}, {"created_at": 1})
        created_at = previous.get("created_at") if previous else None
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed = (utc_now() - created_at.astimezone(timezone.utc)).total_seconds()
            if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Please wait 30 seconds before requesting another code.",
                )

    otp = generate_otp()
    now = utc_now()
    try:
        otp_collection.update_one(
            {"email": email},
            {
                "$set": {
                    "email": email,
                    "otp_hash": hash_otp(email, otp),
                    "expires_at": now + timedelta(minutes=OTP_TTL_MINUTES),
                    "attempts": 0,
                    "created_at": now,
                }
            },
            upsert=True,
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable. Please try again.",
        ) from exc

    try:
        send_verification_email(settings, email, name, otp)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The verification code could not be emailed. Check SMTP settings "
                "and request a new code."
            ),
        ) from exc


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user: UserSignup):
    email = normalize_email(str(user.email))

    try:
        ensure_user_email_index()
    except PyMongoError as exc:
        if isinstance(exc, DuplicateKeyError) or getattr(exc, "code", None) == 11000:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Signup is paused because existing MongoDB users contain duplicate "
                    "email addresses. No account was changed; review the duplicates "
                    "manually, then retry."
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not enforce unique email addresses. Please try again later.",
        ) from exc

    try:
        existing_user = find_user_by_email(email)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    new_user = {
        "name": user.name.strip(),
        "email": email,
        "password_hash": hash_password(user.password),
        # This stays false. New users are allowed to sign in only because their
        # explicit auth_method identifies the no-OTP signup flow.
        "is_verified": False,
        "auth_method": AUTH_METHOD_PASSWORD_NO_OTP,
        "created_at": utc_now(),
    }

    try:
        users_collection.insert_one(new_user)
    except DuplicateKeyError as exc:
        # Covers two simultaneous signups after the availability lookup.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    return {"message": "Account created. You can now sign in with your email and password."}


@router.post("/resend-verification")
def resend_verification(request: EmailOTPResend):
    email = normalize_email(str(request.email))
    try:
        user = find_user_by_email(email)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    # Keep this route for older accounts that used email verification. New
    # password_no_otp signups do not need or receive a verification code.
    if (
        not user
        or user.get("is_verified") is True
        or user.get("auth_method") == AUTH_METHOD_PASSWORD_NO_OTP
    ):
        return {"message": "If an eligible legacy account exists, a code will be sent."}

    issue_legacy_email_otp(email, user.get("name", "there"), enforce_cooldown=True)
    return {"message": "A new verification code has been sent to your email."}


@router.post("/verify-email")
def verify_email(request: EmailOTPVerify):
    email = normalize_email(str(request.email))
    now = utc_now()
    try:
        user = find_user_by_email(email)
        otp_record = otp_collection.find_one({"email": email})
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code is invalid or expired. Request a new code.",
        )
    if user.get("is_verified") is True:
        return {"message": "Email is already verified. You can sign in."}
    if user.get("auth_method") == AUTH_METHOD_PASSWORD_NO_OTP:
        return {"message": "This account uses password sign-in and does not need email verification."}
    if not otp_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code is invalid or expired. Request a new code.",
        )

    expires_at = otp_record.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not isinstance(expires_at, datetime) or expires_at <= now:
        try:
            otp_collection.delete_one({"email": email})
        except PyMongoError:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code has expired. Request a new code.",
        )

    try:
        attempts = int(otp_record.get("attempts", 0))
    except (TypeError, ValueError):
        attempts = OTP_MAX_ATTEMPTS
    if attempts >= OTP_MAX_ATTEMPTS:
        otp_collection.delete_one({"email": email})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many incorrect attempts. Request a new code.",
        )

    expected_hash = hash_otp(email, request.otp)
    stored_hash = otp_record.get("otp_hash", "")
    if not isinstance(stored_hash, str) or not hmac.compare_digest(expected_hash, stored_hash):
        try:
            updated = otp_collection.update_one(
                {
                    "email": email,
                    "otp_hash": stored_hash,
                    "attempts": attempts,
                    "expires_at": {"$gt": now},
                },
                {"$inc": {"attempts": 1}},
            )
        except PyMongoError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database temporarily unavailable.",
            ) from exc
        if updated.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The verification code is invalid or expired. Request a new code.",
            )
        if attempts + 1 >= OTP_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many incorrect attempts. Request a new code.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code is incorrect.",
        )

    try:
        consumed = otp_collection.find_one_and_delete(
            {
                "email": email,
                "otp_hash": expected_hash,
                "attempts": {"$lt": OTP_MAX_ATTEMPTS},
                "expires_at": {"$gt": now},
            }
        )
        if not consumed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The verification code is invalid, expired, or already used.",
            )
        users_collection.update_one(
            {
                "email": email,
                "is_verified": {"$ne": True},
                "auth_method": {"$ne": AUTH_METHOD_PASSWORD_NO_OTP},
            },
            {"$set": {"is_verified": True, "verified_at": now}},
            collation=EMAIL_COLLATION,
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    return {"message": "Email verified. You can now sign in."}


def create_session_response(user: dict, email: str) -> dict:
    now = utc_now()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(minutes=SESSION_TTL_MINUTES)

    try:
        ensure_session_indexes()
        sessions_collection.delete_many({"expires_at": {"$lte": now}})
        sessions_collection.insert_one(
            {
                "token_hash": token_hash,
                "email": email,
                "created_at": now,
                "expires_at": expires_at,
            }
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not start a session. Please try again.",
        ) from exc

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": SESSION_TTL_MINUTES * 60,
        "user": {"name": user.get("name", ""), "email": email},
    }


@router.post("/login")
def login(credentials: UserLogin):
    email = normalize_email(str(credentials.email))
    try:
        user = find_user_by_email(email)
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    if not user or not verify_password(credentials.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user_can_sign_in(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email before signing in.",
        )
    return create_session_response(user, email)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    now = utc_now()
    try:
        session = sessions_collection.find_one(
            {"token_hash": token_hash, "expires_at": {"$gt": now}},
            {"email": 1},
        )
        if not session:
            sessions_collection.delete_one({"token_hash": token_hash})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session has expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = find_user_by_email(session["email"])
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        ) from exc

    if not user or not user_can_sign_in(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The account is unavailable. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Include MongoDB's stable _id: main.py uses its string form to associate
    # uploads and history with this account.
    return user


def oauth_callback_url(provider: str) -> str:
    return f"{OAUTH_BASE_URL}/oauth/{provider}/callback"


def oauth_frontend_redirect(error: str) -> RedirectResponse:
    return RedirectResponse(
        f"{FRONTEND_URL}/#oauth_error={quote(error)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def oauth_is_configured(provider: str) -> bool:
    prefix = provider.upper()
    return bool(
        SESSION_SECRET_KEY
        and os.getenv(f"{prefix}_CLIENT_ID", "").strip()
        and os.getenv(f"{prefix}_CLIENT_SECRET", "").strip()
    )


async def provider_profile(provider: str, client, token: dict) -> tuple[str, str, str]:
    if provider == "github":
        profile_response = await client.get(
            "user",
            token=token,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        profile_response.raise_for_status()
        profile = profile_response.json()

        emails_response = await client.get(
            "user/emails",
            token=token,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        emails_response.raise_for_status()
        emails = emails_response.json()
        verified_email = next(
            (
                item.get("email")
                for item in emails
                if item.get("primary") is True
                and item.get("verified") is True
                and isinstance(item.get("email"), str)
            ),
            None,
        )
        if not verified_email or not profile.get("id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email_unavailable",
            )
        return (
            str(profile["id"]),
            normalize_email(verified_email),
            str(profile.get("name") or profile.get("login") or "GitHub user"),
        )

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo_response = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            token=token,
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
    profile = dict(userinfo)
    email = profile.get("email")
    if (
        not profile.get("sub")
        or not isinstance(email, str)
        or profile.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email_unavailable",
        )
    return (
        str(profile["sub"]),
        normalize_email(email),
        str(profile.get("name") or "LinkedIn user"),
    )


def find_or_create_oauth_user(provider: str, provider_user_id: str, email: str, name: str) -> dict:
    try:
        ensure_user_email_index()
        ensure_oauth_identity_indexes()
        identity = oauth_identities_collection.find_one(
            {"provider": provider, "provider_user_id": provider_user_id}
        )
        if identity:
            user = users_collection.find_one({"_id": identity["user_id"]})
            if not user or not user_can_sign_in(user):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="account_unavailable",
                )
            return user

        user = find_user_by_email(email)
        if user and not user_can_sign_in(user):
            # Do not activate a legacy unverified account or silently create a
            # second user for its email address.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="account_unverified",
            )

        if not user:
            new_user = {
                "name": name.strip() or "NyayaLens user",
                "email": email,
                "password_hash": None,
                "auth_method": "oauth",
                "is_verified": True,
                "verified_at": utc_now(),
                "created_at": utc_now(),
            }
            try:
                inserted = users_collection.insert_one(new_user)
                new_user["_id"] = inserted.inserted_id
                user = new_user
            except DuplicateKeyError:
                user = find_user_by_email(email)
                if not user or not user_can_sign_in(user):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="account_conflict",
                    )

        try:
            oauth_identities_collection.insert_one(
                {
                    "provider": provider,
                    "provider_user_id": provider_user_id,
                    "user_id": user["_id"],
                    "created_at": utc_now(),
                }
            )
        except DuplicateKeyError:
            identity = oauth_identities_collection.find_one(
                {"provider": provider, "provider_user_id": provider_user_id}
            )
            if not identity or identity.get("user_id") != user["_id"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="oauth_link_conflict",
                )
        return user
    except HTTPException:
        raise
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="oauth_index_conflict",
        ) from exc
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="oauth_database_unavailable",
        ) from exc


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, request: Request):
    if provider not in {"github", "linkedin"}:
        raise HTTPException(status_code=404, detail="OAuth provider not supported.")
    if not oauth_is_configured(provider):
        return oauth_frontend_redirect("oauth_not_configured")

    client = oauth.create_client(provider)
    redirect_uri = oauth_callback_url(provider)
    if provider == "github":
        return await client.authorize_redirect(
            request,
            redirect_uri,
            code_challenge_method="S256",
        )
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request):
    if provider not in {"github", "linkedin"}:
        raise HTTPException(status_code=404, detail="OAuth provider not supported.")
    if request.query_params.get("error"):
        return oauth_frontend_redirect("oauth_cancelled")
    if not oauth_is_configured(provider):
        return oauth_frontend_redirect("oauth_not_configured")

    try:
        client = oauth.create_client(provider)
        token = await client.authorize_access_token(request)
        provider_user_id, email, name = await provider_profile(provider, client, token)
        user = find_or_create_oauth_user(provider, provider_user_id, email, name)

        ensure_oauth_handoff_indexes()
        handoff_code = secrets.token_urlsafe(32)
        oauth_handoffs_collection.insert_one(
            {
                "code_hash": hashlib.sha256(handoff_code.encode("utf-8")).hexdigest(),
                "user_id": user["_id"],
                "created_at": utc_now(),
                "expires_at": utc_now() + timedelta(minutes=2),
            }
        )
        return RedirectResponse(
            f"{FRONTEND_URL}/#oauth_code={quote(handoff_code)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except HTTPException as exc:
        known_errors = {
            "email_unavailable",
            "account_unavailable",
            "account_unverified",
            "account_conflict",
            "oauth_link_conflict",
            "oauth_index_conflict",
            "oauth_database_unavailable",
        }
        return oauth_frontend_redirect(
            exc.detail if isinstance(exc.detail, str) and exc.detail in known_errors else "oauth_failed"
        )
    except Exception as exc:
        # Avoid logging provider codes, tokens, emails, or secrets.
        print(f"OAuth callback failed for {provider}: {type(exc).__name__}")
        return oauth_frontend_redirect("oauth_failed")


@router.post("/oauth/exchange")
def exchange_oauth_code(request: OAuthCodeExchange):
    code_hash = hashlib.sha256(request.code.encode("utf-8")).hexdigest()
    now = utc_now()
    try:
        ensure_oauth_handoff_indexes()
        handoff = oauth_handoffs_collection.find_one_and_delete(
            {"code_hash": code_hash, "expires_at": {"$gt": now}}
        )
        if not handoff:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The sign-in code is invalid or expired. Please try again.",
            )
        user = users_collection.find_one({"_id": handoff["user_id"]})
    except HTTPException:
        raise
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not complete sign-in. Please try again.",
        ) from exc

    if not user or not user_can_sign_in(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The account is unavailable. Please sign in again.",
        )
    return create_session_response(user, user["email"])


@router.get("/me")
def current_profile(user: dict = Depends(get_current_user)):
    return {"name": user.get("name", ""), "email": user["email"]}


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    _user: dict = Depends(get_current_user),
):
    token_hash = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    try:
        sessions_collection.delete_one({"token_hash": token_hash})
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not end the session. Please try again.",
        ) from exc
    return {"message": "Signed out successfully."}
