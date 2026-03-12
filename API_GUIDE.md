# 🚀 SaaS Email Sender — Master API Specification v2.0

This document is the **definitive technical authority** on the SaaS Email Sender (Premium Edition) API. It covers every endpoint across the main application, specialized routers, and administrative modules.

---

## 🔐 Global Security Standards
Every endpoint in this API adheres to the following security protocols:
- **Transport Security**: TLS 1.3 enforced via HSTS in production.
- **Session Layer**: Standardized idle (30m) and absolute (24h) timeouts.
- **CSRF Defense**: All mutative methods (`POST`, `PATCH`, `DELETE`) require the `X-CSRF-Token` header.
- **Production Flags**: `HttpOnly`, `Secure`, and `__Host-` prefix on all session cookies in production.

---

## 🔑 1. Authentication & Identity
**Base Path:** `/` | **Security:** Public / Session

| Method | Endpoint | Description | Throttling |
| :--- | :--- | :--- | :--- |
| `POST` | `/signup` | Create a new user account via Supabase. | 10/min |
| `POST` | `/login` | Authenticate with email/password. Regenerates session ID. | 20/min |
| `GET` | `/login/google` | Initiates the Google OAuth2 SSO flow. | 20/min |
| `GET` | `/login/callback`| Handles the response from Google/Supabase. | 20/min |
| `GET` | `/logout` | Destroys the current session and clears cookies. | - |

---

## 👤 2. User Dashboard & Tooling
**Security:** Authenticated Session Required

### 🏠 Core Dashboard
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/user/{id}/dashboard` | Main UI data aggregator (Campaign stats, file status). |
| `GET` | `/api/user/report` | Fetch the last 100 delivery attempts. |

### 📁 Document Management (Backblaze B2)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/presign_upload` | Generates a secure, temporary B2 URL for CV uploads. |
| `POST` | `/api/presign_complete`| Confirms upload and finalizes the file key in DB. |

### 📧 Connectivity & Settings
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/settings` | Update templates and Gmail keys. Requires password if keys change. |
| `POST` | `/api/validate_credentials` | Live validation of Gmail credentials via `google-auth`. |
| `POST` | `/api/test_send` | Sends a one-off test email to proof templates. |
| `POST` | `/api/campaign/toggle` | Master switch for background sending worker. |

---

## 🎯 3. Campaigns & Ledgers
**Prefix:** `/api/campaigns` | **Security:** Ownership Verified

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | List all campaigns with real-time lead status metrics. |
| `POST` | `/` | Logic-gate: Creates a campaign and pulls matching leads. |
| `GET` | `/filters` | Dynamically returns available Country/Provider options from your pool. |
| `POST` | `/{id}/start` | **Snapshot & Start**: Locks templates and activates the send worker. |
| `POST` | `/{id}/pause` | Deactivates the worker; leads remain in current campaign. |

---

## 💳 4. Billing & Payments
**Base Path:** `/api` | **Security:** Stripe Verified

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/payment` | Initiates a Stripe Checkout session for a subscription. |
| `GET` | `/payment/success`| Redirect destination for successful payments. |
| `GET` | `/payment/cancel` | Redirect destination for abandoned checkouts. |
| `GET` | `/api/user/portal` | Generates an authenticated link to the **Stripe Customer Portal**. |
| `POST`| `/api/payment/webhook`| Handles subscription updates (async) from Stripe Servers. |

---

## 🛡️ 5. Hardened Admin API
**Prefix:** `/api/admin` | **Security:** Admin Role + Brute-Force Protection

### 🔬 Telemetry & Health
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/infra` | Live hardware stats (CPU, RAM, Mongo/Redis latency). |
| `GET` | `/security_check`| Proactive vulnerability audit of production keys. |
| `GET` | `/failure_report`| Lists users with invalid keys or blocked campaigns. |
| `GET` | `/audit_logs` | Cryptographic history of all administrative actions. |

### 👑 User & Platform Management
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/users` | Create or update users (Manage limits, roles, blocking). |
| `DELETE`| `/users/{id}` | Hidden Soft-Delete (90-day grace period). |
| `POST` | `/users/{id}/restore`| Immediate restoration of a soft-deleted account. |
| `GET` | `/export_users` | Generates a security-sanitized CSV of the user database. |
| `POST` | `/sync_pool` | Main Recruiter DB -> Local Recruiter Pool sync. |
| `POST` | `/assign` | Trigger manual distribution of leads to active users. |

---

## 📚 6. Knowledge & SEO
**Prefix:** `/resources` | **Security:** Public / SEO Optimized

- `GET /` - Catalog of 2026 job search and email automation guides.
- `GET /{slug}` - Deep-dive articles with specialized metadata.
- `GET /tools/spintax-tester` - Interative tool for email randomization testing.

---
*Generated: 2026-03-12 | SaaS Sender Engineering | Final Verified Build*
