import os
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client[os.getenv("MONGODB_DB", "saa_sender")]

db_hr = client["hremail"]
source_coll = db_hr["email"]

from datetime import datetime

print("Starting direct sync script...")

cursor = source_coll.find({})
total = 0
ops = []

for doc in cursor:
    email = doc.get("email")
    if not email: continue
    email = email.strip().lower()
    
    domain = email.split("@")[-1]
    
    # We're just manually inserting to make them show up for the user immediately.
    # Normally the app handles country detection etc. For speed, we just do a quick generic insert
    # if they don't exist.
    ops.append({
        "updateOne": {
            "filter": {"email": email},
            "update": {
                "$setOnInsert": {
                    "email": email,
                    "domain": domain,
                    "health": "good",
                    "providerType": "free" if domain in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"] else "business",
                    "detectedCountry": "Global",
                    "confidence": 1.0,
                    "bounceCount": 0,
                    "enrichmentMetadata": {},
                    "source": "sync:hremail.email",
                    "created_at": datetime.utcnow()
                },
                "$set": {
                    "last_seen": datetime.utcnow()
                }
            },
            "upsert": True
        }
    })
    
    if len(ops) >= 1000:
        db.recruiters.bulk_write(
            [__import__("pymongo").UpdateOne(op["updateOne"]["filter"], op["updateOne"]["update"], upsert=op["updateOne"]["upsert"]) for op in ops],
            ordered=False
        )
        total += len(ops)
        print(f"Synced {total}...")
        ops = []

if ops:
    db.recruiters.bulk_write(
        [__import__("pymongo").UpdateOne(op["updateOne"]["filter"], op["updateOne"]["update"], upsert=op["updateOne"]["upsert"]) for op in ops],
        ordered=False
    )
    total += len(ops)

print(f"Done! {total} total records processed into saa_sender.recruiters")

# Verify
final_count = db.recruiters.count_documents({})
print(f"Database now has {final_count} recruiters!")
