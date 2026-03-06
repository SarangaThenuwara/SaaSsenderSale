from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse
import requests
from app.db import db
from app.config import ADMIN_API_KEY
from app.security import csrf_protect, parse_oid
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import stripe

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(csrf_protect)])

def get_admin_user(request: Request):
    """
    Dependency to ensure the user is an admin.
    """
    user = getattr(request.state, "session_user", None)
    if user and user.get("role") == "admin":
        return user
    
    # Check API Key Header as fallback (for external tools/scripts)
    api_key = request.headers.get("X-Admin-API-Key")
    if api_key and api_key == ADMIN_API_KEY:
        return {"_id": "api_key", "role": "admin", "username": "system_admin"}
        
    raise HTTPException(status_code=403, detail="Not authorized")

@router.get("/users")
def get_users(_admin=Depends(get_admin_user)):
    users = list(db.users.find({"is_deleted": {"$ne": True}}, {
        "credentials_base64": 0, 
        "token_base64": 0, 
        "refresh_token_enc": 0
    }).sort("created_at", -1).limit(100))
    
    for u in users:
        u["_id"] = str(u["_id"])
        # Add quick stats
        u["assigned_recruiters"] = db.user_recruiter_ledger.count_documents({"userId": ObjectId(u["_id"])})
        u["sent_today"] = u.get("daily_sent", 0)
        
    return users

@router.post("/users/{user_id}/block")
def block_user(user_id: str, _admin=Depends(get_admin_user)):
    target_id = parse_oid(user_id)
    res = db.users.update_one(
        {"_id": target_id}, 
        {"$set": {"is_blocked": True, "campaign_active": False}}
    )
    return {"modified": res.modified_count}

@router.post("/users/{user_id}/unblock")
def unblock_user(user_id: str, _admin=Depends(get_admin_user)):
    target_id = parse_oid(user_id)
    res = db.users.update_one({"_id": target_id}, {"$set": {"is_blocked": False}})
    return {"modified": res.modified_count}

@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: str, _admin=Depends(get_admin_user)):
    """Manually unlocks a user account locked by brute-force protection."""
    target_id = parse_oid(user_id)
    res = db.users.update_one(
        {"_id": target_id}, 
        {"$set": {"locked_until": None, "failed_login_attempts": 0}}
    )
    return {"modified": res.modified_count}

@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: dict = Body(...), _admin=Depends(get_admin_user)):
    allowed = ["daily_limit", "role", "is_paid", "is_blocked", "username", "campaign_active", "subscription_expires_at"]
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates: raise HTTPException(400, "No valid fields")
    
    # SECURITY: Validate daily_limit bounds
    if "daily_limit" in updates:
        try:
            limit = int(updates["daily_limit"])
            if not 0 <= limit <= 10000:
                raise HTTPException(400, "daily_limit must be between 0 and 10000")
            updates["daily_limit"] = limit
        except ValueError:
             raise HTTPException(400, "daily_limit must be an integer")

    if "is_paid" in updates:
        updates["is_paid"] = bool(updates["is_paid"])
        # If setting to true and no expiry provided, default to +30 days
        if updates["is_paid"] and "subscription_expires_at" not in updates:
             updates["subscription_expires_at"] = datetime.utcnow() + timedelta(days=30)

    if "subscription_expires_at" in updates and isinstance(updates["subscription_expires_at"], str):
        try:
            updates["subscription_expires_at"] = datetime.fromisoformat(updates["subscription_expires_at"].replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "Invalid date format for subscription_expires_at. Use ISO format.")

    target_id = parse_oid(user_id)
    res = db.users.update_one({"_id": target_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "User not found")
        
    log_admin_action(_admin["username"], "update_user", f"Updated user {user_id}: {list(updates.keys())}")
    return {"ok": True, "updated_fields": list(updates.keys())}

@router.delete("/users/{user_id}")
def delete_user(user_id: str, _admin=Depends(get_admin_user)):
    # Soft delete (90 day window)
    target_id = parse_oid(user_id)
    res = db.users.update_one(
        {"_id": target_id}, 
        {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "campaign_active": False}}
    )
    log_admin_action(_admin["username"], "soft_delete", f"Deleted user {user_id}")
    return {"modified": res.modified_count}

