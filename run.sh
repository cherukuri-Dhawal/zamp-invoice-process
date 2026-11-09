#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Activate venv
source .venv/Scripts/activate

# Init DB
python -c "from app import db; db.init_db()"

# Start server (frontend + backend served together via FastAPI + Jinja2)
echo "Starting Zamp Invoice Processor at http://127.0.0.1:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
