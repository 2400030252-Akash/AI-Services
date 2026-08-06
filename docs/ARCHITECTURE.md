# AI Voice Calling Platform — Architecture Reference (Module 0)

> **Pinned.** Follow this document consistently across every module.
> Do not rename files, models, routes, or services. Extend without duplicating.

---

## Stack

| Layer       | Technology                                              |
|-------------|---------------------------------------------------------|
| Backend     | Python, FastAPI, SQLAlchemy 2.0 async, Pydantic v2      |
| Database    | Supabase Postgres                                       |
| AI          | NVIDIA API — DeepSeek model (OpenAI-compatible client)  |
| Telephony   | Twilio Voice API (webhook-based)                        |
| Frontend    | Next.js, admin-only login (JWT), no public signup       |
| Billing     | None in Phase 1                                         |

---

## Folder Structure

```
app/
  api/          # Route handlers (FastAPI routers)
  models/       # SQLAlchemy ORM models
  schemas/      # Pydantic v2 request/response schemas
  services/     # Business logic (ai_service, call_service, …)
  database/     # DB session & async engine setup
  core/         # Config (settings), security / JWT helpers
  utils/        # Shared utilities
tests/
```

---

## Database Tables

### `admin_users`
| Column       | Type      | Notes                        |
|--------------|-----------|------------------------------|
| id           | UUID PK   |                              |
| email        | VARCHAR   | unique, not null             |
| password_hash| VARCHAR   | bcrypt                       |
| created_at   | TIMESTAMP | server default now()         |
| updated_at   | TIMESTAMP | server default now()         |

### `calls`
| Column         | Type      | Notes                              |
|----------------|-----------|------------------------------------|
| id             | UUID PK   |                                    |
| call_sid       | VARCHAR   | Twilio CallSid, unique             |
| from_number    | VARCHAR   | caller phone number                |
| to_number      | VARCHAR   | dialled number                     |
| status         | VARCHAR   | queued/ringing/in-progress/completed/failed |
| direction      | VARCHAR   | inbound / outbound                 |
| duration       | INTEGER   | seconds, nullable                  |
| started_at     | TIMESTAMP | nullable                           |
| ended_at       | TIMESTAMP | nullable                           |
| created_at     | TIMESTAMP | server default now()               |

### `conversations`
| Column      | Type      | Notes                                      |
|-------------|-----------|--------------------------------------------|
| id          | UUID PK   |                                            |
| call_id     | UUID FK   | → calls.id                                 |
| role        | VARCHAR   | "user" or "assistant"                      |
| content     | TEXT      | message text                               |
| created_at  | TIMESTAMP | server default now()                       |

---

## API Conventions

### Error Response Format
```json
{
  "error": true,
  "message": "Human-readable description",
  "code": "SNAKE_CASE_ERROR_CODE"
}
```

### Authentication
- JWT bearer tokens issued on admin login.
- Protected routes use a FastAPI dependency (`get_current_admin`).
- No public signup endpoint.

### Naming
| Context           | Convention  |
|-------------------|-------------|
| Python (backend)  | snake_case  |
| JS/TS (frontend)  | camelCase   |
| DB columns        | snake_case  |
| API route paths   | kebab-case  |

---

## Key Services (to be built per module)

| Service         | Responsibility                                    |
|-----------------|---------------------------------------------------|
| `ai_service`    | NVIDIA/DeepSeek chat completions                  |
| `call_service`  | Twilio call lifecycle management                  |
| `auth_service`  | Admin login, JWT encode/decode                    |

---

## Module Build Log

| Module | Description         | Status  |
|--------|---------------------|---------|
| 0      | Architecture Reference | ✅ Pinned |
| …      | _To be added_       | —       |
