# SaaS Email Sender — Premium Edition

A professional, high-margin email automation platform for job seekers to send personalized applications to recruiters at scale. Designed with a privacy-first **Bring Your Own Key (BYOK)** architecture.

## 💎 The BYOK Advantage
Unlike traditional email platforms, this SaaS requires users to provide their own Gmail API keys.
- **Zero Delivery Costs**: You don't pay for SMTP relays or per-email fees.
- **Ultimate Privacy**: Emails are sent directly from the user's account, increasing trust and deliverability.
- **High Margins**: Typical SaaS costs are ~10%; BYOK costs are ~1%, making this a highly profitable "Earnings Machine."

## Features

### 🔐 Authentication & Identity
- **Supabase Integration**: Robust Email/Password auth and Google OAuth SSO.
- **Security Hardening**: Session idle timeouts (30m), absolute timeouts (24h), and secure session fixation protection.
- **Enterprise MFA Ready**: Built on Supabase, allowing easy upgrade to multi-factor authentication.

### 📧 Email Automation
- **Gmail API Outreach**: Native integration for maximum inbox placement.
- **Template Spintax**: Integrated `{Hello|Hi|Greetings}` randomization to avoid spam filters.
- **Dynamic Snapshots**: Campaigns take a snapshot of CVs and templates at start time for consistent delivery.
- **Smart Throttling**: Human-like randomized delays (10-30s) and progressive daily limits.

### 📊 Hardened Admin API
- **Encrypted Communication**: Sensitive responses are encrypted before being sent to the admin client.
- **Infra Monitoring**: Real-time stats for CPU, Memory, MongoDB, Redis, and Celery.
- **Audit Logging**: Every admin action (block, delete, sync) is cryptographically logged.
- **Rate Limited**: Built-in brute-force protection for all administrative actions.

### 🛡️ Security Best Practices (Standard)
- **Strict Headers**: HSTS, CSP (with nonce), COOP, CORP, and X-Content-Type-Options enforced.
- **Cookie Security**: `__Host-` prefix, `HttpOnly`, `Secure`, and `SameSite=Lax` for production.
- **XSS Prevention**: Strict input sanitization via `bleach` and `textContent` rendering on all user-controlled tools.
- **CSRF Protection**: Synchronizer Token Pattern on all POST/PATCH/DELETE requests.
- **No Tracebacks**: Global exception handlers prevent sensitive path or variable leakage to end users.

## Prerequisites
- **Python 3.11+**
- **Node.js** (for Tailwind CSS build)
- **MongoDB** (local or cloud)
- **Redis** (local or cloud)

## Installation & Setup

1. **Clone & Env**: Copy `.env.example` to `.env` and fill in secrets.
2. **Security Keys**: Generate `SECRET_KEY` and `FERNET_KEY` (see scripts below).
3. **Database**: Point `MONGODB_URI` and `REDIS_URL` to your instances.
4. **Cloud Assets**: Configure Supabase (Auth), Google Cloud (Gmail API), and Backblaze B2 (Storage).

### Secret Generation
```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate FERNET_KEY (Required for Credential Encryption)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Running the Application

### Development
```bash
# Server
uvicorn app.main:app --reload

# Worker
celery -A app.celery_app worker --loglevel=info -P solo

# Scheduler
celery -A app.celery_app beat --loglevel=info
```

## API Documentation

### Public / User
- `GET /` - Professional Landing
- `GET /resources` - Knowledge Hub (SEO Specialized)
- `GET /user/dashboard` - Campaign monitoring & CV Management
- `POST /api/test_send` - Direct Gmail API verification

### Admin (Secured)
- `GET /api/admin/stats` - Cluster health & resource metrics
- `GET /api/admin/audit_logs` - Action history
- `POST /api/admin/sync_pool` - Main DB recruiter synchronization

## License
Proprietary - SaaS Sale License

## Support
For technical support or feature requests, contact: [your-email@example.com]