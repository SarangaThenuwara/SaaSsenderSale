import logging
import re
import socket
import requests
from urllib.parse import urlparse
from app.db import db
from datetime import datetime

LOG = logging.getLogger(__name__)

# Free email providers list (expand as needed)
FREE_PROVIDERS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "protonmail.com"
}

# TLD to Country Mapping (simplified)
TLD_COUNTRY_MAP = {
    "uk": "United Kingdom",
    "de": "Germany",
    "fr": "France",
    "jp": "Japan",
    "cn": "China",
    "in": "India",
    "br": "Brazil",
    "ru": "Russia",
    "es": "Spain",
    "it": "Italy",
    "ca": "Canada",
    "au": "Australia",
    "nl": "Netherlands",
    "se": "Sweden",
    "no": "Norway",
    "dk": "Denmark",
    "fi": "Finland",
    "ch": "Switzerland",
    "at": "Austria",
    "be": "Belgium",
    "pt": "Portugal",
    "pl": "Poland",
    "cz": "Czech Republic",
    "hu": "Hungary",
    "ro": "Romania",
    "gr": "Greece",
    "tr": "Turkey",
    "ie": "Ireland",
    "nz": "New Zealand",
    "sg": "Singapore",
    "my": "Malaysia",
    "hk": "Hong Kong",
    "kr": "South Korea",
    "tw": "Taiwan",
    "th": "Thailand",
    "vn": "Vietnam",
    "id": "Indonesia",
    "ph": "Philippines",
    "mx": "Mexico",
    "ar": "Argentina",
    "cl": "Chile",
    "co": "Colombia",
    "za": "South Africa",
    "ae": "United Arab Emirates",
    "sa": "Saudi Arabia",
    "il": "Israel"
}

def normalize_domain(domain: str) -> str:
    domain = domain.lower().strip()
    if domain.startswith("http"):
        parsed = urlparse(domain)
        domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
    return domain

def get_tld(domain: str) -> str:
    parts = domain.split(".")
    if len(parts) > 1:
        return parts[-1]
    return ""

def classify_email_provider(domain: str):
    if domain in FREE_PROVIDERS:
        return "free"
    return "corporate"

def scrape_for_country_signals(domain: str):
    # This is a placeholder for actual scraping logic.
    # In a real implementation, you would:
    # 1. request the homepage
    # 2. look for phone prefixes (e.g., +44 for UK)
    # 3. look for address keywords (e.g., "London", "Berlin")
    # 4. look for html lang attribute
    
    # Simple check for now: try to resolve IP and geo-locate
    try:
        ip = socket.gethostbyname(domain)
        # Placeholder: In production, integrate with a GeoIP DB or API
        # response = requests.get(f"http://ip-api.com/json/{ip}", timeout=2)
        # if response.status_code == 200:
        #     data = response.json()
        #     return data.get("country"), 0.6  # Medium confidence
    except Exception:
        pass
    
    return "unknown", 0.0

def detect_country(domain: str):
    domain = normalize_domain(domain)
    
    # 1. Check cache first
    cached = db.domain_country_cache.find_one({"domain": domain})
    if cached:
        return {
            "country": cached.get("detectedCountry"),
            "confidence": cached.get("confidence"),
            "source": "cache"
        }

    # 2. Check TLD
    tld = get_tld(domain)
    if tld in TLD_COUNTRY_MAP:
        result = {
            "country": TLD_COUNTRY_MAP[tld],
            "confidence": 0.9,
            "source": "tld"
        }
        # Cache filtering result
        db.domain_country_cache.update_one(
            {"domain": domain}, 
            {"$set": {"detectedCountry": result["country"], "confidence": result["confidence"], "updated_at": datetime.utcnow()}},
            upsert=True
        )
        return result

    # 3. Fallback (e.g., .com, .net, .io) -> Scrape/IP
    # For now default to 'global' if scraping not implemented fully
    country, confidence = ("Global", 0.5) 
    
    # Cache result
    db.domain_country_cache.update_one(
        {"domain": domain}, 
        {"$set": {"detectedCountry": country, "confidence": confidence, "updated_at": datetime.utcnow()}},
        upsert=True
    )

    return {
        "country": country,
        "confidence": confidence,
        "source": "fallback"
    }

def enrich_recruiter(email: str):
    domain = email.split("@")[-1]
    provider_type = classify_email_provider(domain)
    
    if provider_type == "free":
        country_info = {"country": "Global", "confidence": 1.0, "source": "free_provider"}
    else:
        country_info = detect_country(domain)
        
    return {
        "domain": domain,
        "providerType": provider_type,
        "detectedCountry": country_info["country"],
        "confidence": country_info["confidence"],
        "health": "good", # Default health
        "bounceCount": 0,
        "enrichmentMetadata": {
            "source": country_info.get("source")
        }
    }
