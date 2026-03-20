# Nigeria AML Compliance Platform

Monorepo for an AML compliance platform (FastAPI + React/Vite) with Kafka, Postgres, Neo4j, Redis, and Nginx.

## Quick start (Docker)

1. Create a local `.env` from `.env.example`.
2. Start the stack:

```bash
docker compose up --build
```

- Frontend: `http://localhost/` (via Nginx) or `http://localhost:3000`
- Backend: `http://localhost:8000` (docs at `/docs`)
- Postgres: `localhost:5432`
- Neo4j: `http://localhost:7474` (bolt `localhost:7687`)
- Kafka: `localhost:9092`
- Redis: `localhost:6379`

## Local dev (no Docker)

### Backend

```bash
cd backend
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

If you want the frontend to call the backend directly (without proxy), set `VITE_API_URL`:

```bash
VITE_API_URL=http://localhost:8000/api/v1
```

## Auth (dev)

Current API routes require a Bearer token (JWT). For development, you can generate one in a Python shell:

```python
from app.core.security import create_access_token
print(create_access_token("dev-user"))
```

Then call APIs with:

`Authorization: Bearer <token>`

## 10-year transaction simulation (demo)

For training-style behaviour, the backend can synthesise multi-year histories **per customer profile** (salaried worker, student, SME trader, HNWI, merchant, importer), then inject AML scenarios (smurfing, layering, structuring, velocity bursts, wire spikes, round-trips, cash/profile mismatch, channel anomalies). Each transaction is scored with an Isolation Forest refitted periodically on **that customer’s prior** transactions only.

- **API:** `POST /api/v1/demo/simulate-temporal` with JSON body `{ "years": 10, "seed": 42, "clear_existing": true, "max_transactions": 100000, "refit_every": 500 }`
- **UI:** Dashboard → **Simulate 10-year history** (may take 1–2 minutes for a full run)

