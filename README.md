# SkillOS

Capture how experts perform practical tasks, turn that into executable skill graphs, guide learners through them with camera and measurement evidence, and verify competency from that evidence.

First domain: **low-voltage (12 V) solar lighting installation and troubleshooting** on isolated training rigs.

> ⚠️ The seeded solar procedures are demo content and **have not been reviewed by a qualified solar technician**. Have them reviewed before anyone uses them on real equipment. SkillOS is scoped to isolated low-voltage DC training systems; the validator rejects procedures that mention mains voltage.

## Status

| Area | State |
|---|---|
| Skill graph schema, validator, NetworkX graph | ✅ working, tested |
| Session state machine + orchestrator | ✅ working, tested |
| Deterministic evidence validation (VERIFIED / UNCERTAIN / FAILED) | ✅ working, tested |
| Competency scoring + progression levels | ✅ working, tested |
| REST API (auth, RBAC, org isolation, skills, videos, sessions, assessments) | ✅ working, tested |
| Video → skill extraction pipeline (FFmpeg + OpenAI) | ✅ implemented; needs `OPENAI_API_KEY`, `OPENAI_MODEL` and FFmpeg to run. Not yet tested against a real video |
| Camera observation (OpenAI vision) | ✅ implemented; needs OpenAI config. Tests use a stub |
| YOLO detector | interface only; needs weights trained on solar components |
| React web app (13 pages: landing, auth, dashboards, library, workspace with camera, capture, review/graph editor, reports, competency, org, admin) | ✅ builds and runs against the API; camera flow needs a real browser + OpenAI config |
| Android app (Kotlin) | ⏳ planned |
| Alembic migrations | ⏳ planned (tables are created on startup for now) |

## How it decides things

AI proposes, deterministic code decides. The model drafts skill graphs and describes camera frames. Rules in `backend/app/validation/evidence.py` decide every verdict, `backend/app/sessions/orchestrator.py` is the only code that moves a session, and every score in a report is computed from the session's event log. See [docs/architecture.md](docs/architecture.md).

Key guarantees, each covered by tests:

- A safety-critical step never passes on learner confirmation alone, and polarity must be measured, not just photographed.
- If the camera can't see something, the result is UNCERTAIN, never VERIFIED.
- Object detection alone never verifies a step.
- Clients cannot submit visual evidence directly. It is produced on the server from an uploaded frame.
- A reversed-polarity reading blocks the session (`BLOCKED_BY_SAFETY`) until a correct reading is submitted.
- Generated skills are saved as drafts. Publishing needs zero validator errors and an expert who acknowledges every warning.

## Run locally (no Docker)

Requires Python 3.12+.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the interactive API docs. By default this uses SQLite and seeds a demo organization:

| Account | Role |
|---|---|
| admin@demo.skillos.dev | admin |
| expert@demo.skillos.dev | expert |
| learner@demo.skillos.dev, learner2@demo.skillos.dev | learner |

Password for all: `skillos-demo-2026`

## Run the web app

Requires Node 20+. With the API running on port 8000:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` (including WebSockets) to the API.

## Run with Docker

```bash
cp .env.example .env    # fill in values
docker compose up --build
```

This starts PostgreSQL, Redis, the API on port 8000, and an RQ worker for video jobs. FFmpeg is included in the image.

## Tests

```bash
cd backend
python -m pytest -q
```

## Configuration

See [.env.example](.env.example). Without OpenAI settings, extraction returns `503 AI is not configured`, camera observation returns 503, and the assistant shows the approved step text with a label saying so. `GET /api/v1/system/capabilities` reports what is configured.

## Repository layout

```
backend/app/
  core/         config, db, security, auth deps, rate limit, audit
  models/       SQLAlchemy models
  api/v1/       routers
  skillgraph/   schema, validator, graph, publish service
  sessions/     state machine, orchestrator, websocket hub
  validation/   evidence evaluation
  assessment/   scoring and competency
  ai/           OpenAI gateway, extraction, observation, instruction
  video/        FFmpeg processing, extraction pipeline
  cv/           detector interface
  seed/         demo data and the three solar modules
frontend/src/
  api/          typed client with token refresh
  auth/         auth context
  components/   app shell and UI primitives
  features/     learning workspace panels
  hooks/        data, camera and live-session hooks
  pages/        routes
docs/           architecture
```
