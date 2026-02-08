from pymongo import MongoClient
from .config import MONGODB_URI, MONGODB_DB

client = MongoClient(MONGODB_URI)
db = client[MONGODB_DB]

# Ensure indexes used by the system
def ensure_indexes():
    db.users.create_index("username", unique=True)
    db.recipients.create_index([("status", 1), ("assigned_to", 1)])
    db.recipients.create_index("dedupe_key")
    db.suppression.create_index("email", unique=True)

ensure_indexes()