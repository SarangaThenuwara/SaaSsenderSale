"""
Quick diagnostic: inspect hremail.email collection structure
Run with: python inspect_hremail.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()

# Force utf-8 output
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGODB_URI)

db_hr = client["hremail"]
coll = db_hr["email"]

total = coll.count_documents({})
print(f"Total documents in hremail.email: {total}")

if total == 0:
    print("ERROR: Collection is EMPTY - nothing to sync!")
else:
    print("\nSample documents (first 3):")
    for i, doc in enumerate(coll.find().limit(3)):
        doc.pop("_id", None)
        print(f"\n  [{i+1}] Keys: {list(doc.keys())}")
        items = list(doc.items())[:5]
        for k, v in items:
            print(f"       {k}: {repr(v)[:80]}")

    has_email_field = coll.count_documents({"email": {"$exists": True}})
    print(f"\nDocs with 'email' field: {has_email_field}/{total}")

    if has_email_field == 0:
        print("\nLooking for email-like fields...")
        sample = coll.find_one({})
        sample.pop("_id", None)
        for key, val in sample.items():
            if isinstance(val, str) and "@" in val:
                print(f"   Found email-like field: '{key}' = '{val}'")

    db_main = client[os.getenv("MONGODB_DB", "saa_sender")]
    recruiter_count = db_main.recruiters.count_documents({})
    print(f"\nCurrent recruiters in saa_sender.recruiters: {recruiter_count}")

print("\nDone.")
