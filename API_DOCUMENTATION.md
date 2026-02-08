# SaaS Sender - API Documentation

This document provides a comprehensive overview of the available API endpoints for the SaaS Sender application.

## **Authentication & Access Control**

The application uses two primary methods of authentication:
1.  **Session-Based**: Used for browser-based interactions (User Dashboard, Admin Panel). Requires a valid session cookie.
2.  **API Key**: Used for Admin API endpoints. Requires the `X-Admin-API-Key` header.

---

## **1. Public Endpoints**

| Endpoint | Method | Description | Rate Limit |
| :--- | :--- | :--- | :--- |
| `/signup` | POST | Registers a new user via Supabase. | 5 / min |
| `/login` | POST | Authenticates a user and starts a session. | 10 / min |
| `/admin-login` | POST | Authenticates an administrator for the web dashboard. | 5 / min |
| `/api/health` | GET | Returns the API health status. | None |

---

## **2. User Endpoints**
*Requires User Session Authentication.*

### **Outreach & Campaign**

| Endpoint | Method | Description | Rate Limit |
| :--- | :--- | :--- | :--- |
| `/api/campaign/toggle` | POST | Starts or pauses the email campaign. `{ "active": true/false }` | 10 / min |
| `/api/test_send` | POST | Sends a test email to a specific address. `{ "to_email": "..." }` | 5 / min |
| `/api/user/report` | GET | Fetches the last 50 processed email logs (Sent/Failed). | None |
| `/api/validate_credentials`| POST| Triggers a background validation of the Gmail Base64 credentials. | 5 / min |

### **Storage & CV Upload**

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/presign_upload` | POST | Generates a presigned URL for Backblaze B2 upload. |
| `/api/presign_complete` | POST | Confirms that a file has been successfully uploaded to B2. |

### **Payments**

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/payment/initiate` | POST | Generates a Webxpay payload and redirects to the payment gateway. |
| `/payment/callback` | GET/POST| Webxpay webhook/callback handler for updating subscription status. |

---

## **3. Admin API Endpoints**
*Requires `X-Admin-API-Key` header OR an Admin Session.*

### **User Management**

#### **List Users**
`GET /api/admin/users`
Returns a list of all registered users (sensitive fields like credentials are excluded).

#### **Create User**
`POST /api/admin/users`
Creates a user in both Supabase and the local MongoDB database.
- **Body**: `{ "email": "...", "password": "..." }`

#### **Update User**
`PATCH /api/admin/users/{user_id}`
Updates specific user fields such as `daily_limit`, `is_paid`, or `role`.
- **Body**: `{ "daily_limit": 500, "is_paid": true }`

#### **Delete User**
`DELETE /api/admin/users/{user_id}`
Deletes the user record from the local database.

---

## **4. System Statistics**
*Requires Admin Authentication.*

#### **Get Stats**
`GET /api/admin/stats`
Returns high-level system metrics including:
- Total Users
- Active Campaigns
- Paid Subscription Count
- Total Processed Recipients (Sent vs Failed)

---

## **5. Security Features**
- **CSRF Protection**: All `POST`, `PATCH`, and `DELETE` requests in the browser require a `csrf_token` (mapped to `csrf` in forms).
- **Encryption**: Sensitive Gmail credentials and OAuth tokens are stored using **Fernet (AES-128)** encryption.
- **Input Sanitization**: Email templates are sanitized using `bleach` to prevent XSS.
- **Strict Base64**: Credentials and Tokens must be valid Base64 encoded JSON strings.

---

## **Error Codes**
- `400 Bad Request`: Missing parameters or invalid data format.
- `401 Unauthorized`: Authentication required or session expired.
- `402 Payment Required`: Campaign cannot start without an active subscription.
- `403 Forbidden`: Admin role required.
- `429 Too Many Requests`: Rate limit exceeded.
- `500 Internal Server Error`: Backend or Database failure.
