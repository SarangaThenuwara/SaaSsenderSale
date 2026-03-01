# SaaS Email Sender — Premium Edition

A professional email automation platform for job seekers to send personalized applications to recruiters at scale.

## Features

### 🔐 Authentication
- **Email/Password Authentication** via Supabase
- **Google OAuth SSO** for seamless sign-in
- **Session Security** with idle (30min) and absolute (24hr) timeouts
- **HTTPS Enforcement** in production

### 📧 Email Automation
- **Gmail Integration** using OAuth2
- **Personalized Templates** with dynamic variables (`{first_name}`)
- **CV Attachments** (5MB limit, auto-cleanup of old files)
- **Daily Sending Limits**: 240 emails/day per user
- **Smart Scheduling** with randomized delays (10-30s between sends)

### 👥 User Management
- **Soft Deletion** with 90-day grace period
- **Account Blocking** for admin control
- **Account Restoration** within grace period
- **Automatic Purge** of old deleted accounts

### 📊 Admin Dashboard
- **Global Activity Report** (last 100 sends)
- **User Management** (block, delete, restore, set limits)
- **CSV Export** of all users
- **Infrastructure Monitoring** (MongoDB, B2, Celery)
- **Payment Gateway Toggle** (Stripe integration)

### 💾 Storage & Infrastructure
- **Backblaze B2** for CV storage (S3-compatible)
- **MongoDB** for user and recipient data
- **Redis** for Celery task queue
- **Celery Beat** for scheduled tasks (daily resets, purges)

## Prerequisites

- **Python 3.11+**
- **Node.js** (for Tailwind CSS build)
- **MongoDB** (local or cloud)
- **Redis** (local or cloud)
- **Backblaze B2** account with S3 credentials
- **Supabase** project with Google OAuth enabled
- **Google Cloud** project with Gmail API enabled

## Installation

### 1. Clone Repository
```bash
git clone <your-repo-url>
cd <project-directory>
```

### 2. Install Python Dependencies
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Install Node Dependencies (for Tailwind)
```bash
npm install
```

### 4. Environment Variables

Create a `.env` file in the root directory:

```env
# Environment
APP_ENV=development  # or "production"
APP_URL=http://localhost:8000  # Your app URL

# Security Keys
SECRET_KEY=your-secret-key-min-32-chars
FERNET_KEY=your-fernet-key-base64-encoded

# Admin Credentials
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password
ADMIN_API_KEY=your-admin-api-key

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=saa_sender

# Redis & Celery
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Backblaze B2 (S3-compatible)
B2_S3_KEY_ID=your-b2-key-id
B2_S3_APP_KEY=your-b2-app-key
B2_S3_BUCKET=your-bucket-name
B2_S3_ENDPOINT=https://s3.us-west-000.backblazeb2.com

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key

# Gmail API
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.send

# Stripe (Payment Gateway)
STRIPE_SECRET_KEY=your-stripe-secret
STRIPE_PUBLIC_KEY=your-stripe-public
STRIPE_WEBHOOK_SECRET=your-webhook-secret
STRIPE_SUCCESS_URL=https://your-domain.com/payment/success
STRIPE_CANCEL_URL=https://your-domain.com/payment/cancel
STRIPE_CURRENCY=usd

# Optional
YOUTUBE_GUIDE_URL=https://youtube.com/your-guide
COLAB_GENERATOR_URL=https://colab.research.google.com/your-notebook
```

### 5. Generate Security Keys

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 6. Setup Supabase

1. Create a Supabase project at https://supabase.com
2. Enable Google OAuth:
   - Go to Authentication → Providers
   - Enable Google provider
   - Add your Google OAuth credentials
   - Set redirect URL: `http://localhost:8000/auth/callback` (update for production)
3. Copy your project URL and anon key to `.env`

### 7. Setup Google Cloud (Gmail API)

1. Create a project at https://console.cloud.google.com
2. Enable Gmail API
3. Create OAuth 2.0 credentials
4. Download `credentials.json` (users will upload this in the app)

### 8. Build Tailwind CSS

```bash
npm run build:css
# Or for development with watch mode:
npm run watch:css
```

## Running the Application

### Development Mode

**Terminal 1: FastAPI Server**
```bash
uvicorn app.main:app --host 0.0.0.0 --reload --port 8000
```

**Terminal 2: Celery Worker**
```bash
celery -A app.celery_app worker --loglevel=info -P solo
```

**Terminal 3: Celery Beat (Scheduler)**
```bash
celery -A app.celery_app beat --loglevel=info
```

### Production Mode

Use a process manager like **Supervisor** or **systemd**:

