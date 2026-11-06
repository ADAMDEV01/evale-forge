from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.database import engine, get_db
from backend.app.db.schema_lifecycle import verify_database_readiness
from backend.app.models.models import Dataset, EvaluationResult, EvaluationRun, HumanReview, Rubric, RubricCriterion, TestCase, User
from backend.app.routes.auth import router as auth_router
from backend.app.schemas.schemas import (
    DatasetSchema,
    EvaluationRequest,
    EvaluationResultSchema,
    EvaluationRunCreateSchema,
    EvaluationRunSchema,
    FailureSchema,
    HealthResponse,
    RubricSchema,
    TestCaseSchema,
)
from backend.app.security.auth import allowed_cors_origins, get_current_user, validate_production_auth_settings
from backend.app.services.evaluation_service import (
    calculate_metrics,
    estimate_provider_cost,
    evaluate_exact_match,
    evaluate_keyword_match,
    evaluate_rubric,
)
from backend.app.services.provider_orchestration import ProviderExecutionError, check_model_if_supported, execute_provider
from backend.app.services.providers import AIProvider, GeneratedResponse, ProviderError, configured_model, create_provider

logger = logging.getLogger(__name__)


class RunFailurePersistenceError(Exception):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_auth_settings()
    verify_database_readiness(engine)
    yield


app = FastAPI(title='EvalForge API', version='1.0.0', lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
)

protected_router = APIRouter(dependencies=[Depends(get_current_user)])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


def _owned_dataset(db: Session, user: User, dataset_id: str) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.user_id == user.id,
        )
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail='Dataset not found')
    return dataset


def _owned_rubric(db: Session, user: User, rubric_id: str) -> Rubric:
    rubric = db.scalar(
        select(Rubric).where(
            Rubric.id == rubric_id,
            Rubric.user_id == user.id,
        )
    )
    if rubric is None:
        raise HTTPException(status_code=404, detail='Rubric not found')
    return rubric


def _owned_runs_statement(user: User):
    return (
        select(EvaluationRun)
        .join(Dataset, Dataset.id == EvaluationRun.dataset_id)
        .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
        .where(
            EvaluationRun.user_id == user.id,
            Dataset.user_id == user.id,
            or_(
                EvaluationRun.rubric_id.is_(None),
                Rubric.user_id == user.id,
            ),
        )
    )


