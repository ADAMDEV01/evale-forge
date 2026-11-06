from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.app import main
from backend.app.models.models import AuthRefreshToken, User
from backend.app.security.auth import (
    AuthenticationConfigurationError,
    JWT_AUDIENCE,
    JWT_ISSUER,
    REFRESH_COOKIE_NAME,
    allowed_cors_origins,
    get_jwt_secret,
    hash_refresh_token,
    validate_production_auth_settings,
)

TEST_EMAIL = 'Person@Example.com'
TEST_PASSWORD = 'correct horse battery staple'


def register_user(client: TestClient, email: str = TEST_EMAIL):
    return client.post('/api/auth/register', json={
        'email': email,
        'password': TEST_PASSWORD,
    })


def signed_access_token(
    *,
    token_type: str = 'access',
    expires_in: timedelta = timedelta(minutes=5),
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            'sub': 'test-authenticated-user',
            'jti': 'test-token-id',
            'token_type': token_type,
            'iat': now,
            'exp': now + expires_in,
            'iss': JWT_ISSUER,
            'aud': JWT_AUDIENCE,
        },
        get_jwt_secret(),
        algorithm='HS256',
    )


def test_login_rate_limit_blocks_repeated_attempts(
    unauthenticated_client: TestClient,
    isolated_test_database,
    monkeypatch,
):
    monkeypatch.setenv('LOGIN_RATE_LIMIT_MAX_ATTEMPTS', '2')
    monkeypatch.setenv('LOGIN_RATE_LIMIT_WINDOW_SECONDS', '900')
    payload = {'email': 'unknown@example.com', 'password': 'incorrect password'}

    first = unauthenticated_client.post('/api/auth/login', json=payload)
    second = unauthenticated_client.post('/api/auth/login', json=payload)
    blocked = unauthenticated_client.post('/api/auth/login', json=payload)

    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert blocked.headers['retry-after']


def test_registration_creates_argon2id_user_and_secure_refresh_cookie(
    unauthenticated_client: TestClient,
    isolated_test_database,
):
    response = register_user(unauthenticated_client)

    assert response.status_code == 201
    body = response.json()
    assert body['user']['email'] == TEST_EMAIL.casefold()
    assert body['token_type'] == 'bearer'
    assert body['expires_in'] == 900
    assert 'password_hash' not in body
    assert 'refresh_token' not in body
    cookie_header = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie_header
    assert 'samesite=strict' in cookie_header
    assert 'path=/api/auth' in cookie_header

    raw_refresh_token = response.cookies.get(REFRESH_COOKIE_NAME)
    assert raw_refresh_token
    session_factory = sessionmaker(bind=isolated_test_database['engine'])
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == TEST_EMAIL.casefold()))
        refresh = session.scalar(select(AuthRefreshToken))

    assert user is not None
    assert user.password_hash.startswith('$argon2id$')
    assert user.password_hash != TEST_PASSWORD
    assert refresh is not None
    assert refresh.token_hash == hash_refresh_token(raw_refresh_token)
    assert refresh.token_hash != raw_refresh_token


def test_refresh_cookie_secure_attribute_can_be_enabled(
    unauthenticated_client: TestClient,
    monkeypatch,
):
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'true')

    response = register_user(unauthenticated_client)

    assert response.status_code == 201
    assert 'secure' in response.headers['set-cookie'].lower()


def test_registration_normalizes_email_and_rejects_duplicate(unauthenticated_client: TestClient):
    first = register_user(unauthenticated_client)
    duplicate = register_user(unauthenticated_client, '  person@example.COM  ')

    assert first.status_code == 201
    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    'payload',
    [
        {'email': 'not-an-email', 'password': TEST_PASSWORD},
        {'email': 'person@example.com', 'password': 'short'},
    ],
)
def test_registration_rejects_invalid_email_or_password(
    unauthenticated_client: TestClient,
    payload: dict[str, str],
):
    response = unauthenticated_client.post('/api/auth/register', json=payload)

    assert response.status_code == 422


