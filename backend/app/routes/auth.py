import hashlib
import os
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.models.models import AuthLoginAttempt, User
from backend.app.schemas.auth import LoginRequest, RegistrationRequest, TokenResponse, UserResponse
from backend.app.security.auth import (
    ACCESS_TOKEN_EXPIRES_IN,
    REFRESH_COOKIE_NAME,
    AuthenticationConfigurationError,
    RefreshTokenError,
    allowed_cors_origins,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_jwt_secret,
    hash_password,
    normalize_email,
    refresh_cookie_is_secure,
    revoke_refresh_token,
    revoke_user_refresh_tokens,
    rotate_refresh_token,
    verify_password,
)

router = APIRouter(prefix='/api/auth', tags=['authentication'])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=refresh_cookie_is_secure(),
        samesite='strict',
        path='/api/auth',
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=refresh_cookie_is_secure(),
        samesite='strict',
        path='/api/auth',
    )


def _check_cookie_request_origin(request: Request) -> None:
    origin = request.headers.get('origin')
    if origin is None:
        return
    if origin not in allowed_cors_origins():
        raise HTTPException(status_code=403, detail='Request origin is not allowed')


def _login_attempt_key(request: Request, email: str) -> str:
    forwarded_for = request.headers.get('x-forwarded-for', '')
    client_ip = forwarded_for.split(',')[0].strip() if forwarded_for else (
        request.client.host if request.client is not None else 'unknown'
    )
    return hashlib.sha256(f'{client_ip}:{email}'.encode('utf-8')).hexdigest()


def _record_login_attempt(db: Session, key_hash: str) -> None:
    try:
        max_attempts = int(os.getenv('LOGIN_RATE_LIMIT_MAX_ATTEMPTS', '10'))
        window_seconds = int(os.getenv('LOGIN_RATE_LIMIT_WINDOW_SECONDS', '900'))
    except ValueError as error:
        raise HTTPException(status_code=503, detail='Login rate limiting is misconfigured') from error
    if max_attempts < 1 or window_seconds < 1:
        raise HTTPException(status_code=503, detail='Login rate limiting is misconfigured')

    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=window_seconds)
    insert = postgresql_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    statement = insert(AuthLoginAttempt).values(
        key_hash=key_hash,
        window_started_at=now,
        attempts=1,
        updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[AuthLoginAttempt.key_hash],
        set_={
            'window_started_at': case(
                (AuthLoginAttempt.window_started_at <= cutoff, now),
                else_=AuthLoginAttempt.window_started_at,
            ),
            'attempts': case(
                (AuthLoginAttempt.window_started_at <= cutoff, 1),
                else_=AuthLoginAttempt.attempts + 1,
            ),
            'updated_at': now,
        },
    )
    db.execute(statement)
    db.commit()

    bucket = db.get(AuthLoginAttempt, key_hash)
    if bucket is not None and bucket.attempts > max_attempts:
        retry_after = max(1, int((bucket.window_started_at + timedelta(seconds=window_seconds) - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail='Too many login attempts. Please try again later.',
            headers={'Retry-After': str(retry_after)},
        )


def _configuration_error(error: AuthenticationConfigurationError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail='Authentication service is not configured',
    )


@router.post('/register', response_model=TokenResponse, status_code=201)
def register(
    payload: RegistrationRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    try:
        get_jwt_secret()
        refresh_cookie_is_secure()
    except AuthenticationConfigurationError as error:
        raise _configuration_error(error) from error

    email = normalize_email(str(payload.email))
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail='An account with this email already exists')

    user = User(
        id=uuid.uuid4().hex,
        email=email,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    try:
        db.add(user)
        db.flush()
        refresh_token, _ = create_refresh_token(db, user.id)
        access_token = create_access_token(user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(
                status_code=409,
                detail='An account with this email already exists',
            ) from None
        raise

    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRES_IN,
        user=_user_response(user),
    )


@router.post('/login', response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    try:
        get_jwt_secret()
        refresh_cookie_is_secure()
    except AuthenticationConfigurationError as error:
        raise _configuration_error(error) from error

    email = normalize_email(str(payload.email))
    attempt_key = _login_attempt_key(request, email)
    _record_login_attempt(db, attempt_key)
    user = db.scalar(select(User).where(User.email == email))
    password_matches = (
        verify_password(payload.password, user.password_hash)
        if user is not None
        else _perform_dummy_password_hash(payload.password)
    )
    if not password_matches or user is None or not user.is_active:
        raise HTTPException(status_code=401, detail='Invalid email or password')

    db.execute(delete(AuthLoginAttempt).where(AuthLoginAttempt.key_hash == attempt_key))
    refresh_token, _ = create_refresh_token(db, user.id)
    access_token = create_access_token(user.id)
    db.commit()
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRES_IN,
        user=_user_response(user),
    )


@router.get('/me', response_model=UserResponse)
def current_user(
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return _user_response(user)


@router.post('/refresh', response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokenResponse:
    _check_cookie_request_origin(request)
    try:
        get_jwt_secret()
        refresh_cookie_is_secure()
    except AuthenticationConfigurationError as error:
        raise _configuration_error(error) from error
    if refresh_token is None:
        raise HTTPException(status_code=401, detail='Invalid or missing refresh token')
    try:
        user, replacement = rotate_refresh_token(db, refresh_token)
        access_token = create_access_token(user.id)
    except RefreshTokenError:
        raise HTTPException(status_code=401, detail='Invalid or missing refresh token') from None
    except AuthenticationConfigurationError as error:
        raise _configuration_error(error)
    _set_refresh_cookie(response, replacement)
    return TokenResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRES_IN,
        user=_user_response(user),
    )


@router.post('/logout', status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> Response:
    _check_cookie_request_origin(request)
    try:
        refresh_cookie_is_secure()
        if refresh_token is not None:
            revoke_refresh_token(db, refresh_token)
        _clear_refresh_cookie(response)
    except AuthenticationConfigurationError as error:
        raise _configuration_error(error) from error
    response.status_code = 204
    return response


@router.post('/logout-all', status_code=204)
def logout_all(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    try:
        refresh_cookie_is_secure()
        revoke_user_refresh_tokens(db, user.id)
        _clear_refresh_cookie(response)
    except AuthenticationConfigurationError as error:
        raise _configuration_error(error) from error
    response.status_code = 204
    return response


def _perform_dummy_password_hash(password: str) -> bool:
    hash_password(password)
    return False
