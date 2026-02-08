#!/usr/bin/env bash
set -e

# Replit Autoscale expects the app to listen on the PORT environment variable.
# Host must be 0.0.0.0 for external access.
PORT=${PORT:-8000}

echo "----------------------------------------"
echo "Starting SaaS Sender Application..."
echo "Port: $PORT"
echo "----------------------------------------"

# exec ensures the app receives signals (like SIGTERM) directly from the OS/Replit
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