import psutil
import socket

def get_infra_stats():
    """Gathers system-level resource utilization."""
    try:
        # CPU & Memory
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        
        # Disk/Storage
        disk = psutil.disk_usage('/')
        
        # Network (Estimate bandwidth usage)
        net = psutil.net_io_counters()
        
        # IP Addresses
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        public_ip = "N/A"
        try:
            public_ip = requests.get('https://api.ipify.org', timeout=2).text
        except: pass
        
        return {
            "cpu": cpu_usage,
            "memory_pct": memory.percent,
            "memory_used": round(memory.used / (1024**3), 2), # GB
            "memory_total": round(memory.total / (1024**3), 2),
            "storage_pct": disk.percent,
            "storage_used": round(disk.used / (1024**3), 2),
            "storage_total": round(disk.total / (1024**3), 2),
            "net_sent": round(net.bytes_sent / (1024**2), 2), # MB
            "net_recv": round(net.bytes_recv / (1024**2), 2),
            "local_ip": local_ip,
            "public_ip": public_ip,
            "hostname": hostname
        }
    except Exception:
        return {}

def get_db_stats():
    """Gathers MongoDB and Redis utilization stats."""
    db_stats = {}
    
    # MongoDB Stats
    try:
        stats = db.command("dbstats")
        db_stats["mongo"] = {
            "data_size": round(stats.get("dataSize", 0) / (1024**2), 2), # MB
            "index_size": round(stats.get("indexSize", 0) / (1024**2), 2),
            "collections": stats.get("collections", 0),
            "objects": stats.get("objects", 0)
        }
    except: db_stats["mongo"] = {"error": "Connection failed"}
    
    # Redis Stats (ENHANCED)
    try:
        from app.redis_client import redis_client
        if redis_client:
            info = redis_client.info()
            db_stats["redis"] = {
                "ok": True,
                "version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "peak_memory": info.get("used_memory_peak_human"),
                "clients": info.get("connected_clients"),
                "uptime_days": info.get("uptime_in_days"),
                "ops_per_sec": info.get("instantaneous_ops_per_sec"),
                "total_commands": info.get("total_commands_processed"),
                "hit_rate": round(info.get("keyspace_hits", 0) / (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 1)) * 100, 2) if (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)) > 0 else 0,
                "keys": sum([db.get("keys", 0) for name, db in info.items() if name.startswith("db")]),
                "expires": sum([db.get("expires", 0) for name, db in info.items() if name.startswith("db")]),
                "os": info.get("os"),
                "process_id": info.get("process_id")
            }
        else:
            db_stats["redis"] = {"error": "Redis client not available"}
    except Exception as e:
        db_stats["redis"] = {"error": str(e)}
    
    return db_stats

@router.get("/infra")
def infra_metrics(_admin=Depends(get_admin_user)):
    return {
        "system": get_infra_stats(),
        "databases": get_db_stats()
    }

@router.get("/settings")
def get_global_settings(_admin=Depends(get_admin_user)):
    settings = db.settings.find_one({"_id": "global"}) or {
        "maintenance_mode": False,
        "maintenance_message": "System under scheduled maintenance.",
        "signup_enabled": True,
        "default_daily_limit": 240,
        "payment_gateway_enabled": False
    }
    return settings

@router.post("/settings")
def update_global_settings(payload: dict = Body(...), _admin=Depends(get_admin_user)):
     # Only allow safe keys
    safe_keys = ["maintenance_mode", "maintenance_message", "signup_enabled", "default_daily_limit", "payment_gateway_enabled"]
    updates = {k: v for k, v in payload.items() if k in safe_keys}
    
    db.settings.update_one({"_id": "global"}, {"$set": updates}, upsert=True)
    
    # Audit Log
    log_admin_action(_admin["username"], "update_settings", f"Updated global settings: {list(updates.keys())}")
    
    return {"ok": True}

