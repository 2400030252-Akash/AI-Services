# AI Voice Calling Platform

> **Phase 1** — Admin-only backend API for AI-powered voice calls via Twilio + NVIDIA DeepSeek.

---

## Tech Stack

| Layer       | Technology                                         |
|-------------|----------------------------------------------------|
| Backend     | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2  |
| Database    | Supabase Postgres (asyncpg driver)                 |
| AI          | NVIDIA API — DeepSeek model (OpenAI-compatible)    |
| Telephony   | Twilio Voice API (webhook-based)                   |
| Frontend    | Next.js — admin login only, JWT auth               |

---

## Project Structure

```
app/
  api/          Route handlers (FastAPI routers) + deps.py
  models/       SQLAlchemy ORM models
  schemas/      Pydantic v2 request/response schemas
  services/     Business logic (ai_service, call_service, …)
  database/     Async engine, session factory, base classes
  core/         Config (pydantic-settings), JWT/bcrypt security
  utils/        Shared helpers (error responses, etc.)
tests/
Dockerfile
requirements.txt
.env.example
```

---

## Getting Started

### 1. Clone & create virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

Open `.env` and fill in:
- `DATABASE_URL` — Supabase Postgres connection string (asyncpg)
- `SUPABASE_URL` / `SUPABASE_KEY` — from your Supabase project settings
- `JWT_SECRET` — a long random string
- `NVIDIA_API_KEY` — from NVIDIA Developer portal
- `TWILIO_*` — from your Twilio Console
- `FRONTEND_URL` — your Next.js origin (default `http://localhost:3000`)

### 4. Run development server

```bash
uvicorn app.main:app --reload
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
Health check: [http://localhost:8000/health](http://localhost:8000/health)

---

## Docker

```bash
# Build image
docker build -t ai-voice-api .

# Run (pass all required env vars)
docker run -p 8000:8000 --env-file .env ai-voice-api
```

---

## API Conventions

### Error format (all error responses)
```json
{
  "error": true,
  "message": "Human-readable description",
  "code": "SNAKE_CASE_ERROR_CODE"
}
```

### Authentication
- JWT Bearer token required on all protected routes.
- Token issued via `POST /api/v1/auth/login`.
- No public signup — admin accounts are seeded manually.

---

## Module Build Status

| Module | Description                  | Status       |
|--------|------------------------------|--------------|
| 0      | Architecture Reference       | ✅ Done       |
| 1      | Project Scaffold             | ✅ Done       |
| 2      | Auth (login, JWT)            | ⏳ Pending    |
| 3      | Calls API + Twilio webhooks  | ⏳ Pending    |
| 4      | AI Conversation Service      | ⏳ Pending    |
| 5      | Admin Dashboard (Next.js)    | ⏳ Pending    |
