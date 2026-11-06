# Production deployment

## Current deployment shape: Vercel Services

This repository is configured as a Vercel multi-service project:

- `app`: Vite frontend at the root path (`/`).
- `backend`: FastAPI service rooted at `backend/`, with entrypoint
  `main:app`.
- Top-level rewrites route `/api` and `/api/*` to the backend service, then
  route remaining paths to the frontend.

The Vercel project framework must be set to **Services**. The `services` key
and the project-level Services framework setting are both required. Keep the
specific `/api` rewrites before the frontend catch-all. Vercel forwards the
original request path, so FastAPI routes must continue to include the `/api`
prefix; the current backend routes do.

Vercel Services are currently documented as beta. Each service follows Vercel
Function runtime limits. This is a supported deployment shape, but it does not
make long-running evaluations unlimited or durable.

## Runtime suitability and evaluation limits

The current evaluation endpoint processes test cases sequentially and the
provider request timeout defaults to 120 seconds. A dataset with several slow
cases can exceed a serverless request's configured maximum duration. The
service's `maxDuration` can be configured within the limits of the Vercel
plan, but increasing it does not provide durable background execution.

For larger or production-critical workloads, move evaluation execution to a
durable job queue and worker on a long-running container service. That queue
and worker are not implemented by this repository today. Until then, keep
datasets and provider timeouts within the actual Vercel duration budget and
verify the deployed endpoint with representative workloads.

## Vercel project setup

1. Push this repository to your new GitHub repository, import it in Vercel
   (**Add New → Project**), and deploy the `main` branch.
2. Set the project's Framework Preset to **Services** (not Vite).
3. Keep the project root at the repository root (`./`); the service roots
   are defined in `vercel.json`.
4. Confirm the build detects both `app` and `backend` services.
5. Configure the environment variables below for the appropriate Production
   and Preview environments, then redeploy after changing build-time values.

The frontend uses `VITE_API_URL` at build time. For this same-domain Services
setup, set `VITE_API_URL=/api`. Do not leave it unset: the source fallback is
`http://localhost:8000/api`, which points a deployed visitor's browser at that
visitor's own machine.

## Required backend environment

Set these in the Vercel project's Environment Variables. Use Production for
the production deployment and Preview only when its database and secrets are
intentionally configured separately.

| Variable | Required value / purpose |
| --- | --- |
| `FASTAPI_ENV` | `production`; enables fail-fast production checks and prevents loading a local dotenv file. |
| `DATABASE_URL` | Persistent managed PostgreSQL URL. Plain `postgresql://` is normalized to `postgresql+psycopg://`. |
| `JWT_SECRET_KEY` | Unique cryptographically random secret of at least 32 bytes. Generate it locally; never commit it or paste it into logs/issues. |
| `AUTH_COOKIE_SECURE` | `true` for HTTPS production cookies. |
| `LOGIN_RATE_LIMIT_MAX_ATTEMPTS` | Failed/successful login attempts allowed per email/IP bucket; defaults to 10. Successful authentication clears the bucket. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | Login rate-limit window in seconds; defaults to 900. Buckets are stored in PostgreSQL and shared across function instances. |
| `CORS_ALLOWED_ORIGINS` | Exact frontend origin(s) of your real deployment, e.g. `https://your-project.vercel.app`; comma-separate additional trusted origins. Required in production, no built-in default domain is added, and `*` is rejected. |
| `VITE_API_URL` | `/api` for the same-domain frontend/backend Services deployment. This is public and is embedded at frontend build time. |
| `OLLAMA_BASE_URL` | Base URL of a remote Ollama server reachable from the backend. |
| `OLLAMA_MODEL` | Model name installed on that remote Ollama server. |
| `OLLAMA_TIMEOUT_SECONDS` | Positive request timeout; default is 120 seconds. Keep it within the function duration budget. |
| `GROQ_API_KEY` | Optional secret for the hosted Groq provider. Keep it server-side; never use a `VITE_` prefix. |
| `GROQ_MODEL` | Optional Groq model ID; defaults to `openai/gpt-oss-20b`. |
| `GROQ_BASE_URL` | Optional OpenAI-compatible endpoint; defaults to `https://api.groq.com/openai/v1`. |
| `GROQ_TIMEOUT_SECONDS` | Positive Groq request timeout; defaults to 60 seconds. |
| `GROQ_INPUT_COST_PER_MILLION` | Optional current USD price per million input tokens for the configured Groq model. |
| `GROQ_OUTPUT_COST_PER_MILLION` | Optional current USD price per million output tokens for the configured Groq model. |

