from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (UniqueConstraint('email', name='uq_users_email'),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class AuthRefreshToken(Base):
    __tablename__ = 'auth_refresh_tokens'
    __table_args__ = (
        UniqueConstraint('token_hash', name='uq_auth_refresh_tokens_token_hash'),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    replaced_by_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class AuthLoginAttempt(Base):
    __tablename__ = 'auth_login_attempts'

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class Dataset(Base):
    __tablename__ = 'datasets'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey('users.id', ondelete='RESTRICT'),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[str] = mapped_column(String(32), default='v1.0')
    cases: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    modified_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    color: Mapped[Optional[str]] = mapped_column(String(32), default='violet')

    test_cases: Mapped[list['TestCase']] = relationship(back_populates='dataset', cascade='all, delete-orphan')
    versions: Mapped[list['DatasetVersion']] = relationship(back_populates='dataset', cascade='all, delete-orphan')


class DatasetVersion(Base):
    __tablename__ = 'dataset_versions'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id'), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    case_count: Mapped[int] = mapped_column(Integer, default=0)

    dataset: Mapped['Dataset'] = relationship(back_populates='versions')
    test_cases: Mapped[list['TestCase']] = relationship(back_populates='dataset_version')


class TestCase(Base):
    __tablename__ = 'test_cases'
    __table_args__ = (UniqueConstraint('dataset_id', 'title', name='uq_test_case_title_dataset'),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id'), nullable=False)
    dataset_version_id: Mapped[Optional[str]] = mapped_column(ForeignKey('dataset_versions.id'), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    expected_keywords: Mapped[str] = mapped_column(Text, default='[]')
    criteria: Mapped[str] = mapped_column(Text, default='')
    category: Mapped[str] = mapped_column(String(100), default='General')
    tags: Mapped[str] = mapped_column(Text, default='')
    importance: Mapped[str] = mapped_column(String(32), default='Medium')
    expected_behavior: Mapped[str] = mapped_column(Text, default='')

    dataset: Mapped['Dataset'] = relationship(back_populates='test_cases')
    dataset_version: Mapped[Optional['DatasetVersion']] = relationship(back_populates='test_cases')


class Rubric(Base):
    __tablename__ = 'rubrics'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey('users.id', ondelete='RESTRICT'),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    criteria: Mapped[list['RubricCriterion']] = relationship(back_populates='rubric', cascade='all, delete-orphan')


class RubricCriterion(Base):
    __tablename__ = 'rubric_criteria'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rubric_id: Mapped[str] = mapped_column(ForeignKey('rubrics.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    weight: Mapped[int] = mapped_column(Integer, default=0)
    scale: Mapped[str] = mapped_column(String(32), default='0–5')
    expected_keywords: Mapped[str] = mapped_column(Text, default='[]')

    rubric: Mapped['Rubric'] = relationship(back_populates='criteria')


class EvaluationRun(Base):
    __tablename__ = 'evaluation_runs'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey('users.id', ondelete='RESTRICT'),
        nullable=True,
        index=True,
    )
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id'), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default='mock')
    dataset_name: Mapped[str] = mapped_column(String(200), default='')
    evaluation_method: Mapped[str] = mapped_column(String(32), default='exact_match')
    rubric_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rubric_snapshot_json: Mapped[str] = mapped_column(Text, default='{}')
    token_usage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='Pending')
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    latency: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[str] = mapped_column(String(80), default='')
    config_json: Mapped[str] = mapped_column(Text, default='{}')
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    results: Mapped[list['EvaluationResult']] = relationship(back_populates='run', cascade='all, delete-orphan')


class EvaluationResult(Base):
    __tablename__ = 'evaluation_results'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('evaluation_runs.id'), nullable=False)
    test_case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    test_case_title: Mapped[str] = mapped_column(String(200), default='')
    category: Mapped[str] = mapped_column(String(100), default='General')
    input_snapshot: Mapped[str] = mapped_column(Text, default='')
    expected: Mapped[str] = mapped_column(Text, default='')
    evaluation_method: Mapped[str] = mapped_column(String(32), default='exact_match')
    status: Mapped[str] = mapped_column(String(32), default='Pending')
    score: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    actual: Mapped[str] = mapped_column(Text, default='')
    token_usage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    criteria_breakdown_json: Mapped[str] = mapped_column(Text, default='[]')
    error_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped['EvaluationRun'] = relationship(back_populates='results')


class HumanReview(Base):
    __tablename__ = 'human_reviews'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str] = mapped_column(ForeignKey('evaluation_results.id'), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), default='reviewer')
    verdict: Mapped[str] = mapped_column(String(32), default='pass')
    note: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
