from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from datetime import datetime

router = APIRouter(prefix="/resources", tags=["Knowledge Hub"])
templates = Jinja2Templates(directory="app/templates")

# Curated high-SEO content for Knowledge Hub
GUIDES = [
    {
        "slug": "byok-gmail-api-setup",
        "title": "Mastering BYOK: How to Securely Connect Your Gmail API",
        "excerpt": "Learn the step-by-step process of creating a Google Cloud Project and generating OAuth2 credentials for privacy-first email automation.",
        "category": "Setup",
        "author": "SaaS Sender Security Team",
        "publish_date": "2026-02-15",
        "reading_time": "6 min",
        "content_template": "guides/byok_setup.html",
        "meta_desc": "Step-by-step guide on setting up Bring Your Own Key (BYOK) for Gmail API outreach. Secure your credentials and protect your privacy."
    },
    {
        "slug": "avoid-spam-filters-with-spintax",
        "title": "Zero-Grip Outreach: Avoiding Spam Filters with Spintax and Randomization",
        "excerpt": "Discover how randomized template rotation and spintax formatting can protect your sender reputation in 2026.",
        "category": "Deliverability",
        "author": "Deliverability Experts",
        "publish_date": "2026-02-18",
        "reading_time": "8 min",
        "content_template": "guides/spintax_guide.html",
        "meta_desc": "Learn how to use spintax and randomized email templates to avoid Gmail's spam filters and maintain a high sender reputation."
    },
    {
        "slug": "domain-authentication-for-job-seekers",
        "title": "Email Deliverability 101: SPF, DKIM, and DMARC for Job Seekers",
        "excerpt": "Why your CV might be landing in the spam folder and how to fix your domain authentication to reach HR managers 100% of the time.",
        "category": "Technical",
        "author": "Deliverability Expert",
        "publish_date": "2026-02-21",
        "reading_time": "12 min",
        "content_template": "guides/domain_auth.html",
        "meta_desc": "Technical guide on setting up SPF, DKIM, and DMARC for professional email accounts to ensure job applications reach the inbox."
    },
    {
        "slug": "uae-job-search-automation",
        "title": "Cracking the UAE Job Market: A Guide to Automated Outreach",
        "excerpt": "How to navigate Dubai and Abu Dhabi's competitive recruitment landscape using personalized, high-deliverability email automation.",
        "category": "Recruitment",
        "author": "Career Strategist (UAE)",
        "publish_date": "2026-02-21",
        "reading_time": "9 min",
        "content_template": "guides/uae_job_search.html",
        "meta_desc": "Strategic guide for job applicants in the UAE. Learn how to use automated email outreach safely to reach HR managers in Dubai and Abu Dhabi."
    },
    {
        "slug": "privacy-first-outreach-strategy",
        "title": "Why Privacy-First Outreach Matters for Executive Job Seekers",
        "excerpt": "Protecting your professional reputation and document security during a high-stakes job search in the Gulf region.",
        "category": "Strategy",
        "author": "Privacy Advocate",
        "publish_date": "2026-02-20",
        "reading_time": "5 min",
        "content_template": "guides/privacy_strategy.html",
        "meta_desc": "How privacy-first email automation leads to better results and compliance with GDPR/CCPA in enterprise sales outreach."
    },
    {
        "slug": "gmail-api-vs-smtp",
        "title": "Gmail API vs SMTP Relay: Which is Better for Cold Outreach?",
        "excerpt": "A technical comparison of email protocols. Learn why API-based dispatching is the gold standard for high-deliverability outreach.",
        "category": "Infrastructure",
        "author": "SaaS Sender Engineering",
        "publish_date": "2026-02-21",
        "reading_time": "10 min",
        "content_template": "guides/gmail_api_vs_smtp.html",
        "meta_desc": "Comparing Gmail API vs SMTP for cold email outreach. Discover the security, speed, and deliverability benefits of API-based automation."
    },
    {
        "slug": "outreach-infrastructure-faq",
        "title": "Outreach Ethics & Infrastructure: The 2026 Structured FAQ",
        "excerpt": "Clear answers to the most common questions about BYOK, encryption, and the legality of automated email systems.",
        "category": "Security",
        "author": "Compliance Officer",
        "publish_date": "2026-02-21",
        "reading_time": "7 min",
        "content_template": "guides/outreach_faq.html",
        "meta_desc": "Frequently asked questions about secure email outreach, BYOK architecture, and data privacy compliance."
    },
    {
        "slug": "effective-recruiter-outreach",
        "title": "The Anatomy of a Perfect Recruiter Email: Getting Noticed in 2026",
        "excerpt": "Strategies for crafting concise, personalized, and high-impact emails that stand out in a recruiter's crowded inbox.",
        "category": "Strategy",
        "author": "L. Inkedin",
        "publish_date": "2026-02-22",
        "reading_time": "5 min",
        "content_template": "guides/effective-recruiter-outreach.html",
        "meta_desc": "Master the art of emailing recruiters. Learn about subject line optimization, personalization techniques, and effective call-to-actions for job seekers."
    }
]

@router.get("/", response_class=HTMLResponse)
async def knowledge_index(request: Request):
    return templates.TemplateResponse("premium/knowledge_index.html", {
        "request": request,
        "guides": GUIDES,
        "title": "Knowledge Hub | SaaS Email Sender Resources"
    })

@router.get("/{slug}", response_class=HTMLResponse)
async def knowledge_detail(request: Request, slug: str):
    guide = next((g for g in GUIDES if g["slug"] == slug), None)
    if not guide:
        raise HTTPException(status_code=404, detail="Resource not found")
        
    return templates.TemplateResponse("premium/knowledge_detail.html", {
        "request": request,
        "guide": guide,
        "title": f"{guide['title']} | Resources"
    })

@router.get("/tools/spintax-tester", response_class=HTMLResponse)
async def spintax_tester(request: Request):
    return templates.TemplateResponse("premium/spintax_tester.html", {
        "request": request,
        "title": "Free Spintax Tester | SaaS Email Sender Tools",
        "meta_desc": "Test your email randomization with our free interactive Spintax tool. Perfect for optimizing cold outreach deliverability."
    })