`ALEMBIC_DATABASE_URL` is optional and overrides `DATABASE_URL` for
Alembic commands only. It is not required for normal API startup. Prefer
running migrations as an explicit release step against the intended database.

## Database and migrations

Production requires an explicitly configured PostgreSQL `DATABASE_URL`.
The application creates its SQLAlchemy engine at import time, then its startup
lifespan checks database connectivity and schema compatibility/current Alembic
revision. Startup does not create tables or automatically run migrations.

The `psycopg[binary]` driver is already in `backend/requirements.txt`.
Before first deployment, configure the managed PostgreSQL database and run
reviewed migrations from a trusted environment with the backend dependencies:

```powershell
$env:FASTAPI_ENV = "production"
$env:DATABASE_URL = "<managed-postgresql-url>"
$env:ALEMBIC_DATABASE_URL = $env:DATABASE_URL
python -m alembic -c alembic.ini upgrade head
```

Confirm both variables point to the intended database before running the
command. For an existing database, follow the backup, compatibility review,
and explicit adoption guidance in [DATABASE.md](./DATABASE.md). Migrations
leave legacy ownership nullable and do not assign existing records to a user.

SQLite is suitable for local development and tests only. Vercel function
instances do not provide durable shared SQLite storage; production must use
the configured managed PostgreSQL database.

## Groq connectivity and cost estimates

Groq is an optional hosted provider. Set `GROQ_API_KEY` in the backend
Production environment, then redeploy and use the Models page or evaluation
wizard to check the provider connection. Never expose the key in frontend
variables, source control, browser requests, or logs.

Cost estimates are calculated from the prompt/completion token counts returned
by Groq and the two optional per-million USD rates above. Set those rates to
the current published prices for the selected model; leaving either rate
unset keeps the estimate unavailable rather than displaying a misleading
zero. Ollama API spend is reported as $0 because local inference has no
provider API charge; electricity and hosting costs are not measured.

## Ollama connectivity

The backend calls Ollama's native `/api/tags` and `/api/generate` endpoints.
The locally running Ollama process at `127.0.0.1:11434` is not reachable from
Vercel. Set `OLLAMA_BASE_URL` to a separately hosted Ollama endpoint that the
backend can reach, and restrict access with a private network, firewall, VPN,
or authenticated private proxy. The current provider does not implement
Ollama Cloud's direct API-key authentication; do not assume that an Ollama
Cloud key can be used with this integration.

## Deployment verification checklist

After each production deployment, verify all of the following against the
deployed domain:

- `GET /api/health` returns the expected health response.
- Frontend requests use `/api`, not `localhost`.
- Signup and login work over HTTPS and the refresh cookie is stored securely.
- A user's datasets, test cases, rubrics, runs, and failures are scoped to that
  authenticated user.
- The configured Groq API key is accepted and a real Groq evaluation completes.
- If remote Ollama is configured, its endpoint is reachable from the deployed
  backend; a local Ollama process on a developer PC is not reachable from Vercel.
- Database migrations are at the expected Alembic head.

A successful Vercel build/status check alone does not prove these runtime
checks have passed.

## Remaining production hardening

The current implementation still runs evaluations sequentially inside the
request lifecycle; it does not yet provide a durable background queue or
worker. Do not treat FastAPI background tasks or an in-process queue as durable
on serverless instances. A production queue requires a shared broker and a
separately deployed worker, plus persisted job state and frontend polling.

Login rate limiting is database-backed and shared across instances. The
migration adds hashed email/IP buckets; configure the two LOGIN_RATE_LIMIT
variables to tune the policy. It currently limits login attempts, not signup
or other authenticated endpoints.

The CI evaluation regression gate checks deterministic evaluator behavior
against fixed fixtures. It does not call Groq or Ollama and therefore does not
claim to detect live model drift; a live-model gate requires explicitly
configured provider credentials, a controlled benchmark dataset, and a
separate opt-in workflow.

## Local development

Run the frontend and backend using the repository's local development
instructions. Local SQLite and a manually started Ollama process are
development conveniences, not production services. The root Docker Compose
configuration is for local development and is not a complete production
stack with managed PostgreSQL, private Ollama networking, backups, and TLS.
