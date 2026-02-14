from pymongo import MongoClient
from .config import MONGODB_URI, MONGODB_DB

client = MongoClient(MONGODB_URI)
db = client[MONGODB_DB]

# Ensure indexes used by the system
def ensure_indexes():
    # Users
    db.users.create_index("username", unique=True)
    db.users.create_index("supabase_id", unique=True, sparse=True) # Ensure mapping is fast
    
    # Legacy Recipients (Keep for now if needed, or deprecate)
    db.recipients.create_index([("status", 1), ("assigned_to", 1)])
    db.recipients.create_index("email", unique=True)
    db.recipients.create_index("dedupe_key")
    
    # 1. Recruiters (Global Master List)
    db.recruiters.create_index("email", unique=True)
    db.recruiters.create_index("domain")
    db.recruiters.create_index("detectedCountry")
    db.recruiters.create_index("health")
    db.recruiters.create_index("providerType")
    
    # 2. User Recruiter Ledger
    # Compound unique index to prevent duplicate assignment
    db.user_recruiter_ledger.create_index([("userId", 1), ("recruiterId", 1)], unique=True)
    # Compound index for efficient worker queries (fetch pending jobs for a user)
    db.user_recruiter_ledger.create_index([("userId", 1), ("status", 1), ("lastAttempt", 1)])
    # Index for analytics/filtering
    db.user_recruiter_ledger.create_index("campaignId")

    # 3. Domain Country Cache
    db.domain_country_cache.create_index("domain", unique=True)

    # 4. Global Suppression List
    db.suppression.create_index("email", unique=True)
    db.suppression.create_index("recruiterId")


ensure_indexes()