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

## Runtime suitability and evaluation jobs

Live evaluations are submitted to a durable PostgreSQL job queue. The API
validates the request, snapshots the selected test cases and rubric, writes a
pending run/job, and returns `202 Accepted` without waiting for model inference.
The browser polls the authenticated job endpoint for persisted result counts,
status, and errors; cancellation is available while a worker is processing.

A dedicated long-running worker claims jobs with PostgreSQL
`FOR UPDATE SKIP LOCKED`, renews its lease while a model call is running,
persists each test result as it completes, and resumes only cases that do not
already have a saved result after a worker restart. Transient provider errors
receive a bounded retry schedule. The queue, job state, snapshots, and results
are stored in the shared PostgreSQL database; no Redis or in-memory queue is
required.

**The worker is not a Vercel Function.** Vercel continues to host the frontend
and HTTP API, while a separate container service must run the worker process.
If that service is stopped or not deployed, API requests will remain queued
until a worker is available. Keep the API and worker on the same production
database and migration revision.


## Deploy the evaluation worker

The worker uses the same `backend/Dockerfile` and repository code as the API,
but starts a different process:

```bash
python -m backend.app.jobs.evaluation_worker
```

For local Docker Compose, `docker compose up --build` starts the API,
frontend, and dedicated `evaluation-worker` service. For production, create a
private, always-on Docker/background-worker service from this repository:

- Dockerfile: `backend/Dockerfile`
- Start command: `python -m backend.app.jobs.evaluation_worker`
- Do not expose a public HTTP port for the worker.
- Configure the same `DATABASE_URL` as the API and apply Alembic migrations
  before starting either new version.
- Configure `FASTAPI_ENV=production`, `JWT_SECRET_KEY`, and the provider
  settings needed by queued jobs (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`,
  `OLLAMA_TIMEOUT_SECONDS`, `GROQ_API_KEY`, `GROQ_MODEL`, and optional
  Groq cost rates). Keep all secrets in the worker platform's secret store.
- Set `EVALUATION_WORKER_POLL_SECONDS` to a value from 0.25 to 60 seconds;
  the default is 2 seconds.

The worker uses a five-minute lease with a 30-second heartbeat and up to three
attempts. If a process is terminated, another worker can reclaim its expired
lease. Results already written to PostgreSQL are retained and skipped when the
job resumes. A provider may have completed an external inference just before a
worker crash without its response being committed; that individual inference
can be repeated, so this is durable at-least-once execution rather than
exactly-once model billing.

Run at least one worker replica. Additional replicas can safely compete for
jobs because claims are protected by PostgreSQL row locks. Monitor jobs in
`Pending` for longer than the expected queue delay and jobs marked `Failed`;
the API exposes each job's last error and attempt count to its owner.

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

The durable PostgreSQL evaluation queue and dedicated worker described above
are implemented. The API persists the run, job payload, and test-case snapshot,
then returns `202 Accepted`; the worker claims jobs with PostgreSQL row locks,
renews its lease, persists results incrementally, and resumes unfinished cases
after an interrupted attempt. Production readiness still requires a private,
always-on worker service running against the same database and migration
revision as the API. A successful Vercel build does not start the worker or
prove that queued jobs will be processed. Do not replace the worker with an
in-process FastAPI background task on serverless instances.

Login rate limiting is database-backed and shared across instances. Each
bucket key is a one-way hash of the normalized email and client IP; raw email/IP
pairs are not persisted in the rate-limit table. Expired buckets older than
7 days are pruned in batches of at most 200 per login attempt. PostgreSQL uses a
transaction-scoped advisory lock to coordinate cleanup, and the DELETE repeats
the expiry predicate so a bucket refreshed concurrently is never removed.

On Vercel, the login throttle uses the public client address from
X-Forwarded-For because Vercel overwrites that header at its edge. Outside
Vercel, the application ignores client-supplied X-Forwarded-For and uses the
ASGI peer address; do not set VERCEL=1 on a host that does not provide the same
trusted proxy behavior. The limiter currently protects login attempts, not
signup or every authenticated endpoint.

Production authentication fails closed unless JWT_SECRET_KEY is at least
32 random bytes and is not a placeholder, AUTH_COOKIE_SECURE=true, and
CORS_ALLOWED_ORIGINS contains exact public HTTPS origins without wildcards,
paths, query strings, or credentials. Logout uses a conditional token update;
if a token was rotated while logout was in flight, its entire refresh-token
family is revoked so the replacement cannot survive.

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

## Dedicated Render worker blueprint

This repository also includes a root-level `render.yaml` for the long-running evaluation worker. It creates a background worker in the Ohio region, matching the current Neon project region, and starts:

```bash
python -m backend.app.jobs.evaluation_worker
```

The Blueprint deliberately sets `autoDeployTrigger: off`; connecting or updating the Blueprint does not automatically deploy new worker code. The worker is not a Vercel Function and must use the exact same production `DATABASE_URL` as the API. Set the same `JWT_SECRET_KEY`, exact public `CORS_ALLOWED_ORIGINS`, and provider configuration as the API. Re-enter secret values in Render's secret fields; they are not copied from Vercel automatically.

For production model calls, use a provider endpoint reachable from Render. A local Ollama process on a developer's computer or `localhost` is not reachable by a hosted worker. Set `OLLAMA_BASE_URL` only when a secured remote Ollama service is available, or configure the same Groq API key/model used by the API. Keep API keys in Render's secret store.

The current Render price list shows the `0.5c-512mb` worker plan at approximately USD $7/month. This is an additional recurring cost, before taxes or usage changes. Do not create or start the service until that cost and the provider settings are approved. Once provisioned, deploy the worker manually, verify its startup logs, and submit one small queued evaluation; it should move from Pending to Completed and persist results in the shared PostgreSQL database.

The Vercel project remains configured to skip builds until deployment is explicitly authorized. Enabling this worker does not require a Vercel deployment, but the API must already have the durable-job code and matching database migration.