def _owned_run(db: Session, user: User, run_id: str) -> EvaluationRun:
    run = db.scalar(_owned_runs_statement(user).where(EvaluationRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail='Evaluation run not found')
    return run


def _owned_result(db: Session, user: User, result_id: str) -> EvaluationResult:
    owned_run_ids = _owned_runs_statement(user).with_only_columns(EvaluationRun.id)
    result = db.scalar(
        select(EvaluationResult).where(
            EvaluationResult.id == result_id,
            EvaluationResult.run_id.in_(owned_run_ids),
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail='Failure not found')
    return result


def _owned_test_case(db: Session, user: User, case_id: str) -> TestCase:
    case = db.scalar(
        select(TestCase)
        .join(Dataset, Dataset.id == TestCase.dataset_id)
        .where(
            TestCase.id == case_id,
            Dataset.user_id == user.id,
        )
    )
    if case is None:
        raise HTTPException(status_code=404, detail='Test case not found')
    return case


def _json_or(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _run_schema(item: EvaluationRun, persisted_results_count: int) -> EvaluationRunSchema:
    return EvaluationRunSchema(
        id=item.id,
        dataset=item.dataset_name or item.dataset_id,
        datasetVersion=item.dataset_version,
        model=item.model,
        provider=item.provider,
        evaluationMethod=item.evaluation_method,
        accuracy=item.accuracy,
        passRate=item.pass_rate,
        latency=item.latency,
        status=item.status,
        date=item.date,
        passed=item.passed,
        failed=item.failed,
        total=item.total,
        config=_json_or(item.config_json, {}),
        tokenUsage=item.token_usage,
        estimatedCost=item.estimated_cost,
        errorType=item.error_type,
        errorMessage=item.error_message,
        persisted_results_count=persisted_results_count,
    )


def _result_schema(item: EvaluationResult) -> EvaluationResultSchema:
    return EvaluationResultSchema(
        id=item.id,
        testCaseId=item.test_case_id,
        testCaseTitle=item.test_case_title or item.test_case_id,
        category=item.category,
        status=item.status,
        score=item.score,
        latencyMs=item.latency_ms,
        input=item.input_snapshot,
        expected=item.expected,
        actual=item.actual,
        passed=item.passed,
        evaluationMethod=item.evaluation_method,
        tokenUsage=item.token_usage,
        criteriaBreakdown=_json_or(item.criteria_breakdown_json, []),
        errorType=item.error_type,
        errorMessage=item.error_message,
    )


@app.get('/api/health', response_model=HealthResponse)
def health() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/api/providers/{provider_name}/health')
def provider_health(provider_name: str, model: str | None = Query(default=None)):
    try:
        provider = create_provider(provider_name, model)
        try:
            model_checked = check_model_if_supported(provider)
            return {
                'provider': provider_name,
                'available': True,
                'model': provider.model,
                'modelInstalled': True if model_checked else None,
                'error': None,
            }
        finally:
            provider.close()
    except ProviderError as error:
        return {
            'provider': provider_name,
            'available': False,
            'model': model or configured_model(provider_name),
            'modelInstalled': False if error.code == 'model_not_found' else None,
            'error': {'code': error.code, 'message': error.message},
        }


@protected_router.get('/api/datasets')
def list_datasets(
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    datasets = db.scalars(
        select(Dataset).where(Dataset.user_id == user.id)
    ).all()
    return [
        DatasetSchema(
            id=item.id,
            name=item.name,
            description=item.description,
            version=item.version,
            cases=item.cases,
            createdAt=item.created_at.date().isoformat(),
            modifiedAt=item.modified_at.date().isoformat(),
            color=item.color or 'violet',
        ).model_dump()
        for item in datasets
    ]


@protected_router.post('/api/datasets')
def create_dataset(
    payload: DatasetSchema,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    dataset = db.scalar(
        select(Dataset).where(
            Dataset.id == payload.id,
            Dataset.user_id == user.id,
        )
    )
    if dataset is None and db.get(Dataset, payload.id) is not None:
        raise HTTPException(status_code=404, detail='Dataset not found')
    if not dataset:
        dataset = Dataset(
            id=payload.id,
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            version=payload.version,
            cases=payload.cases,
            color=payload.color,
        )
        db.add(dataset)
    else:
        dataset.name = payload.name
        dataset.description = payload.description
        dataset.version = payload.version
        dataset.cases = payload.cases
        dataset.color = payload.color
        dataset.modified_at = datetime.utcnow()
    db.commit()
    return list_datasets(db, user)


@protected_router.delete('/api/datasets/{dataset_id}')
def delete_dataset(
    dataset_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    dataset = _owned_dataset(db, user, dataset_id)
    evaluation_run_id = db.scalar(
        select(EvaluationRun.id)
        .where(
            EvaluationRun.dataset_id == dataset_id,
        )
        .limit(1)
    )
    if evaluation_run_id is not None:
        raise HTTPException(
            status_code=409,
            detail='The dataset cannot be permanently deleted because evaluation history exists. Keep the dataset to preserve its history.',
        )
    db.delete(dataset)
    db.commit()
    return {'deleted': dataset_id}


@protected_router.get('/api/test-cases')
def list_test_cases(
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    rows = db.scalars(
        select(TestCase)
        .join(Dataset, Dataset.id == TestCase.dataset_id)
        .where(Dataset.user_id == user.id)
    ).all()
    return [
        TestCaseSchema(
            id=item.id,
            datasetId=item.dataset_id,
            title=item.title,
            input=item.input,
            expected=item.expected,
            expectedKeywords=_json_or(item.expected_keywords, []),
            criteria=item.criteria,
            category=item.category,
            tags=(item.tags.split(',') if item.tags else []),
            importance=item.importance,
            expectedBehavior=item.expected_behavior,
        ).model_dump()
        for item in rows
    ]


@protected_router.post('/api/test-cases')
def create_test_case(
    payload: TestCaseSchema,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    _owned_dataset(db, user, payload.datasetId)
    case = db.scalar(
        select(TestCase)
        .join(Dataset, Dataset.id == TestCase.dataset_id)
        .where(
            TestCase.id == payload.id,
            Dataset.user_id == user.id,
        )
    )
    if case is None and db.get(TestCase, payload.id) is not None:
        raise HTTPException(status_code=404, detail='Test case not found')
    if not case:
        case = TestCase(
            id=payload.id,
            dataset_id=payload.datasetId,
            title=payload.title,
            input=payload.input,
            expected=payload.expected,
            expected_keywords=json.dumps(payload.expectedKeywords),
            criteria=payload.criteria,
            category=payload.category,
            tags=','.join(payload.tags),
            importance=payload.importance,
            expected_behavior=payload.expectedBehavior,
        )
        db.add(case)
    else:
        case.dataset_id = payload.datasetId
        case.title = payload.title
        case.input = payload.input
        case.expected = payload.expected
        case.expected_keywords = json.dumps(payload.expectedKeywords)
        case.criteria = payload.criteria
        case.category = payload.category
        case.tags = ','.join(payload.tags)
        case.importance = payload.importance
        case.expected_behavior = payload.expectedBehavior
    db.commit()
    return list_test_cases(db, user)


@protected_router.delete('/api/test-cases/{case_id}')
def delete_test_case(
    case_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    case = _owned_test_case(db, user, case_id)
    db.delete(case)
    db.commit()
    return {'deleted': case_id}


@protected_router.get('/api/failures')
def list_failures(
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    rows = db.execute(
        select(EvaluationResult, EvaluationRun)
        .join(EvaluationRun, EvaluationResult.run_id == EvaluationRun.id)
        .join(Dataset, Dataset.id == EvaluationRun.dataset_id)
        .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
        .where(
            EvaluationRun.user_id == user.id,
            Dataset.user_id == user.id,
            or_(
                EvaluationRun.rubric_id.is_(None),
                Rubric.user_id == user.id,
            ),
            EvaluationRun.provider == 'ollama',
            EvaluationRun.status.in_(('Completed', 'Failed')),
            or_(
                and_(
                    EvaluationResult.status == 'Completed',
                    EvaluationResult.passed.is_(False),
                ),
                EvaluationResult.status == 'Error',
            ),
        )
    ).all()
    reviews = db.scalars(
        select(HumanReview)
        .join(EvaluationResult, EvaluationResult.id == HumanReview.result_id)
        .join(EvaluationRun, EvaluationRun.id == EvaluationResult.run_id)
        .join(Dataset, Dataset.id == EvaluationRun.dataset_id)
        .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
        .where(
            EvaluationRun.user_id == user.id,
            Dataset.user_id == user.id,
            or_(
                EvaluationRun.rubric_id.is_(None),
                Rubric.user_id == user.id,
            ),
        )
        .order_by(HumanReview.created_at)
    ).all()
    reviews_by_result = {
        review.result_id: review
        for review in reviews
    }
    return [
        FailureSchema(
            id=result.id,
            testCase=result.test_case_title or result.test_case_id,
            dataset=run.dataset_name or run.dataset_id,
            model=run.model,
            run_status=run.status,
            run_provider=run.provider,
            failure_type=(
                'evaluation_error'
                if result.status == 'Error'
                else 'evaluation_failure'
            ),
            category=result.category or 'Incorrect information',
            score=result.score,
            timestamp=run.date,
            input=result.input_snapshot,
            expected=result.expected,
            actual=result.actual,
            explanation=result.error_message or 'The generated response did not meet the evaluation criteria.',
            reviewed=result.id in reviews_by_result,
            note=reviews_by_result[result.id].note if result.id in reviews_by_result else None,
            humanJudgment=reviews_by_result[result.id].verdict if result.id in reviews_by_result else None,
        ).model_dump()
        for result, run in rows
    ]


@protected_router.put('/api/failures/{failure_id}')
def update_failure(
    failure_id: str,
    payload: FailureSchema,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    row = _owned_result(db, user, failure_id)
    row.error_message = payload.explanation
    if payload.reviewed:
        if payload.humanJudgment not in ('pass', 'fail'):
            raise HTTPException(
                status_code=400,
                detail='A human judgment (pass or fail) is required.'
            )
        review = db.scalars(
            select(HumanReview)
            .where(
                HumanReview.result_id == failure_id,
                HumanReview.result_id.in_(
                    select(EvaluationResult.id)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationResult.run_id)
                    .join(Dataset, Dataset.id == EvaluationRun.dataset_id)
                    .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
                    .where(
                        EvaluationRun.user_id == user.id,
                        Dataset.user_id == user.id,
                        or_(
                            EvaluationRun.rubric_id.is_(None),
                            Rubric.user_id == user.id,
                        ),
                    )
                ),
            )
            .order_by(HumanReview.created_at.desc())
        ).first()
        if review:
            review.verdict = payload.humanJudgment
            review.note = payload.note or ''
        else:
            review = HumanReview(
                id=uuid.uuid4().hex,
                result_id=failure_id,
                reviewer=user.email,
                verdict=payload.humanJudgment,
                note=payload.note or '',
            )
            db.add(review)
    db.commit()
    return list_failures(db, user)


@protected_router.get('/api/runs')
def list_runs(
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    rows = db.scalars(
        _owned_runs_statement(user).order_by(EvaluationRun.created_at.desc())
    ).all()
    if not rows:
        return []
    result_counts = db.execute(
        select(EvaluationResult.run_id, func.count(EvaluationResult.id))
        .where(EvaluationResult.run_id.in_([item.id for item in rows]))
        .group_by(EvaluationResult.run_id)
    ).all()
    counts_by_run_id = {run_id: count for run_id, count in result_counts}
    return [
        _run_schema(item, counts_by_run_id.get(item.id, 0)).model_dump()
        for item in rows
    ]


@protected_router.post('/api/runs')
def create_run(
    payload: EvaluationRunCreateSchema,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    dataset = _owned_dataset(db, user, payload.dataset_id)
    existing = db.scalar(
        _owned_runs_statement(user).where(EvaluationRun.id == payload.id)
    )
    if existing is None and db.get(EvaluationRun, payload.id) is not None:
        raise HTTPException(status_code=404, detail='Evaluation run not found')
    if existing is None:
        existing = EvaluationRun(
            id=payload.id,
            user_id=user.id,
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            dataset_version=payload.datasetVersion,
            model=payload.model,
            provider=payload.provider,
            evaluation_method=payload.evaluationMethod,
            status=payload.status,
            accuracy=payload.accuracy,
            pass_rate=payload.passRate,
            latency=payload.latency,
            passed=payload.passed,
            failed=payload.failed,
            total=payload.total,
            date=payload.date,
            config_json=json.dumps(payload.config or {}),
            token_usage=payload.tokenUsage,
            estimated_cost=payload.estimatedCost,
            error_type=payload.errorType,
            error_message=payload.errorMessage,
        )
        db.add(existing)
    else:
        existing.dataset_id = dataset.id
        existing.dataset_name = dataset.name
        existing.dataset_version = payload.datasetVersion
        existing.model = payload.model
        existing.provider = payload.provider
        existing.evaluation_method = payload.evaluationMethod
        existing.status = payload.status
        existing.accuracy = payload.accuracy
        existing.pass_rate = payload.passRate
        existing.latency = payload.latency
        existing.passed = payload.passed
        existing.failed = payload.failed
        existing.total = payload.total
        existing.date = payload.date
        existing.config_json = json.dumps(payload.config or {})
        existing.token_usage = payload.tokenUsage
        existing.estimated_cost = payload.estimatedCost
        existing.error_type = payload.errorType
        existing.error_message = payload.errorMessage
    db.commit()
    return list_runs(db, user)


@protected_router.get('/api/runs/{run_id}')
def get_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    run = _owned_run(db, user, run_id)
    results = db.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run.id)
        .order_by(EvaluationResult.sequence)
    ).all()
    metrics = calculate_metrics([
        {
            'status': item.status,
            'passed': item.passed,
            'score': item.score,
            'latency_ms': item.latency_ms,
            'token_usage': item.token_usage,
        }
        for item in results
    ]).model_dump()
    return {
        'run': _run_schema(run, len(results)).model_dump(),
        'results': [_result_schema(item).model_dump() for item in results],
        'metrics': metrics,
        'errors': sum(1 for item in results if item.status == 'Error'),
    }


@protected_router.get('/api/rubrics')
def list_rubrics(
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    rows = db.scalars(
        select(Rubric).where(Rubric.user_id == user.id)
    ).all()
    return [
        RubricSchema(
            id=item.id,
            name=item.name,
            description=item.description,
            active=item.active,
            criteria=[
                {
                    'id': criterion.id,
                    'name': criterion.name,
                    'description': criterion.description,
                    'weight': criterion.weight,
                    'scale': criterion.scale,
                    'expectedKeywords': _json_or(criterion.expected_keywords, []),
                }
                for criterion in item.criteria
            ],
        ).model_dump()
        for item in rows
    ]


@protected_router.post('/api/rubrics')
def create_rubric(
    payload: RubricSchema,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    rubric = db.scalar(
        select(Rubric).where(
            Rubric.id == payload.id,
            Rubric.user_id == user.id,
        )
    )
    if rubric is None and db.get(Rubric, payload.id) is not None:
        raise HTTPException(status_code=404, detail='Rubric not found')
    criterion_ids = [
        criterion.id or f'{payload.id}-{criterion.name.lower().replace(" ", "-")}'
        for criterion in payload.criteria
    ]
    if len(criterion_ids) != len(set(criterion_ids)):
        raise HTTPException(status_code=422, detail='Rubric criterion IDs must be unique.')
    for criterion_id in criterion_ids:
        criterion_owner = db.scalar(
            select(RubricCriterion.rubric_id).where(
                RubricCriterion.id == criterion_id
            )
        )
        if criterion_owner is not None and (
            rubric is None or criterion_owner != rubric.id
        ):
            raise HTTPException(status_code=404, detail='Rubric criterion not found')

    criteria = [
        {
            'name': criterion.name,
            'weight': criterion.weight,
            'scale': criterion.scale,
            'expectedKeywords': criterion.expectedKeywords,
        }
        for criterion in payload.criteria
    ]
    try:
        evaluate_rubric('', criteria)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if rubric is None:
        rubric = Rubric(
            id=payload.id,
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            active=payload.active,
        )
        db.add(rubric)
    else:
        rubric.name = payload.name
        rubric.description = payload.description
        rubric.active = payload.active
    for criterion in rubric.criteria:
        db.delete(criterion)
    for criterion, criterion_id in zip(payload.criteria, criterion_ids):
        db.add(RubricCriterion(
            id=criterion_id,
            rubric_id=payload.id,
            name=criterion.name,
            description=criterion.description,
            weight=criterion.weight,
            scale=criterion.scale,
            expected_keywords=json.dumps(criterion.expectedKeywords),
        ))
    db.commit()
    return list_rubrics(db, user)


def _persist_run_failure(
    db: Session,
    run_id: str,
    user_id: str,
    error_type: str,
    error_message: str,
) -> None:
    try:
        db.rollback()
        run = db.scalar(
            select(EvaluationRun)
            .join(Dataset, Dataset.id == EvaluationRun.dataset_id)
            .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.user_id == user_id,
                Dataset.user_id == user_id,
                or_(
                    EvaluationRun.rubric_id.is_(None),
                    Rubric.user_id == user_id,
                ),
            )
        )
        if run is None:
            raise RunFailurePersistenceError(f'Evaluation run {run_id} could not be reloaded.')
        persisted_results = db.scalars(
            select(EvaluationResult)
            .where(
                EvaluationResult.run_id.in_(
                    select(EvaluationRun.id)
                    .join(Dataset, Dataset.id == EvaluationRun.dataset_id)
                    .outerjoin(Rubric, Rubric.id == EvaluationRun.rubric_id)
                    .where(
                        EvaluationRun.id == run_id,
                        EvaluationRun.user_id == user_id,
                        Dataset.user_id == user_id,
                        or_(
                            EvaluationRun.rubric_id.is_(None),
                            Rubric.user_id == user_id,
                        ),
                    )
                )
            )
        ).all()
        _update_run_metrics(run, persisted_results)
        run.status = 'Failed'
        run.error_type = error_type
        run.error_message = error_message
        db.commit()
    except SQLAlchemyError as recovery_error:
        try:
            db.rollback()
        except SQLAlchemyError as rollback_error:
            recovery_error.add_note(f'Rollback after failure-state persistence also failed: {rollback_error}')
        recovery_details = [str(recovery_error), *getattr(recovery_error, '__notes__', [])]
        raise RunFailurePersistenceError(
            f'Could not persist Failed status for evaluation run {run_id}: {"; ".join(recovery_details)}'
        ) from recovery_error


def _raise_provider_error(
    error: ProviderError,
    run: EvaluationRun,
    db: Session,
    user_id: str,
) -> None:
    detail: dict[str, Any] = {'code': error.code, 'message': error.message, 'runId': run.id}
    try:
        _persist_run_failure(db, run.id, user_id, error.code, error.message)
    except RunFailurePersistenceError as recovery_error:
        logger.error('Could not persist failed status for run %s: %s', run.id, recovery_error)
        detail['failureStatusPersisted'] = False
        detail['persistenceError'] = str(recovery_error)
    status_code = {
        'provider_connection': 503,
        'model_not_found': 422,
        'provider_timeout': 504,
        'provider_rate_limit': 429,
        'provider_response': 502,
        'provider_configuration': 400,
    }.get(error.code, 502)
    if 'failureStatusPersisted' not in detail:
        detail['failureStatusPersisted'] = True
    raise HTTPException(status_code=status_code, detail=detail) from error


def _update_run_metrics(run: EvaluationRun, persisted_results: list[EvaluationResult]) -> None:
    metric_rows = [
        {
            'status': result.status,
            'passed': result.passed,
            'score': result.score,
            'latency_ms': result.latency_ms,
            'token_usage': result.token_usage,
        }
        for result in persisted_results
    ]
    summary = calculate_metrics(metric_rows).model_dump()
    run.accuracy = summary['accuracy']
    run.pass_rate = summary['passRate']
    run.latency = int(summary['averageLatency'])
    run.score = summary['averageScore']
    run.passed = sum(1 for row in metric_rows if row['status'] == 'Completed' and row['passed'])
    run.failed = sum(1 for row in metric_rows if row['status'] == 'Completed' and not row['passed'])
    run.token_usage = summary['tokenUsage']



def _raise_unexpected_provider_error(
    error: Exception,
    stage: str,
    run: EvaluationRun,
    db: Session,
    user_id: str,
) -> None:
    logger.error(
        'Unexpected provider %s error for run %s',
        stage,
        run.id,
        exc_info=(type(error), error, error.__traceback__),
    )
    error_code = f'provider_{stage}'
    message = f'An unexpected error occurred during provider {stage}.'
    detail: dict[str, Any] = {'code': error_code, 'message': message, 'runId': run.id}
    try:
        _persist_run_failure(db, run.id, user_id, error_code, message)
    except RunFailurePersistenceError as recovery_error:
        logger.error('Could not persist failed status for run %s: %s', run.id, recovery_error)
        detail['failureStatusPersisted'] = False
        detail['persistenceError'] = str(recovery_error)
    if 'failureStatusPersisted' not in detail:
        detail['failureStatusPersisted'] = True
    raise HTTPException(
        status_code=500,
        detail=detail,
    ) from error


def _commit_evaluation(
    db: Session,
    run_id: str,
    user_id: str,
) -> None:
    try:
        db.commit()
    except SQLAlchemyError as error:
        message = 'Evaluation results could not be persisted.'
        detail: dict[str, Any] = {
            'code': 'evaluation_persistence',
            'message': message,
            'runId': run_id,
        }
        try:
            _persist_run_failure(db, run_id, user_id, 'evaluation_persistence', message)
            detail['failureStatusPersisted'] = True
        except RunFailurePersistenceError as recovery_error:
            logger.error('Result persistence and failure recovery failed for run %s: %s', run_id, recovery_error)
            detail.update({
                'message': 'Evaluation results and the run failure status could not be persisted.',
                'failureStatusPersisted': False,
                'originalError': str(error),
                'recoveryError': str(recovery_error),
            })
        raise HTTPException(
            status_code=500,
            detail=detail,
        ) from error


@protected_router.post('/api/evaluate')
def evaluate(
    payload: EvaluationRequest,
    db: Annotated[Session, Depends(get_db)],
    user: AuthenticatedUser,
):
    dataset = _owned_dataset(db, user, payload.datasetId)
    cases = db.scalars(
        select(TestCase).where(TestCase.dataset_id == dataset.id)
    ).all()
    if not cases:
        raise HTTPException(status_code=400, detail='Dataset has no test cases for evaluation.')
    model = payload.model.strip() or (payload.models[0].strip() if len(payload.models) == 1 else '')
    if payload.models and (len(payload.models) != 1 or payload.model.strip()):
        raise HTTPException(status_code=422, detail='An evaluation requires exactly one model.')
    if payload.evaluationMethod == 'exact_match' and any(not case.expected.strip() for case in cases):
        raise HTTPException(status_code=422, detail='Exact Match requires an expected response for every test case.')
    if payload.evaluationMethod == 'keyword_match' and any(not _json_or(case.expected_keywords, []) for case in cases):
        raise HTTPException(status_code=422, detail='Keyword Match requires expected keywords for every test case.')

    rubric = None
    criteria: list[dict[str, Any]] = []
    if payload.evaluationMethod == 'rubric':
        rubric = db.scalars(
            select(Rubric).where(
                Rubric.user_id == user.id,
                (Rubric.id == payload.rubric) | (Rubric.name == payload.rubric),
            )
        ).first()
        if rubric is None:
            if db.get(Rubric, payload.rubric) is not None:
                raise HTTPException(status_code=404, detail='Rubric not found')
            raise HTTPException(status_code=422, detail=f'Rubric "{payload.rubric}" was not found.')
        criteria = [
            {
                'name': criterion.name,
                'weight': criterion.weight,
                'description': criterion.description,
                'scale': criterion.scale,
                'expectedKeywords': _json_or(criterion.expected_keywords, []),
            }
            for criterion in rubric.criteria
        ]
        try:
            evaluate_rubric('', criteria)
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    config = {
        'provider': payload.provider,
        'model': model,
        'evaluationMethod': payload.evaluationMethod,
        'temperature': payload.temperature,
    }
    run = EvaluationRun(
        id=f'run_{uuid.uuid4().hex[:12]}',
        user_id=user.id,
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        model=model or 'configured Ollama model',
        provider=payload.provider,
        evaluation_method=payload.evaluationMethod,
        rubric_id=rubric.id if rubric else None,
        rubric_snapshot_json=json.dumps(
            {'id': rubric.id, 'name': rubric.name, 'criteria': criteria} if rubric else {}
        ),
        status='Pending',
        total=len(cases),
        date=datetime.now().astimezone().isoformat(),
        config_json=json.dumps(config),
    )
    db.add(run)
    _commit_evaluation(db, run.id, user.id)
    run.status = 'Running'
    _commit_evaluation(db, run.id, user.id)

    def persist_provider_model(provider: AIProvider) -> None:
        run.model = provider.model
        config['model'] = provider.model
        run.config_json = json.dumps(config)
        try:
            db.commit()
        except SQLAlchemyError as error:
            message = 'The resolved provider model could not be persisted.'
            recovery_error = None
            try:
                _persist_run_failure(db, run.id, user.id, 'evaluation_persistence', message)
            except RunFailurePersistenceError as failure_error:
                recovery_error = failure_error
                logger.error('Could not persist failed status for run %s: %s', run.id, failure_error)
            raise ProviderExecutionError(
                error,
                'persistence',
                recovery_error,
            ) from error

    processed: list[dict[str, Any]] = []
    engine_errors = 0
    estimated_cost_total = 0.0
    cost_estimate_complete = True
    case_iterator = iter(enumerate(cases))

    def persist_response(generated: GeneratedResponse) -> None:
        nonlocal engine_errors, estimated_cost_total, cost_estimate_complete
        sequence, case = next(case_iterator)

        try:
            if payload.evaluationMethod == 'exact_match':
                outcome = evaluate_exact_match(generated.text, case.expected)
            elif payload.evaluationMethod == 'keyword_match':
                outcome = evaluate_keyword_match(generated.text, _json_or(case.expected_keywords, []))
            else:
                outcome = evaluate_rubric(generated.text, criteria)
            result_status = 'Completed'
            error_type = None
            error_message = None
        except (ValueError, KeyError, TypeError) as error:
            outcome = {'passed': False, 'score': 0.0, 'breakdown': []}
            result_status = 'Error'
            error_type = 'evaluation_engine'
            error_message = str(error)
            engine_errors += 1

        case_cost = estimate_provider_cost(payload.provider, generated.prompt_tokens, generated.completion_tokens)
        if case_cost is None:
            cost_estimate_complete = False
        else:
            estimated_cost_total += case_cost
        run.estimated_cost = round(estimated_cost_total, 10) if cost_estimate_complete else None

        row = {
            'status': result_status,
            'passed': outcome['passed'],
            'score': outcome['score'],
            'latency_ms': generated.latency_ms,
            'token_usage': generated.total_tokens,
            'estimated_cost': case_cost,
        }
        processed.append(row)
        db.add(EvaluationResult(
            id=f'res_{uuid.uuid4().hex[:12]}',
            run_id=run.id,
            test_case_id=case.id,
            sequence=sequence,
            test_case_title=case.title,
            category=case.category,
            input_snapshot=case.input,
            expected=case.expected,
            evaluation_method=payload.evaluationMethod,
            status=result_status,
            score=outcome['score'],
            latency_ms=generated.latency_ms,
            actual=generated.text,
            passed=outcome['passed'],
            token_usage=generated.total_tokens,
            criteria_breakdown_json=json.dumps(outcome.get('breakdown', [])),
            error_type=error_type,
            error_message=error_message,
        ))
        _commit_evaluation(db, run.id, user.id)

    try:
        execute_provider(
            create_provider,
            payload.provider,
            model or None,
            (case.input for case in cases),
            payload.temperature,
            persist_provider_model,
            persist_response,
        )
    except ProviderExecutionError as execution_error:
        if isinstance(execution_error.error, ProviderError):
            _raise_provider_error(execution_error.error, run, db, user.id)
        if execution_error.stage == 'persistence':
            detail: dict[str, Any] = {
                'code': 'evaluation_persistence',
                'message': 'The resolved provider model could not be persisted.',
                'runId': run.id,
                'originalError': str(execution_error.error),
                'failureStatusPersisted': execution_error.recovery_error is None,
            }
            if execution_error.recovery_error is not None:
                detail['recoveryError'] = str(execution_error.recovery_error)
            supplemental_errors = getattr(execution_error, '__notes__', [])
            if supplemental_errors:
                detail['supplementalErrors'] = supplemental_errors
            raise HTTPException(status_code=500, detail=detail) from execution_error.error
        _raise_unexpected_provider_error(
            execution_error.error,
            execution_error.stage,
            run,
            db,
            user.id,
        )
    except HTTPException:
        raise
    except Exception as error:
        _raise_unexpected_provider_error(error, 'processing', run, db, user.id)

    summary = calculate_metrics(processed).model_dump()
    run.accuracy = summary['accuracy']
    run.pass_rate = summary['passRate']
    run.latency = int(summary['averageLatency'])
    run.score = summary['averageScore']
    run.passed = sum(1 for row in processed if row.get('status') == 'Completed' and row.get('passed'))
    run.failed = sum(
        1 for row in processed if row.get('status') == 'Completed' and not row.get('passed')
    )
    token_counts = [row['token_usage'] for row in processed if row.get('token_usage') is not None]
    run.token_usage = sum(token_counts) if token_counts else None
    run.estimated_cost = summary['estimatedCost']
    run.status = 'Failed' if engine_errors else 'Completed'
    if engine_errors:
        run.error_type = 'evaluation_engine'
        run.error_message = f'{engine_errors} test case(s) could not be evaluated.'
    _commit_evaluation(db, run.id, user.id)
    results = db.scalars(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run.id)
        .order_by(EvaluationResult.sequence)
    ).all()
    return {
        'run': _run_schema(run, len(results)).model_dump(),
        'results': [_result_schema(item).model_dump() for item in results],
        'metrics': summary,
        'errors': engine_errors,
    }


app.include_router(auth_router)
app.include_router(protected_router)
