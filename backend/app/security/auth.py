from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.models.models import AuthRefreshToken, User

ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
ACCESS_TOKEN_EXPIRES_IN = int(ACCESS_TOKEN_LIFETIME.total_seconds())
JWT_ISSUER = 'evalforge'
JWT_AUDIENCE = 'evalforge-api'
REFRESH_COOKIE_NAME = 'evalforge_refresh'
DEFAULT_CORS_ALLOWED_ORIGINS = (
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:4173',
)
PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticationConfigurationError(RuntimeError):
    pass


class RefreshTokenError(ValueError):
    pass


def allowed_cors_origins() -> list[str]:
    is_production = os.environ.get('FASTAPI_ENV', '').strip().lower() in {'prod', 'production'}
    configured = os.environ.get('CORS_ALLOWED_ORIGINS', '').strip()
    if is_production and not configured:
        raise RuntimeError('CORS_ALLOWED_ORIGINS must be explicitly configured in production.')
    configured = os.environ.get(
        'CORS_ALLOWED_ORIGINS',
        ','.join(DEFAULT_CORS_ALLOWED_ORIGINS),
    )
    origins = [origin.strip().rstrip('/') for origin in configured.split(',') if origin.strip()]
    if not origins or '*' in origins:
        raise RuntimeError('CORS_ALLOWED_ORIGINS must contain explicit origins and cannot include "*".')

    return origins


def refresh_cookie_is_secure() -> bool:
    configured = os.environ.get('AUTH_COOKIE_SECURE', 'true').strip().lower()
    if configured not in {'true', 'false'}:
        raise AuthenticationConfigurationError('AUTH_COOKIE_SECURE must be true or false.')
    return configured == 'true'


def validate_production_auth_settings() -> None:
    if os.environ.get('FASTAPI_ENV', '').strip().lower() not in {'prod', 'production'}:
        return
    get_jwt_secret()
    if not refresh_cookie_is_secure():
        raise AuthenticationConfigurationError(
            'AUTH_COOKIE_SECURE must be true in production.'
        )
    allowed_cors_origins()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_jwt_secret() -> bytes:
    secret = os.environ.get('JWT_SECRET_KEY', '')
    if len(secret.encode('utf-8')) < 32:
        raise AuthenticationConfigurationError(
            'JWT_SECRET_KEY must be configured with at least 32 bytes.'
        )
    return secret.encode('utf-8')


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        'sub': user_id,
        'jti': uuid.uuid4().hex,
        'token_type': 'access',
        'iat': now,
        'exp': now + ACCESS_TOKEN_LIFETIME,
        'iss': JWT_ISSUER,
        'aud': JWT_AUDIENCE,
    }
    return jwt.encode(claims, get_jwt_secret(), algorithm='HS256')


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail='Invalid or missing authentication credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != 'bearer':
        raise _unauthorized()
    try:
        claims: dict[str, Any] = jwt.decode(
            credentials.credentials,
            get_jwt_secret(),
            algorithms=['HS256'],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={
                'require': ['sub', 'jti', 'token_type', 'iat', 'exp', 'iss', 'aud'],
            },
        )
    except AuthenticationConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail='Authentication service is not configured',
        ) from error
    except jwt.InvalidTokenError:
        raise _unauthorized() from None

    if claims.get('token_type') != 'access' or not isinstance(claims.get('sub'), str):
        raise _unauthorized()
    user = db.get(User, claims['sub'])
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_refresh_token(
    db: Session,
    user_id: str,
    family_id: str | None = None,
) -> tuple[str, AuthRefreshToken]:
    token = secrets.token_urlsafe(48)
    token_id = uuid.uuid4().hex
    session = AuthRefreshToken(
        id=token_id,
        user_id=user_id,
        token_hash=hash_refresh_token(token),
        family_id=family_id or token_id,
        created_at=utcnow(),
        expires_at=utcnow() + REFRESH_TOKEN_LIFETIME,
    )
    db.add(session)
    return token, session


def _revoke_family(db: Session, family_id: str, now: datetime) -> None:
    db.execute(
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.family_id == family_id,
            AuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def rotate_refresh_token(db: Session, token: str) -> tuple[User, str]:
    now = utcnow()
    token_hash = hash_refresh_token(token)
    current = db.scalar(
        select(AuthRefreshToken).where(AuthRefreshToken.token_hash == token_hash)
    )
    if current is None:
        raise RefreshTokenError('Invalid refresh token')
    if current.revoked_at is not None:
        _revoke_family(db, current.family_id, now)
        db.commit()
        raise RefreshTokenError('Refresh token reuse detected')
    if current.expires_at <= now:
        current.revoked_at = now
        db.commit()
        raise RefreshTokenError('Refresh token expired')

    user = db.get(User, current.user_id)
    if user is None or not user.is_active:
        _revoke_family(db, current.family_id, now)
        db.commit()
        raise RefreshTokenError('Refresh token is no longer valid')

    replacement, replacement_session = create_refresh_token(
        db,
        current.user_id,
        current.family_id,
    )
    result = db.execute(
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.id == current.id,
            AuthRefreshToken.revoked_at.is_(None),
            AuthRefreshToken.expires_at > now,
        )
        .values(
            revoked_at=now,
            replaced_by_id=replacement_session.id,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        _revoke_family(db, current.family_id, now)
        db.commit()
        raise RefreshTokenError('Refresh token reuse detected')

    db.commit()
    return user, replacement


def revoke_refresh_token(db: Session, token: str) -> None:
    now = utcnow()
    current = db.scalar(
        select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == hash_refresh_token(token)
        )
    )
    if current is None:
        return
    if current.revoked_at is not None:
        _revoke_family(db, current.family_id, now)
    else:
        current.revoked_at = now
    db.commit()


def revoke_user_refresh_tokens(db: Session, user_id: str) -> None:
    db.execute(
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.user_id == user_id,
            AuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    db.commit()