@router.get("/audit_logs")
def get_audit_logs(_admin=Depends(get_admin_user)):
    logs = list(db.admin_audit_logs.find().sort("timestamp", -1).limit(100))
    for l in logs:
        l["_id"] = str(l["_id"])
        l["timestamp"] = l["timestamp"].isoformat() if l.get("timestamp") else None
    return logs

def log_admin_action(username, action, details):
    db.admin_audit_logs.insert_one({
        "username": username,
        "action": action,
        "details": details,
        "timestamp": datetime.utcnow()
    })

@router.get("/revenue")
def get_revenue_stats(_admin=Depends(get_admin_user)):
    total_paid = db.users.count_documents({"is_paid": True, "is_deleted": {"$ne": True}})
    # Mocking revenue based on a fixed 300 AED price
    active_mrr = total_paid * 300 
    
    # Recent subscriptions (last 30 days)
    month_ago = datetime.utcnow() - timedelta(days=30)
    new_subs = db.users.count_documents({"is_paid": True, "paid_at": {"$gte": month_ago}})
    
    return {
        "total_paid_users": total_paid,
        "mrr": active_mrr,
        "new_subs_30d": new_subs,
        "currency": "AED"
    }

@router.get("/stats")
def global_stats(_admin=Depends(get_admin_user)):
    total_users = db.users.count_documents({"is_deleted": {"$ne": True}})
    total_recruiters = db.recruiters.count_documents({})
    total_suppressed = db.suppression.count_documents({})
    
    # Aggregate sent today across all users
    pipeline = [{"$group": {"_id": None, "total_sent": {"$sum": "$daily_sent"}}}]
    sent_res = list(db.users.aggregate(pipeline))
    total_sent_today = sent_res[0]["total_sent"] if sent_res else 0
    
    # Dead recruiters
    dead_recruiters = db.recruiters.count_documents({"health": "dead"})
    
    return {
        "total_users": total_users,
        "total_recruiters": total_recruiters,
        "total_suppressed": total_suppressed,
        "total_sent_today": total_sent_today,
        "dead_recruiters": dead_recruiters
    }

@router.get("/recruiters/review")
def review_recruiters(limit: int = 50, _admin=Depends(get_admin_user)):
    """Get recruiters with low confidence country detection."""
    recruiters = list(db.recruiters.find(
        {"confidence": {"$lt": 0.8}, "providerType": {"$ne": "free"}},
        {"enrichmentMetadata": 0}
    ).limit(limit))
    
    for r in recruiters:
        r["_id"] = str(r["_id"])
        
    return recruiters

@router.post("/recruiters/{recruiter_id}/override_country")
def override_country(recruiter_id: str, payload: dict = Body(...), _admin=Depends(get_admin_user)):
    country = payload.get("country")
    if not country:
        raise HTTPException(400, "Country required")
        
    target_id = parse_oid(recruiter_id)
    res = db.recruiters.update_one(
        {"_id": target_id},
        {"$set": {"detectedCountry": country, "confidence": 1.0, "manual_override": True}}
    )
    return {"modified": res.modified_count}

@router.get("/suppression")
def list_suppression(limit: int = 50, _admin=Depends(get_admin_user)):
    items = list(db.suppression.find().sort("created_at", -1).limit(limit))
    for i in items:
        i["_id"] = str(i["_id"])
    return items

@router.delete("/suppression/{email}")
def remove_suppression(email: str, _admin=Depends(get_admin_user)):
    res = db.suppression.delete_one({"email": email})
    return {"deleted": res.deleted_count}

