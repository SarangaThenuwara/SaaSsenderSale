from app.db import db
from app.utils import encrypt_bytes_to_b64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

def migrate():
    users = list(db.users.find())
    logger.info(f"Found {len(users)} users to check.")
    
    updated_count = 0
    for u in users:
        updates = {}
        creds = u.get("credentials_base64")
        tok = u.get("token_base64")
        
        # Fernet encrypted strings usually start with 'gAAAA'
        if creds and not creds.startswith("gAAAA"):
            logger.info(f"Encrypting credentials for user {u.get('email', u['_id'])}")
            updates["credentials_base64"] = encrypt_bytes_to_b64(creds.encode())
            
        if tok and not tok.startswith("gAAAA"):
            logger.info(f"Encrypting token for user {u.get('email', u['_id'])}")
            updates["token_base64"] = encrypt_bytes_to_b64(tok.encode())
            
        if updates:
            db.users.update_one({"_id": u["_id"]}, {"$set": updates})
            updated_count += 1
            
    logger.info(f"Migration finished. Updated {updated_count} users.")

if __name__ == "__main__":
    migrate()
