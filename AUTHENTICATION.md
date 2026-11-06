# Authentication

EvalForge supports locally managed email/password accounts. Passwords are
hashed with Argon2id. Access tokens are signed JWTs with a 15-minute lifetime;
refresh credentials are random, HttpOnly cookies with a 30-day lifetime and
are stored in the database only as SHA-256 hashes. Refresh credentials rotate
on use, and reuse of a revoked credential revokes its active token family.

Authentication endpoints:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `POST /api/auth/logout-all`

`/api/health` and `/api/providers/ollama/health` remain public. Business API
routes require a verified bearer access token. Dataset, rubric, and evaluation
resources are scoped to their authenticated owner; child cases, results, and
reviews are authorized through their parent. Unowned legacy records are
excluded from user access.

Configure `JWT_SECRET_KEY` on the backend with a unique random value of at least
32 bytes. Never put this value in frontend configuration or source control. For
production, set `FASTAPI_ENV=production`, `AUTH_COOKIE_SECURE=true`, and
`CORS_ALLOWED_ORIGINS` to the exact HTTPS browser origins that should access
the API. Production startup requires these settings and rejects wildcard CORS
origins. The refresh cookie is `HttpOnly`, `Secure`, and `SameSite=Strict`, so
the frontend and API should use HTTPS domains on the same site.

The authentication schema is revision `b762c47d8e10`; ownership is added by
revision `ce4d8129ab31`. Production startup verifies that migrations are
already applied and never applies them automatically. See [DATABASE.md](./DATABASE.md)
and [DEPLOYMENT.md](./DEPLOYMENT.md) for controlled migration and hosting
requirements. Legacy records are not automatically assigned to an account.