@router.post("/queue/reset")
def reset_queues(_admin=Depends(get_admin_user)):
    # Reset all users daily limits manually
    res = db.users.update_many({}, {"$set": {"daily_sent": 0}})
    return {"reset_count": res.modified_count}

@router.post("/recruiters/sync")
def trigger_recruiter_sync(_admin=Depends(get_admin_user)):
    """Manually trigger the background sync from the configured source."""
    try:
        from app.sync_pool import sync_from_main_database
        # Trigger as a Celery task
        task = sync_from_main_database.delay()
        return {"ok": True, "task_id": task.id}
    except Exception as e:
        LOG.error(f"Failed to trigger sync: {e}")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "message": str(e)}
        )

# --- Enhanced Recruiter Management ---

import dns.resolver

@router.get("/dns_check")
def dns_check(domain: str, _admin=Depends(get_admin_user)):
    """Verifies MX, SPF, and DMARC status for a domain."""
    results = {"mx": "missing", "spf": "missing", "dmarc": "missing"}
    
    try:
        # Check MX
        mx_records = dns.resolver.resolve(domain, 'MX')
        if mx_records: results["mx"] = "configured"
    except: pass
    
    try:
        # Check SPF
        txt_records = dns.resolver.resolve(domain, 'TXT')
        for r in txt_records:
            if "v=spf1" in str(r):
                results["spf"] = "configured"
                break
    except: pass

    try:
        # Check DMARC
        dmarc_records = dns.resolver.resolve(f"_dmarc.{domain}", 'TXT')
        if dmarc_records: results["dmarc"] = "configured"
    except: pass
    
    return results

@router.get("/recruiters")
def list_recruiters(
    page: int = 1, 
    limit: int = 20, 
    country: str = None, 
    provider: str = None, 
    health: str = None,
    search: str = None,
    _admin=Depends(get_admin_user)
):
    query = {}
    if country:
        query["detectedCountry"] = country
    if provider:
        query["providerType"] = provider
    if health:
        query["health"] = health
    if search:
        # SECURITY: Escape regex special characters to prevent injection
        import re as regex_module
        escaped_search = regex_module.escape(search)
        query["email"] = {"$regex": escaped_search, "$options": "i"}
        
    skip = (page - 1) * limit
    cursor = db.recruiters.find(query).skip(skip).limit(limit)
    total = db.recruiters.count_documents(query)
    
    items = []
    for r in cursor:
        r["_id"] = str(r["_id"])
        # Format dates
        if "created_at" in r: r["created_at"] = r["created_at"].isoformat()
        if "last_seen" in r: r["last_seen"] = r["last_seen"].isoformat()
        items.append(r)
        
    return {"items": items, "total": total, "page": page, "limit": limit}

@router.patch("/recruiters/{recruiter_id}")
def update_recruiter(recruiter_id: str, payload: dict = Body(...), _admin=Depends(get_admin_user)):
    allowed = ["detectedCountry", "providerType", "health", "manual_override", "confidence"]
    updates = {k: v for k, v in payload.items() if k in allowed}
    
    if not updates:
        raise HTTPException(400, "No valid updates provided")
        
    if "manual_override" in updates and updates["manual_override"]:
        updates["confidence"] = 1.0 # Auto-set confidence if manually overridden
        
    target_id = parse_oid(recruiter_id)
    res = db.recruiters.update_one({"_id": target_id}, {"$set": updates})
    
    if res.matched_count == 0:
        raise HTTPException(404, "Recruiter not found")
        
    return {"ok": True, "modified": res.modified_count}

# --- Queue & System Health ---

import redis
from app.config import CELERY_BROKER_URL

