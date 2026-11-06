from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.models.models import (
    AuthRefreshToken,
    Dataset,
    DatasetVersion,
    EvaluationResult,
    EvaluationRun,
    HumanReview,
    Rubric,
    RubricCriterion,
    TestCase,
    User,
)

OWNED_MODELS = (Dataset, Rubric, EvaluationRun)


class OwnershipAdoptionError(RuntimeError):
    pass


def _find_legacy_reference_issues(session: Session) -> list[str]:
    checks = (
        (
            'dataset_versions.dataset_id',
            select(DatasetVersion.id)
            .outerjoin(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(Dataset.id.is_(None)),
        ),
        (
            'test_cases.dataset_id',
            select(TestCase.id)
            .outerjoin(Dataset, Dataset.id == TestCase.dataset_id)
            .where(Dataset.id.is_(None)),
        ),
        (
            'test_cases.dataset_version_id',
            select(TestCase.id)
            .outerjoin(
                DatasetVersion,
                (DatasetVersion.id == TestCase.dataset_version_id)
                & (DatasetVersion.dataset_id == TestCase.dataset_id),
            )
            .where(
                TestCase.dataset_version_id.is_not(None),
                DatasetVersion.id.is_(None),
            ),
        ),
        (
            'evaluation_runs.dataset_id',
            select(EvaluationRun.id)
            .outerjoin(Dataset, Dataset.id == EvaluationRun.dataset_id)
            .where(Dataset.id.is_(None)),
        ),
        (
            'evaluation_runs.rubric_id',
            select(EvaluationRun.id)
            .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
            .where(
                EvaluationRun.rubric_id.is_not(None),
                Rubric.id.is_(None),
            ),
        ),
        (
            'rubric_criteria.rubric_id',
            select(RubricCriterion.id)
            .outerjoin(Rubric, Rubric.id == RubricCriterion.rubric_id)
            .where(Rubric.id.is_(None)),
        ),
        (
            'evaluation_results.run_id',
            select(EvaluationResult.id)
            .outerjoin(EvaluationRun, EvaluationRun.id == EvaluationResult.run_id)
            .where(EvaluationRun.id.is_(None)),
        ),
        (
            'human_reviews.result_id',
            select(HumanReview.id)
            .outerjoin(EvaluationResult, EvaluationResult.id == HumanReview.result_id)
            .where(EvaluationResult.id.is_(None)),
        ),
        (
            'auth_refresh_tokens.user_id',
            select(AuthRefreshToken.id)
            .outerjoin(User, User.id == AuthRefreshToken.user_id)
            .where(User.id.is_(None)),
        ),
    )
    return [
        reference
        for reference, query in checks
        if session.scalar(query.limit(1)) is not None
    ]


def adopt_unowned_records(
    session: Session,
    designated_admin_user_id: str | None,
) -> dict[str, int]:
    if not designated_admin_user_id or not designated_admin_user_id.strip():
        raise OwnershipAdoptionError(
            'A designated administrator user ID is required; no owner was assigned.'
        )

    administrator = session.get(User, designated_admin_user_id)
    if administrator is None or not administrator.is_active:
        raise OwnershipAdoptionError(
            'The designated administrator must exist and be active; no owner was assigned.'
        )

    legacy_issues = _find_legacy_reference_issues(session)
    if legacy_issues:
        raise OwnershipAdoptionError(
            'Ownership adoption stopped because legacy references are orphaned or inconsistent: '
            + ', '.join(legacy_issues)
        )

    conflicting_owners = sorted({
        user_id
        for model in OWNED_MODELS
        for user_id in session.scalars(
            select(model.user_id).where(
                model.user_id.is_not(None),
                model.user_id != designated_admin_user_id,
            )
        ).all()
    })
    if conflicting_owners:
        raise OwnershipAdoptionError(
            'Ownership adoption stopped because records already belong to another user.'
        )

    inconsistent_runs = session.scalars(
        select(EvaluationRun.id)
        .outerjoin(Dataset, Dataset.id == EvaluationRun.dataset_id)
        .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
        .where(
            (
                EvaluationRun.user_id.is_not(None)
                & Dataset.user_id.is_not(None)
                & (EvaluationRun.user_id != Dataset.user_id)
            )
            | (
                EvaluationRun.rubric_id.is_not(None)
                & EvaluationRun.user_id.is_not(None)
                & Rubric.user_id.is_not(None)
                & (EvaluationRun.user_id != Rubric.user_id)
            )
        )
        .limit(1)
    ).first()
    if inconsistent_runs:
        raise OwnershipAdoptionError(
            'Ownership adoption stopped because a run, dataset, or rubric has inconsistent owners.'
        )

    updates: dict[str, int] = {}
    try:
        for model in OWNED_MODELS:
            result = session.execute(
                update(model)
                .where(model.user_id.is_(None))
                .values(user_id=designated_admin_user_id)
                .execution_options(synchronize_session=False)
            )
            updates[model.__tablename__] = result.rowcount or 0

        session.commit()
    except Exception:
        session.rollback()
        raise

    return updates
