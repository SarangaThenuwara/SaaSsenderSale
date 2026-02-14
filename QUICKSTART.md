# Quick Start Checklist

## Initial Setup

### 1. Environment Setup
- [ ] Python 3.11+ installed
- [ ] Node.js installed
- [ ] MongoDB running (local or cloud)
- [ ] Redis running (local or cloud)

### 2. Install Dependencies
```bash
# Python
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Node
npm install
```

### 3. Generate Security Keys
```bash
# SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. Create .env File
Copy from `.env.example` or use the template in README.md

Required variables:
- [ ] `SECRET_KEY`
- [ ] `FERNET_KEY`
- [ ] `MONGODB_URI`
- [ ] `REDIS_URL`
- [ ] `SUPABASE_URL`
- [ ] `SUPABASE_ANON_KEY`
- [ ] `B2_S3_KEY_ID`
- [ ] `B2_S3_APP_KEY`
- [ ] `B2_S3_BUCKET`
- [ ] `B2_S3_ENDPOINT`
- [ ] `APP_URL`

### 5. External Services Setup

#### Supabase
- [ ] Create project at https://supabase.com
- [ ] Enable Google OAuth provider
- [ ] Add Google OAuth credentials
- [ ] Set redirect URL: `{APP_URL}/auth/callback`
- [ ] Copy project URL and anon key to `.env`

#### Google Cloud (Gmail API)
- [ ] Create project at https://console.cloud.google.com
- [ ] Enable Gmail API
- [ ] Create OAuth 2.0 credentials
- [ ] Download credentials.json (for users to upload)

#### Backblaze B2
- [ ] Create account at https://backblaze.com
- [ ] Create bucket
- [ ] Generate S3-compatible credentials
- [ ] Copy credentials to `.env`

### 6. Build Frontend
```bash
npm run build:css
```

## Running the Application

### Development Mode

**Terminal 1: FastAPI**
```bash
uvicorn app.main:app --host 0.0.0.0 --reload --port 8000
```

**Terminal 2: Celery Worker**
```bash
celery -A app.celery_app worker --loglevel=info -P solo
```

**Terminal 3: Celery Beat**
```bash
celery -A app.celery_app beat --loglevel=info
```

### Access Points
- Application: http://localhost:8000
- Admin: http://localhost:8000/admin
- Login: http://localhost:8000/login

## First-Time Setup

### 1. Create Admin User
Option A: Via Supabase Dashboard
- Create user with email/password
- Note the user ID

Option B: Via MongoDB
```javascript
db.users.updateOne(
  { email: "admin@example.com" },
  { $set: { role: "admin" } }
)
```

### 2. Test Google SSO
- [ ] Click "Continue with Google" on login page
- [ ] Verify redirect to Google
- [ ] Verify callback and session creation
- [ ] Check user created in MongoDB

### 3. Test Email Sending
- [ ] Upload credentials.json in settings
- [ ] Upload CV (under 5MB)
- [ ] Send test email
- [ ] Verify email received

### 4. Test Admin Features
- [ ] Access /admin
- [ ] View user list
- [ ] Block/unblock user
- [ ] Soft delete user
- [ ] Restore deleted user
- [ ] Export users to CSV

## Production Deployment

### Pre-Deployment
- [ ] Set `APP_ENV=production`
- [ ] Update `APP_URL` to production domain
- [ ] Generate strong production keys
- [ ] Setup production MongoDB
- [ ] Setup production Redis
- [ ] Configure SSL certificate

### Deployment Steps
- [ ] Deploy application code
- [ ] Setup process manager (Supervisor/systemd)
- [ ] Configure reverse proxy (Nginx/Caddy)
- [ ] Update Supabase redirect URLs
- [ ] Test all authentication flows
- [ ] Test email sending
- [ ] Monitor logs for errors

### Post-Deployment
- [ ] Setup monitoring (Sentry, etc.)
- [ ] Configure backups
- [ ] Test session timeouts
- [ ] Test rate limits
- [ ] Verify Celery tasks running

## Troubleshooting

### Application won't start
- Check MongoDB connection
- Check Redis connection
- Verify all required env vars are set
- Check SECRET_KEY is set

### Google SSO not working
- Verify Supabase Google provider enabled
- Check redirect URL matches exactly
- Verify APP_URL is correct
- Check browser console for errors

### Emails not sending
- Verify Celery worker running
- Check Gmail credentials valid
- Review Celery logs
- Check user's `needs_reauth` flag

### Session issues
- Verify SECRET_KEY consistent across restarts
- Check Redis is running
- Clear browser cookies
- Check session timeout settings

### File upload fails
- Verify B2 credentials correct
- Check bucket permissions
- Ensure file under 5MB
- Check browser console for errors

## Quick Commands

### View Celery Tasks
```bash
celery -A app.celery_app inspect active
```

### View Scheduled Tasks
```bash
celery -A app.celery_app inspect scheduled
```

### Purge Celery Queue
```bash
celery -A app.celery_app purge
```

### MongoDB User Count
```bash
mongosh
use saa_sender
db.users.countDocuments()
```

### Redis Check
```bash
redis-cli ping
```

## Support

For issues, refer to:
- README.md - Full documentation
- IMPLEMENTATION_SUMMARY.md - Technical details
- Logs in terminal windows
- MongoDB for data inspection
