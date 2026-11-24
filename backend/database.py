import os

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collation import Collation
from pymongo.server_api import ServerApi


load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("MONGODB_DB_NAME", "nyayalens")

if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is missing from .env")

client = MongoClient(
    MONGODB_URI,
    server_api=ServerApi("1"),
    serverSelectionTimeoutMS=10_000,
)

db = client[DATABASE_NAME]

# Collation makes email lookups and the unique index case-insensitive while
# keeping stored addresses normalized to lowercase in the application.
EMAIL_COLLATION = Collation(locale="en", strength=2)

users_collection = db["users"]
otp_collection = db["email_otps"]
sessions_collection = db["sessions"]
analyses_collection = db["analyses"]
analysis_translations_collection = db["analysis_translations"]

# Future OAuth providers can map (provider, provider_user_id) to the existing
# users._id. No OAuth routes or provider credentials are configured here.
oauth_identities_collection = db["oauth_identities"]
oauth_handoffs_collection = db["oauth_handoffs"]


def ensure_user_email_index():
    """Enforce case-insensitive email uniqueness without changing user rows.

    If existing rows contain duplicate emails, MongoDB refuses to create this
    index. The caller can report that conflict and leave every row untouched.
    The partial filter leaves unrelated legacy rows without a string email
    out of this index.
    """

    return users_collection.create_index(
        [("email", ASCENDING)],
        unique=True,
        collation=EMAIL_COLLATION,
        partialFilterExpression={"email": {"$type": "string"}},
        name="unique_user_email_case_insensitive",
    )


def ensure_session_indexes():
    """Create or confirm indexes used by bearer-token sessions."""

    sessions_collection.create_index(
        "token_hash",
        unique=True,
        name="unique_session_token_hash",
    )
    sessions_collection.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="expire_sessions_at_deadline",
    )


def ensure_analysis_indexes():
    """Optimize retrieval of each user's analysis history."""

    analyses_collection.create_index(
        [
            ("user_id", ASCENDING),
            ("created_at", DESCENDING),
        ],
        name="user_analysis_history",
    )


def ensure_oauth_identity_indexes():
    """Prepare stable, unique provider identity links for a future OAuth phase."""

    oauth_identities_collection.create_index(
        [
            ("provider", ASCENDING),
            ("provider_user_id", ASCENDING),
        ],
        unique=True,
        name="unique_oauth_provider_identity",
    )
    oauth_identities_collection.create_index(
        "user_id",
        name="oauth_identities_by_user",
    )


def ensure_oauth_handoff_indexes():
    """Create one-time OAuth code lookup and expiry indexes."""

    oauth_handoffs_collection.create_index(
        "code_hash",
        unique=True,
        name="unique_oauth_handoff_code_hash",
    )
    oauth_handoffs_collection.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="expire_oauth_handoffs_at_deadline",
    )


def initialize_database():
    """Check MongoDB connectivity and initialize supporting indexes."""

    client.admin.command("ping")
    ensure_user_email_index()
    ensure_session_indexes()
    ensure_analysis_indexes()
    ensure_oauth_identity_indexes()
    ensure_oauth_handoff_indexes()
    return True


def test_connection():
    client.admin.command("ping")
    return True


if __name__ == "__main__":
    try:
        initialize_database()
        print("MongoDB Atlas connected successfully!")
        print("Database:", DATABASE_NAME)
        print("Database indexes initialized!")
    except Exception as error:
        print("MongoDB connection or index setup failed.")
        print("Error type:", type(error).__name__)
        print("Error details:", str(error))
