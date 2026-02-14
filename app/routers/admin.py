from fastapi import APIRouter, Depends, HTTPException, Request, Body
import requests
from app.db import db
from app.config import ADMIN_API_KEY
from bson.objectid import ObjectId
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/admin", tags=["admin"])

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
    res = db.users.update_one(
        {"_id": ObjectId(user_id)}, 
        {"$set": {"is_blocked": True, "campaign_active": False}}
    )
    return {"modified": res.modified_count}

@router.post("/users/{user_id}/unblock")
def unblock_user(user_id: str, _admin=Depends(get_admin_user)):
    res = db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_blocked": False}})
    return {"modified": res.modified_count}

@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: str, _admin=Depends(get_admin_user)):
    """Manually unlocks a user account locked by brute-force protection."""
    res = db.users.update_one(
        {"_id": ObjectId(user_id)}, 
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

    res = db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "User not found")
        
    log_admin_action(_admin["username"], "update_user", f"Updated user {user_id}: {list(updates.keys())}")
    return {"ok": True, "updated_fields": list(updates.keys())}

@router.delete("/users/{user_id}")
def delete_user(user_id: str, _admin=Depends(get_admin_user)):
    # Soft delete (90 day window)
    res = db.users.update_one(
        {"_id": ObjectId(user_id)}, 
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
    
    # Redis Stats
    try:
        from app.celery_app import celery_app
        with celery_app.pool.acquire(block=True) as conn:
            r = conn.default_channel.client
            info = r.info()
            db_stats["redis"] = {
                "used_memory": info.get("used_memory_human"),
                "clients": info.get("connected_clients"),
                "uptime_days": info.get("uptime_in_days"),
                "ops_per_sec": info.get("instantaneous_ops_per_sec")
            }
    except: db_stats["redis"] = {"error": "Connection failed"}
    
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
        
    res = db.recruiters.update_one(
        {"_id": ObjectId(recruiter_id)},
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
        
    res = db.recruiters.update_one({"_id": ObjectId(recruiter_id)}, {"$set": updates})
    
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
        # Also mark recruiter as dead if exists
        db.recruiters.update_one({"email": email}, {"$set": {"health": "dead"}})
    except Exception as e:
        raise HTTPException(500, str(e))
        
    return {"ok": True, "email": email}

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