**FastAPI (with Gunicorn)**
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**Celery Worker**
```bash
celery -A app.celery_app worker --loglevel=info --concurrency=4
```

**Celery Beat**
```bash
celery -A app.celery_app beat --loglevel=info
```

## Project Structure

```
.
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration & env vars
│   ├── db.py                   # MongoDB connection
│   ├── celery_app.py           # Celery configuration
│   ├── send_worker.py          # Email sending tasks
│   ├── assigner.py             # Recipient assignment logic
│   ├── sync_pool.py            # HR pool synchronization
│   ├── user_helpers.py         # User management utilities
│   ├── gmail_helpers.py        # Gmail API integration
│   ├── storage_b2.py           # Backblaze B2 storage
│   ├── supabase_auth.py        # Supabase authentication
│   ├── utils.py                # Utility functions
│   ├── static/                 # CSS, JS, images
│   └── templates/              # Jinja2 templates
│       └── premium/            # Premium UI templates
├── .env                        # Environment variables
├── requirements.txt            # Python dependencies
├── package.json                # Node dependencies
├── tailwind.config.js          # Tailwind configuration
└── README.md                   # This file
```

## API Endpoints

### Public Routes
- `GET /` - Landing page
- `GET /login` - Login page
- `POST /login` - Login submission
- `GET /signup` - Signup page
- `POST /signup` - Signup submission
- `GET /login/google` - Google OAuth login
- `GET /auth/callback` - OAuth callback handler
- `GET /logout` - Logout

### User Routes (Authenticated)
- `GET /user/{user_id}/dashboard` - User dashboard
- `GET /user/{user_id}/settings` - Settings page
- `POST /api/presign_upload` - Get presigned upload URL
- `POST /api/presign_complete` - Complete CV upload
- `POST /api/test_send` - Send test email
- `POST /api/campaign/toggle` - Start/stop campaign
- `GET /api/user/report` - Get user's send report

### Admin Routes (Admin Only)
- `GET /admin` - Admin dashboard
- `POST /admin/assign` - Trigger recipient assignment
- `POST /admin/sync_pool` - Sync HR pool from main DB
- `PATCH /api/admin/users/{user_id}` - Update user
- `DELETE /api/admin/users/{user_id}` - Soft delete user
- `POST /api/admin/users/{user_id}/restore` - Restore deleted user
- `GET /api/admin/global_report` - Global activity report
- `GET /api/admin/export_users` - Export users to CSV
- `GET /api/admin/stats` - System statistics

## Scheduled Tasks (Celery Beat)

- **Daily Limit Reset** - Midnight (00:00) - Resets `daily_sent` to 0
- **Recipient Assignment** - Every 30 minutes - Auto-assigns pending recipients
- **HR Pool Sync** - Every hour - Syncs from main database
- **Purge Deleted Users** - Daily at 3 AM - Permanently deletes users after 90 days

## Rate Limits

- **Login**: 20/minute
- **Signup**: 10/minute
- **Test Send**: 10/minute
- **Campaign Toggle**: 20/minute
- **Credential Validation**: 10/minute

## Security Features

- **CSRF Protection** on all forms
- **Session Security** with timeouts
- **HTTPS Enforcement** in production
- **Secure Cookies** (httponly, SameSite=lax)
- **Rate Limiting** on sensitive endpoints
- **Password Hashing** via Supabase
- **Token Encryption** for refresh tokens

## Deployment Checklist

- [ ] Set `APP_ENV=production` in `.env`
- [ ] Generate strong `SECRET_KEY` and `FERNET_KEY`
- [ ] Update `APP_URL` to production domain
- [ ] Configure production MongoDB and Redis
- [ ] Setup SSL certificate (Let's Encrypt)
- [ ] Configure Supabase redirect URLs for production
- [ ] Setup process manager (Supervisor/systemd)
- [ ] Configure reverse proxy (Nginx/Caddy)
- [ ] Setup monitoring (Sentry, DataDog, etc.)
- [ ] Configure backups for MongoDB
- [ ] Test email sending in production

## Troubleshooting

### Emails Not Sending
1. Check Celery worker is running
2. Verify Gmail credentials are valid
3. Check `needs_reauth` flag in user document
4. Review Celery logs for errors

### Session Issues
1. Verify `SECRET_KEY` is set and consistent
2. Check Redis is running
3. Clear browser cookies

### Upload Failures
1. Verify B2 credentials are correct
2. Check bucket permissions
3. Ensure file is under 5MB

## License

Proprietary - All rights reserved

## Support

For support, contact: [your-email@example.com]