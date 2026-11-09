# EvalForge

EvalForge is a workspace for evaluating LLM outputs. You build **datasets** of test cases, define **rubrics**, run **evaluations** against a real model, and review persisted results, failures and reports. It solves the "does this prompt/model actually still work?" problem with repeatable, auditable runs instead of ad-hoc spot checks.

![EvalForge dashboard](https://github.com/user-attachments/assets/70ee222b-cf7c-4f32-a5ac-9eaaf0576830)

## Features

- Account signup/login with JWT access tokens, Argon2id password hashing and rotating refresh tokens (HttpOnly cookie).
- Per-user data isolation (datasets, test cases, rubrics, runs, failures).
- Datasets, test cases and weighted-keyword rubrics.
- Real evaluation with **Ollama** (self-hosted) and **Groq** (hosted).
- Scoring methods: Exact Match, Keyword Match, Rubric Scoring.
- Results, failures, token usage and cost estimates persisted in the database; reports and PDF/CSV export.
- Alembic migrations, backend (pytest) and frontend (Vitest) tests, Docker/Compose, Vercel config, GitHub Actions CI.

## Mock vs Real evaluation

| | Demo / Mock | Live provider |
| --- | --- | --- |
| Calls a model | No | Yes (Ollama or Groq) |
| Results | Generated sample data | Actual model responses, persisted |
| Labelled in UI | "Demo / Mock" | "Live / Groq" or "Live / Ollama" |
| In reports/metrics | Excluded | Included |
| On provider failure | n/a | Error shown; never falls back to mock |

## Architecture

```
Browser (React + Vite)
   │  /api  (same origin on Vercel)
   ▼
FastAPI backend ──► PostgreSQL (SQLite for local dev/tests only)
   │
   ├──► Ollama  (OLLAMA_BASE_URL)
   └──► Groq    (GROQ_API_KEY)
```

Evaluations currently run sequentially inside one API request (no durable queue/worker). Keep datasets and timeouts within your host's request-duration limit; see [DEPLOYMENT.md](./DEPLOYMENT.md).

## Tech stack

React 18, TypeScript, Vite, Tailwind, TanStack Query, Recharts · FastAPI, SQLAlchemy, Alembic, Argon2 · PostgreSQL · Ollama, Groq · Vitest, pytest · Docker, Vercel, GitHub Actions.

## Local setup

```bash
cp .env.example .env          # set JWT_SECRET_KEY (>= 32 random bytes)
# AUTH_COOKIE_SECURE=false is for local HTTP only; use true on HTTPS
npm ci
python -m pip install -r backend/requirements.txt
python -m alembic -c alembic.ini upgrade head
python -m uvicorn backend.app.main:app --reload   # backend on :8000
npm run dev                                       # frontend on :5173
```

Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Providers

The Models page reports the providers configured on the backend and their configured model IDs. Ollama runs locally or on a separately reachable host; Groq is a hosted API provider. A configured provider/model is not proof that its credentials, network connection, or live inference are currently healthy—use the connection check and complete a real evaluation to verify it.

- **PostgreSQL**: set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/evalforge`. Required in production. See [DATABASE.md](./DATABASE.md).
- **Ollama**: install Ollama, `ollama pull llama3.2`, set `OLLAMA_BASE_URL` / `OLLAMA_MODEL`. See [OLLAMA.md](./OLLAMA.md).
- **Groq**: set `GROQ_API_KEY` (server-side only) and optionally `GROQ_MODEL`.

## Tests and build

```bash
npm run lint
npm run test:run
npm run build
pytest -q backend/tests/
```

## Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for Vercel (Services preset), required environment variables and the post-deploy checklist. Live application: [https://evale-forge.vercel.app/](https://evale-forge.vercel.app/).

Other docs: [AUTHENTICATION.md](./AUTHENTICATION.md), [OWNERSHIP.md](./OWNERSHIP.md), [DATABASE.md](./DATABASE.md).

## Skills demonstrated

- **Frontend:** React, TypeScript, Vite, TanStack Query, data visualization, reporting, and PDF/CSV export.
- **Backend:** Python, FastAPI, REST APIs, provider abstraction, and persistent evaluation workflows.
- **Data:** PostgreSQL, SQLAlchemy, Alembic migrations, datasets, test cases, rubrics, and evaluation records.
- **AI evaluation:** Ollama, Groq, Exact Match, Keyword Match, rubric scoring, repeatable test runs, and result analysis.
- **Security:** JWT authentication, Argon2id password hashing, rotating refresh tokens, and per-user data isolation.
- **Quality & delivery:** pytest, Vitest, Docker Compose, GitHub Actions CI, and Vercel configuration.

## Repository

- Source code: https://github.com/ADAMDEV01/evale-forge