@router.get("/queues")
def get_queues(_admin=Depends(get_admin_user)):
    try:
        r = redis.from_url(CELERY_BROKER_URL)
        # Standard Celery queues + our named queues
        queues = ["celery", "default", "send_queue", "assign_queue", "sync_queue"]
        stats = {}
        total_queued = 0
        for q in queues:
            length = r.llen(q)
            stats[q] = length
            total_queued += length
            
        return {"queues": stats, "total_queued": total_queued, "ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- Bounce & Deliverability Analytics ---

@router.get("/bounces/stats")
def bounce_stats(_admin=Depends(get_admin_user)):
    # 1. By Provider (Risky/Dead)
    provider_stats = list(db.recruiters.aggregate([
        {"$match": {"health": {"$in": ["risky", "dead"]}}},
        {"$group": {"_id": "$providerType", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]))
    
    # 2. By Country (Top 10 Risky/Dead)
    country_stats = list(db.recruiters.aggregate([
        {"$match": {"health": {"$in": ["risky", "dead"]}}},
        {"$group": {"_id": "$detectedCountry", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]))
    
    # 3. Bounce Rate Trend (Global - Mock timeframe for now based on 'last_seen' or similar?)
    # More useful: Users with high bounce rates
    risky_users = list(db.users.aggregate([
        {"$match": {"bounces_today": {"$gt": 0}}},
        {"$project": {
            "username": 1, 
            "email": 1, 
            "bounces_today": 1, 
            "daily_sent": 1,
            "rate": {"$divide": ["$bounces_today", {"$max": ["$daily_sent", 1]}]}
        }},
        {"$sort": {"rate": -1}},
        {"$limit": 5}
    ]))
    for u in risky_users:
        u["_id"] = str(u["_id"])
        u["rate"] = round(u["rate"] * 100, 1) # percent

    return {
        "by_provider": provider_stats, 
        "by_country": country_stats,
        "risky_users": risky_users
    }

@router.post("/suppression")
def add_suppression(payload: dict = Body(...), _admin=Depends(get_admin_user)):
    email = payload.get("email")
    reason = payload.get("reason", "manual_admin")
    
    if not email:
        raise HTTPException(400, "Email required")
        
    try:
        db.suppression.update_one(
            {"email": email},
            {"$set": {"reason": reason, "created_at": datetime.utcnow()}},
            upsert=True
        )
        # 1. Mark global recruiter record as dead
        db.recruiters.update_one({"email": email}, {"$set": {"health": "dead"}})
        
        # 2. Skip all pending/sending entries in all user ledgers
        skipped = db.user_recruiter_ledger.update_many(
            {"email": email, "status": {"$in": ["pending", "sending"]}},
            {"$set": {"status": "skipped", "error": "suppressed_by_admin"}}
        )
        
        log_admin_action(_admin["username"], "add_suppression", f"Suppressed {email}. Skipped {skipped.modified_count} ledger jobs.")
    except Exception as e:
        raise HTTPException(500, str(e))
        
    return {"ok": True, "email": email, "skipped_jobs": skipped.modified_count}

# --- Worker Management ---
from app.celery_app import celery_app

@router.get("/workers")
def list_workers(_admin=Depends(get_admin_user)):
    try:
        i = celery_app.control.inspect()
        # active_queues returns {worker_name: [{name: 'queue', ...}, ...]}
        queues = i.active_queues()
        if not queues:
             # If no workers are running or inspection failed (e.g. no broker connection)
             # try ping to see if they are just not consuming
             pings = i.ping()
             if pings:
                 # Workers are alive but maybe no queues found?
                 # Format: {worker: []}
                 return {"ok": True, "workers": {k: [] for k in pings.keys()}}
             else:
                 return {"ok": True, "workers": {}}
        
        return {"ok": True, "workers": queues}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.post("/workers/pause")
def pause_worker(payload: dict = Body(...), _admin=Depends(get_admin_user)):
    worker = payload.get("worker")
    if not worker: return {"ok": False, "error": "Worker name required"}
    
    # Cancel consumption for all known queues
    # In a real app we might want to be more specific, but this pauses everything
    for q in ["send_queue", "default", "celery", "assign_queue", "sync_queue"]:
        celery_app.control.cancel_consumer(q, destination=[worker])
        
    return {"ok": True, "action": "paused", "worker": worker}

@router.post("/workers/resume")
def resume_worker(payload: dict = Body(...), _admin=Depends(get_admin_user)):
    worker = payload.get("worker")
    if not worker: return {"ok": False, "error": "Worker name required"}
    
    # Resume consumption
    for q in ["send_queue", "default", "celery", "assign_queue", "sync_queue"]:
        celery_app.control.add_consumer(q, destination=[worker])
        
    return {"ok": True, "action": "resumed", "worker": worker}

@router.post("/broadcast")
def broadcast_notification(payload: dict = Body(...), _admin=Depends(get_admin_user)):
    """Store a system-wide notification banner for all users to see."""
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty")
    if len(message) > 500:
        raise HTTPException(400, "Message too long (max 500 chars)")

    db.settings.update_one(
        {"_id": "global"},
        {"$set": {
            "broadcast_message": message,
            "broadcast_at": datetime.utcnow(),
            "broadcast_by": _admin.get("username", "admin")
        }},
        upsert=True
    )
    log_admin_action(_admin["username"], "broadcast", f"Sent system notification: {message[:80]}")
    return {"ok": True, "message": message}

@router.delete("/broadcast")
def clear_broadcast(_admin=Depends(get_admin_user)):
    """Clear the active system-wide notification banner."""
    db.settings.update_one(
        {"_id": "global"},
        {"$unset": {"broadcast_message": "", "broadcast_at": "", "broadcast_by": ""}}
    )
    log_admin_action(_admin["username"], "broadcast_clear", "Cleared system notification banner")
    return {"ok": True}

@router.post("/optimize_indexes")
def optimize_indexes(_admin=Depends(get_admin_user)):
    """Re-index all major MongoDB collections for performance."""
    results = {}
    collections_to_optimize = ["users", "recruiters", "user_recruiter_ledger", "recipients", "suppression"]
    for col_name in collections_to_optimize:
        try:
            col = db[col_name]
            col.reindex()
            results[col_name] = "ok"
        except Exception as e:
            results[col_name] = f"error: {str(e)}"

    log_admin_action(_admin["username"], "optimize_indexes", f"Ran reIndex on {len(collections_to_optimize)} collections")
    return {"ok": True, "results": results}

@router.get("/global_report")
def global_report(_admin=Depends(get_admin_user)):
    """Fetch recent outreach activity across all users."""
    pipeline = [
        {"$sort": {"sent_at": -1}},
        {"$limit": 50},
        {"$lookup": {
            "from": "users",
            "localField": "assigned_to",
            "foreignField": "_id",
            "as": "user"
        }},
        {"$unwind": {"path": "$user", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "username": {"$ifNull": ["$user.username", "Unknown"]},
            "email": 1, # Recipient email
            "status": 1,
            "sent_at": 1,
            "ip_address": {"$ifNull": ["$user.last_login_ip", "0.0.0.0"]}
        }}
    ]
    activity = list(db.recipients.aggregate(pipeline))
    result = []
    for a in activity:
        result.append({
            "username": a.get("username"),
            "email": a.get("email"),
            "status": a.get("status"),
            "ip_address": a.get("ip_address"),
            "sent_at": a.get("sent_at").isoformat() if a.get("sent_at") else None
        })
    return result

# --- NEW ADMIN FEATURES ---

@router.post("/impersonate/{user_id}")
def impersonate_user(user_id: str, request: Request, _admin=Depends(get_admin_user)):
    """Set session var to impersonate another user."""
    request.session["impersonating"] = user_id
    log_admin_action(_admin.get("username", "admin"), "impersonate", f"Impersonating user {user_id}")
    return {"ok": True, "message": f"Now impersonating {user_id}. Refresh the page."}

@router.post("/stop_impersonating")
def stop_impersonating(request: Request, _admin=Depends(get_admin_user)):
    """Stop impersonating and return to admin session."""
    request.session.pop("impersonating", None)
    return {"ok": True}

@router.get("/message_trace")
def message_trace(query: str, _admin=Depends(get_admin_user)):
    """Global search across user_recruiter_ledger by email/domain."""
    import re
    # Match email exactly, or if it's a domain, try $regex
    regex = re.compile(re.escape(query), re.IGNORECASE)
    leads = list(db.user_recruiter_ledger.find({
        "$or": [
            {"email": regex},
            {"domain": regex}
        ]
    }).sort("updated_at", -1).limit(100))
    for l in leads:
        l["_id"] = str(l["_id"])
        l["userId"] = str(l["userId"])
        if "campaignId" in l: l["campaignId"] = str(l["campaignId"])
    return {"results": leads}

@router.get("/content_review")
def content_review(_admin=Depends(get_admin_user)):
    """Fetch users' templates to review for spam."""
    users = list(db.users.find({
        "$or": [
            {"email_templates": {"$exists": True, "$not": {"$size": 0}}},
            {"body_template": {"$exists": True, "$ne": ""}}
        ]
    }).limit(100))
    results = []
    for u in users:
        results.append({
            "user_id": str(u["_id"]),
            "username": u.get("username"),
            "email": u.get("email"),
            "subject": u.get("subject_template"),
            "body": u.get("body_template"),
            "templates": u.get("email_templates")
        })
    return results

@router.post("/billing/credits/{user_id}")
def add_credits(user_id: str, payload: dict = Body(...), _admin=Depends(get_admin_user)):
    """Manually issue bonus credits/sends."""
    amount = payload.get("amount", 0)
    target_id = parse_oid(user_id)
    res = db.users.update_one({"_id": target_id}, {"$inc": {"daily_limit": amount}})
    log_admin_action(_admin.get("username", "admin"), "add_credits", f"Added {amount} limit to {user_id}")
    return {"ok": True, "modified": res.modified_count}

@router.post("/billing/subscription/{user_id}")
def update_user_subscription(user_id: str, payload: dict = Body(...), _admin=Depends(get_admin_user)):
    """
    Admin: Manually upgrade/downgrade subscription status.
    If 'is_paid' is true, we set expiry to +30 days by default.
    """
    is_paid = payload.get("is_paid", False)
    target_id = parse_oid(user_id)
    
    update_data = {"is_paid": is_paid}
    if is_paid:
        update_data["subscription_expires_at"] = datetime.utcnow() + timedelta(days=30)
    else:
        update_data["subscription_expires_at"] = datetime.utcnow()
        update_data["campaign_active"] = False

    res = db.users.update_one({"_id": target_id}, {"$set": update_data})
    log_admin_action(_admin.get("username", "admin"), "update_subscription", f"Set is_paid={is_paid} for {user_id}")
    return {"ok": True, "modified": res.modified_count}

@router.post("/billing/subscription/{user_id}/cancel")
def cancel_user_subscription(user_id: str, _admin=Depends(get_admin_user)):
    """
    Admin: Proactively cancel the user's Stripe subscription.
    """
    target_id = parse_oid(user_id)
    user = db.users.find_one({"_id": target_id})
    if not user:
        raise HTTPException(404, "User not found")
    
    sub_id = user.get("stripe_subscription_id")
    if not sub_id:
        # Fallback: Just mark as unpaid if no Stripe ID
        db.users.update_one({"_id": target_id}, {"$set": {"is_paid": False, "campaign_active": False}})
        return {"ok": True, "message": "Local access revoked (no Stripe subscription found)"}
    
    from app.stripe_pay import cancel_subscription
    res = cancel_subscription(sub_id)
    if res:
        log_admin_action(_admin.get("username", "admin"), "cancel_stripe_subscription", f"Cancelled Stripe subscription {sub_id} for user {user_id}")
        return {"ok": True, "message": "Subscription marked for cancellation in Stripe"}
    else:
        raise HTTPException(500, "Failed to cancel subscription in Stripe")

