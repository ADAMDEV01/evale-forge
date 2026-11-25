from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update

from backend.app.db import database
from backend.app.models.models import EvaluationJob, EvaluationRun, User
from backend.app.schemas.schemas import EvaluationRequest

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
LEASE_DURATION = timedelta(minutes=5)
HEARTBEAT_INTERVAL_SECONDS = 30
MAX_RETRY_DELAY_SECONDS = 5 * 60
RETRYABLE_HTTP_STATUSES = {429, 502, 503, 504}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def retry_delay(attempts: int) -> timedelta:
    seconds = min(30 * (2 ** max(0, attempts - 1)), MAX_RETRY_DELAY_SECONDS)
    return timedelta(seconds=seconds)


def claim_next_job(*, worker_id: str, now: datetime | None = None) -> str | None:
    now = now or utcnow()
    expired_before = now - LEASE_DURATION

    with database.SessionLocal() as db:
        expired_jobs = db.scalars(
            select(EvaluationJob)
            .where(
                EvaluationJob.status == 'Running',
                EvaluationJob.locked_at < expired_before,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for expired in expired_jobs:
            expired.lock_owner = None
            expired.locked_at = None
            expired.updated_at = now
            run = db.get(EvaluationRun, expired.run_id)
            if expired.attempts >= MAX_ATTEMPTS:
                expired.status = 'Failed'
                expired.last_error = 'Worker lease expired after the final execution attempt.'
                if run is not None:
                    run.status = 'Failed'
                    run.error_type = 'worker_lease_expired'
                    run.error_message = expired.last_error
            else:
                expired.status = 'Pending'
                expired.available_at = now
                expired.last_error = 'Worker lease expired; job was returned to the queue.'
                if run is not None:
                    run.status = 'Pending'

        db.flush()
        job = db.scalar(
            select(EvaluationJob)
            .where(
                EvaluationJob.status == 'Pending',
                EvaluationJob.available_at <= now,
                EvaluationJob.attempts < MAX_ATTEMPTS,
            )
            .order_by(EvaluationJob.available_at, EvaluationJob.created_at, EvaluationJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            db.commit()
            return None

        job.status = 'Running'
        job.attempts += 1
        job.lock_owner = worker_id
        job.locked_at = now
        job.updated_at = now
        run = db.get(EvaluationRun, job.run_id)
        if run is not None:
            run.status = 'Running'
            run.error_type = None
            run.error_message = None
        db.commit()
        return job.id


def _heartbeat(job_id: str, worker_id: str, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
        now = utcnow()
        try:
            with database.SessionLocal() as db:
                result = db.execute(
                    update(EvaluationJob)
                    .where(
                        EvaluationJob.id == job_id,
                        EvaluationJob.status == 'Running',
                        EvaluationJob.lock_owner == worker_id,
                    )
                    .values(locked_at=now, updated_at=now)
                )
                db.commit()
                if result.rowcount != 1:
                    return
        except Exception:
            logger.exception('Could not renew evaluation worker lease for job %s', job_id)


def _complete_or_retry(
    job_id: str,
    worker_id: str,
    *,
    error: Exception | None = None,
    retryable: bool = False,
) -> None:
    now = utcnow()
    with database.SessionLocal() as db:
        job = db.scalar(
            select(EvaluationJob)
            .where(
                EvaluationJob.id == job_id,
                EvaluationJob.status == 'Running',
                EvaluationJob.lock_owner == worker_id,
            )
            .with_for_update()
        )
        if job is None:
            return
        run = db.get(EvaluationRun, job.run_id)

        if error is None:
            job.status = run.status if run and run.status in {'Completed', 'Failed', 'Cancelled'} else (
                'Cancelled' if job.cancel_requested else 'Completed'
            )
            if run is not None:
                run.status = job.status
            job.last_error = None
        elif job.cancel_requested:
            job.status = 'Cancelled'
            if run is not None:
                run.status = 'Cancelled'
        elif retryable and job.attempts < MAX_ATTEMPTS:
            job.status = 'Pending'
            job.available_at = now + retry_delay(job.attempts)
            job.last_error = str(error)[:2_000]
            if run is not None:
                run.status = 'Pending'
        else:
            job.status = 'Failed'
            job.last_error = str(error)[:2_000]
            if run is not None:
                run.status = 'Failed'
                run.error_type = 'worker_execution'
                run.error_message = str(error)[:2_000]

        job.lock_owner = None
        job.locked_at = None
        job.updated_at = now
        db.commit()


def process_job(job_id: str, *, worker_id: str) -> None:
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat,
        args=(job_id, worker_id, stop),
        name=f'evalforge-heartbeat-{job_id}',
        daemon=True,
    )
    heartbeat.start()

    try:
        with database.SessionLocal() as db:
            job = db.scalar(
                select(EvaluationJob).where(
                    EvaluationJob.id == job_id,
                    EvaluationJob.status == 'Running',
                    EvaluationJob.lock_owner == worker_id,
                )
            )
            if job is None:
                return
            user = db.get(User, job.user_id)
            if user is None or not user.is_active:
                raise RuntimeError('Evaluation owner is no longer active.')

            payload = json.loads(job.payload_json)
            request = EvaluationRequest.model_validate(payload['request'])

            # Import inside the process so tests and provider configuration can
            # patch the same application service used by the synchronous API.
            from backend.app import main

            result = main._execute_evaluation(
                request,
                db,
                user,
                existing_run_id=job.run_id,
                case_snapshot=payload['cases'],
                job_id=job.id,
            )
            status = result['run']['status']
            if status == 'Cancelled':
                _complete_or_retry(job_id, worker_id)
            elif status == 'Failed':
                _complete_or_retry(
                    job_id,
                    worker_id,
                    error=RuntimeError(result['run'].get('errorMessage') or 'Evaluation failed.'),
                    retryable=False,
                )
            else:
                _complete_or_retry(job_id, worker_id)
    except HTTPException as error:
        _complete_or_retry(
            job_id,
            worker_id,
            error=error,
            retryable=error.status_code in RETRYABLE_HTTP_STATUSES,
        )
    except Exception as error:
        logger.exception('Evaluation worker failed while processing job %s', job_id)
        _complete_or_retry(job_id, worker_id, error=error, retryable=False)
    finally:
        stop.set()
        heartbeat.join(timeout=1)


def run_once(*, worker_id: str | None = None, now: datetime | None = None) -> bool:
    worker_id = worker_id or uuid.uuid4().hex
    job_id = claim_next_job(worker_id=worker_id, now=now)
    if job_id is None:
        return False
    process_job(job_id, worker_id=worker_id)
    return True


def run_forever(*, poll_interval: float = 2.0, worker_id: str | None = None) -> None:
    if poll_interval < 0.25 or poll_interval > 60:
        raise ValueError('poll_interval must be between 0.25 and 60 seconds.')
    worker_id = worker_id or uuid.uuid4().hex
    logger.info('EvalForge worker %s started.', worker_id)
    while True:
        try:
            if not run_once(worker_id=worker_id):
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info('EvalForge worker %s stopping.', worker_id)
            return
        except Exception:
            logger.exception('Unexpected worker loop error.')
            time.sleep(poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the durable EvalForge evaluation worker.')
    parser.add_argument('--once', action='store_true', help='Process at most one queued evaluation.')
    parser.add_argument('--poll-interval', type=float, default=float(os.getenv('EVALUATION_WORKER_POLL_SECONDS', '2')))
    parser.add_argument('--worker-id', default=os.getenv('EVALUATION_WORKER_ID'))
    args = parser.parse_args()

    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
    if args.once:
        run_once(worker_id=args.worker_id)
    else:
        run_forever(poll_interval=args.poll_interval, worker_id=args.worker_id)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
