# SaaS Sender - v2.0 Architecture

The application has been upgraded to a scalable SaaS platform with the following core components:

## 1. Database Architecture (MongoDB)
*   **Recruiters**: Global list with `detectedCountry`, `providerType` (corporate/free), `health` (good/risky/dead), `bounceCount`.
*   **User Recruiter Ledger**: Tracks per-user interaction (`userId`, `recruiterId`, `status`, `campaignId`). Prevents duplicates and enables massive scale.
*   **Domain Country Cache**: Stores domain -> country detection results to speed up ingestion.
*   **Global Suppression**: Blacklist for hard bounces and spam traps.

## 2. Core Services (`app/services/`)
*   **Country Detection**: (`country_detection.py`) Automatically detects country from domain TLD, Free Provider list, and DNS/Scraping clues.
*   **Recruiter Manager**: (`recruiter_manager.py`) Handles bulk ingestion and the **Weekly Recruiter Update Pipeline** to propagate new leads to user ledgers efficiently.
*   **Bounce Monitor**: (`bounce_monitor.py`) Scans user inboxes for bounces, updates global recruiter health, and pauses campaigns if bounce rates spike (>5%).

## 3. Worker logic (`app/send_worker.py`)
*   Refactored to check `Ledger` status, `Recruiter` health, and `Global Suppression` list before sending.
*   Respects per-user daily limits (240 emails/day).
*   Uses randomized sending intervals.
*   Handles Campaign ID filtering for targeted outreach.

## 4. Admin Dashboard (`app/routers/admin.py` & templates)
*   **Unified Management Console**:
    *   **Architecture**: Single-page high-performance dashboard (`admin.html`) with a refined tabbed interface.
    *   **Navigation**: Top-aligned persistent tabs for instant switching between modules (User Control, Recruiter Pool, Deliverability, Node Console).
*   **Security & DNS Validation**:
    *   **IP Intelligence**: Automatic logging of user login IP addresses; displayed in User Directory and Live Monitor for fraud detection.
    *   **DNS Verification**: One-click deep-check for user domains (MX, SPF, DMARC) to ensure high deliverability before campaigns start.
*   **Modules**:
    *   **User Control**: Full directory with search, block/unblock, limit management, and IP tracking.
    *   **Node Console**: Command center for Celery worker nodes (Pause/Resume) and real-time Redis queue depth monitoring.
*   **Infrastructure**: Real-time System Resources (CPU, RAM, Disk) and Network Bandwidth monitoring.

## 5. Periodic Tasks (`app/tasks.py` & `app/celery_app.py`)
*   **Weekly Update**: Every Monday at 2 AM.
*   **Bounce Scan**: Hourly checks for all users.
*   **Daily Reset**: Resets user limits at midnight.
*   **Purge Deleted Users**: Daily cleanup.

## 6. Campaign Management (`app/routers/campaigns.py`)
*   **Endpoints**:
    *   `POST /api/campaigns`: Create new campaign, applying filters to default pending leads.
    *   `GET /api/campaigns`: List user campaigns with real-time stats.
    *   `POST /api/campaigns/{id}/start`: Activate a specific campaign for the worker.
*   **UI**: [REMOVED] Campaign Segments feature retracted per user request. Simplified outreach back to global toggle.

## 7. Storage (`app/storage_b2.py`)
*   Updated to use `userId` based paths for organized CV storage.
*   Secure presigned URL generation with user context.

## Next Steps
1.  **Ingestion**: Connect the `Weekly Update` task to a real data source (currently a placeholder).
2.  **Testing**: Verify end-to-end flow with real email sending and bounce processing.
3.  **Refinement**: Enhance "Recruiter Review" UI for manual country correction by admins.