def test_registration_does_not_accept_client_supplied_identity(unauthenticated_client: TestClient):
    response = unauthenticated_client.post('/api/auth/register', json={
        'email': TEST_EMAIL,
        'password': TEST_PASSWORD,
        'id': 'caller-chosen-user-id',
    })

    assert response.status_code == 422


def test_login_uses_normalized_email_and_wrong_password_is_generic(unauthenticated_client: TestClient):
    registered = register_user(unauthenticated_client)
    assert registered.status_code == 201

    login = unauthenticated_client.post('/api/auth/login', json={
        'email': ' PERSON@example.COM ',
        'password': TEST_PASSWORD,
    })
    wrong_password = unauthenticated_client.post('/api/auth/login', json={
        'email': TEST_EMAIL,
        'password': 'incorrect password',
    })

    assert login.status_code == 200
    assert login.json()['user']['id'] == registered.json()['user']['id']
    assert wrong_password.status_code == 401
    assert wrong_password.json()['detail'] == 'Invalid email or password'


def test_current_user_and_business_routes_require_verified_access_token(
    unauthenticated_client: TestClient,
):
    assert unauthenticated_client.get('/api/datasets').status_code == 401
    assert unauthenticated_client.get('/api/health').status_code == 200

    registered = register_user(unauthenticated_client)
    access_token = registered.json()['access_token']
    response = unauthenticated_client.get(
        '/api/auth/me',
        headers={'Authorization': f'Bearer {access_token}'},
    )

    assert response.status_code == 200
    assert response.json() == registered.json()['user']


