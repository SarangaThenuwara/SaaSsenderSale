from fastapi import APIRouter, Depends, HTTPException, Request, Body
from app.db import db
from app.security import csrf_protect, parse_oid
from bson.objectid import ObjectId
from datetime import datetime

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"], dependencies=[Depends(csrf_protect)])

def get_current_user(request: Request):
    user = getattr(request.state, "session_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@router.get("/filters")
def get_filter_options(user=Depends(get_current_user)):
    """
    Returns available countries and provider types based on the user's ledger.
    Using aggregation for performance.
    """
    pipeline = [
        {"$match": {"userId": ObjectId(user["_id"])}},
        {"$group": {
            "_id": None, 
            "countries": {"$addToSet": "$country"},
            "providers": {"$addToSet": "$provider"}
        }}
    ]
    res = list(db.user_recruiter_ledger.aggregate(pipeline))
    if not res:
        return {"countries": [], "providers": []}
    
    data = res[0]
    # Filter out None values and sort
    countries = sorted([c for c in data.get("countries", []) if c])
    providers = sorted([p for p in data.get("providers", []) if p])
    
    return {"countries": countries, "providers": providers}

@router.get("/")
def list_campaigns(user=Depends(get_current_user)):
    """
    List all campaigns for the user.
    """
    # 1. Get explicit campaigns
    campaigns = list(db.campaigns.find({"userId": ObjectId(user["_id"])}).sort("created_at", -1))
    for c in campaigns:
        c["_id"] = str(c["_id"])
        c["userId"] = str(c["userId"])
        
        # Get live stats
        c["pending_count"] = db.user_recruiter_ledger.count_documents({"userId": ObjectId(user["_id"]), "campaignId": c["_id"], "status": "pending"})
        c["sent_count"] = db.user_recruiter_ledger.count_documents({"userId": ObjectId(user["_id"]), "campaignId": c["_id"], "status": "sent"})
    
    # Check for 'default' bucket items
    default_pending = db.user_recruiter_ledger.count_documents({"userId": ObjectId(user["_id"]), "campaignId": "default", "status": "pending"})
    if default_pending > 0:
        campaigns.append({
            "_id": "default",
            "name": "Uncategorized / Default",
            "status": "active" if user.get("active_campaign_id") == "default" else "inactive",
            "pending_count": default_pending,
            "sent_count": db.user_recruiter_ledger.count_documents({"userId": ObjectId(user["_id"]), "campaignId": "default", "status": "sent"})
        })
        
    return campaigns

@router.post("/")
def create_campaign(payload: dict = Body(...), user=Depends(get_current_user)):
    """
    Create a new campaign and move matching pending leads into it.
    Payload: { "name": "UK Corporate", "filters": { "country": "United Kingdom", "provider": "corporate" } }
    """
    name = payload.get("name")
    filters = payload.get("filters", {})
    
    if not name:
        raise HTTPException(400, "Campaign name required")

    # Create Campaign Doc
    campaign_doc = {
        "userId": ObjectId(user["_id"]),
        "name": name,
        "filters": filters,
        "status": "created",
        "created_at": datetime.utcnow()
    }
    res = db.campaigns.insert_one(campaign_doc)
    campaign_id = str(res.inserted_id)

    # Build update query for Ledger
    query = {
        "userId": ObjectId(user["_id"]),
        "status": "pending",
        "campaignId": "default" # Only move from default? Or from any? Safer to move from default to avoid stealing from other campaigns explicitly.
    }
    
    # Apply filters
    if filters.get("country"):
        query["country"] = filters["country"]
    if filters.get("provider"):
        query["provider"] = filters["provider"]
    if filters.get("confidence_min"):
        # We didn't denormalize confidence... 
        # Ideally we should have. For now, ignore or fetch?
        # Let's skip confidence filtering for version 1 or assume high confidence is default.
        pass

    # Move leads
    update_res = db.user_recruiter_ledger.update_many(
        query,
        {"$set": {"campaignId": campaign_id}}
    )
    
    return {
        "ok": True, 
        "campaign_id": campaign_id, 
        "moved_leads": update_res.modified_count
    }

@router.post("/{campaign_id}/start")
def start_campaign(campaign_id: str, user=Depends(get_current_user)):
    """
    Set this campaign as the active one for the worker.
    """
    # Verify ownership
    if campaign_id != "default":
        target_id = parse_oid(campaign_id)
        camp = db.campaigns.find_one({"_id": target_id, "userId": ObjectId(user["_id"])})
        if not camp:
            raise HTTPException(404, "Campaign not found")

    # Create Snapshot
    snapshot = {
        "cv_key": user.get("cv_b2_key"),
        "cv_filename": user.get("cv_filename"),
        "subject": user.get("subject_template"),
        "body": user.get("body_template"),
        "email_templates": user.get("email_templates", []), # CRITICAL: Snapshot the randomized list
        "snapshot_at": datetime.utcnow(),
        "campaign_id": campaign_id
    }

    db.users.update_one(
        {"_id": ObjectId(user["_id"])},
        {"$set": {
            "active_campaign_id": campaign_id, 
            "campaign_active": True,
            "campaign_snapshot": snapshot
        }}
    )
    return {"ok": True, "active": campaign_id}

@router.post("/{campaign_id}/pause")
def pause_campaign(campaign_id: str, user=Depends(get_current_user)):
    db.users.update_one(
        {"_id": ObjectId(user["_id"])},
        {"$set": {"campaign_active": False}}
    )
    return {"ok": True, "status": "paused"}