@pytest.mark.parametrize(
    ('token_type', 'expires_in', 'kind'),
    [
        ('access', timedelta(minutes=5), 'malformed'),
        ('access', timedelta(seconds=-1), 'expired'),
        ('refresh', timedelta(minutes=5), 'wrong_type'),
        ('access', timedelta(minutes=5), 'wrong_signature'),
    ],
)
def test_invalid_expired_and_wrong_type_jwt_are_rejected(
    unauthenticated_client: TestClient,
    token_type: str,
    expires_in: timedelta,
    kind: str,
):
    if kind == 'malformed':
        token = 'not-a-jwt'
    elif kind == 'wrong_signature':
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                'sub': 'test-authenticated-user',
                'jti': 'test-token-id',
                'token_type': token_type,
                'iat': now,
                'exp': now + expires_in,
                'iss': JWT_ISSUER,
                'aud': JWT_AUDIENCE,
            },
            b'x' * 32,
            algorithm='HS256',
        )
    else:
        token = signed_access_token(token_type=token_type, expires_in=expires_in)
    response = unauthenticated_client.get(
        '/api/datasets',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 401
    assert response.json()['detail'] == 'Invalid or missing authentication credentials'


def test_refresh_rotates_credentials_and_stores_only_hashes(
    unauthenticated_client: TestClient,
    isolated_test_database,
):
    registered = register_user(unauthenticated_client)
    original_refresh = registered.cookies.get(REFRESH_COOKIE_NAME)

    rotated = unauthenticated_client.post('/api/auth/refresh')
    replacement_refresh = rotated.cookies.get(REFRESH_COOKIE_NAME)

    assert rotated.status_code == 200
    assert replacement_refresh
    assert replacement_refresh != original_refresh
    assert rotated.json()['user'] == registered.json()['user']
    assert 'refresh_token' not in rotated.json()
    session_factory = sessionmaker(bind=isolated_test_database['engine'])
    with session_factory() as session:
        sessions = session.scalars(
            select(AuthRefreshToken).order_by(AuthRefreshToken.created_at)
        ).all()

    assert len(sessions) == 2
    assert sessions[0].token_hash == hash_refresh_token(original_refresh)
    assert sessions[0].revoked_at is not None
    assert sessions[0].replaced_by_id == sessions[1].id
    assert sessions[1].token_hash == hash_refresh_token(replacement_refresh)
    assert sessions[1].revoked_at is None


def test_reuse_of_rotated_refresh_token_revokes_the_token_family(
    unauthenticated_client: TestClient,
):
    registered = register_user(unauthenticated_client)
    original_refresh = registered.cookies.get(REFRESH_COOKIE_NAME)
    rotated = unauthenticated_client.post('/api/auth/refresh')
    replacement_refresh = rotated.cookies.get(REFRESH_COOKIE_NAME)

    replay = unauthenticated_client.post(
        '/api/auth/refresh',
        headers={'Cookie': f'{REFRESH_COOKIE_NAME}={original_refresh}'},
    )
    followup = unauthenticated_client.post(
        '/api/auth/refresh',
        headers={'Cookie': f'{REFRESH_COOKIE_NAME}={replacement_refresh}'},
    )

    assert replay.status_code == 401
    assert followup.status_code == 401


def test_logout_revokes_refresh_credential(unauthenticated_client: TestClient):
    registered = register_user(unauthenticated_client)

    logout = unauthenticated_client.post('/api/auth/logout')
    refresh = unauthenticated_client.post('/api/auth/refresh')

    assert logout.status_code == 204
    assert refresh.status_code == 401


def test_logout_all_revokes_all_refresh_sessions(unauthenticated_client: TestClient):
    registered = register_user(unauthenticated_client)
    token = registered.json()['access_token']
    original_refresh = registered.cookies.get(REFRESH_COOKIE_NAME)
    unauthenticated_client.post('/api/auth/login', json={
        'email': TEST_EMAIL,
        'password': TEST_PASSWORD,
    })

    logout = unauthenticated_client.post(
        '/api/auth/logout-all',
        headers={'Authorization': f'Bearer {token}'},
    )
    refresh = unauthenticated_client.post('/api/auth/refresh')
    original_refresh_after_logout = unauthenticated_client.post(
        '/api/auth/refresh',
        headers={'Cookie': f'{REFRESH_COOKIE_NAME}={original_refresh}'},
    )

    assert logout.status_code == 204
    assert refresh.status_code == 401
    assert original_refresh_after_logout.status_code == 401


def test_untrusted_origin_cannot_use_refresh_cookie(unauthenticated_client: TestClient):
    register_user(unauthenticated_client)

    response = unauthenticated_client.post(
        '/api/auth/refresh',
        headers={'Origin': 'https://attacker.example'},
    )

    assert response.status_code == 403


def test_cors_does_not_enable_wildcard_origins_with_credentials():
    cors = next(
        middleware for middleware in main.app.user_middleware
        if middleware.cls.__name__ == 'CORSMiddleware'
    )

    assert '*' not in cors.kwargs['allow_origins']
    assert cors.kwargs['allow_credentials'] is True


def test_production_auth_configuration_requires_https_cookie_and_explicit_origins(monkeypatch):
    monkeypatch.setenv('FASTAPI_ENV', 'production')
    monkeypatch.setenv('JWT_SECRET_KEY', 'x' * 32)
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'false')
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', 'https://app.example.test')

    with pytest.raises(AuthenticationConfigurationError, match='must be true in production'):
        validate_production_auth_settings()

    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'true')
    monkeypatch.delenv('CORS_ALLOWED_ORIGINS')
    with pytest.raises(RuntimeError, match='explicitly configured in production'):
        validate_production_auth_settings()

    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', '*')
    with pytest.raises(RuntimeError, match='cannot include'):
        allowed_cors_origins()


def test_cors_does_not_add_hardcoded_origin(monkeypatch):
    from backend.app.security.auth import allowed_cors_origins

    monkeypatch.setenv('FASTAPI_ENV', 'production')
    monkeypatch.setenv('CORS_ALLOWED_ORIGINS', 'https://example.test/')
    assert allowed_cors_origins() == ['https://example.test']
