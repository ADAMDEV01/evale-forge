"""Add durable evaluation job queue.

Revision ID: 4b7e2c91a6d0
Revises: d41e0a6b9c12
Create Date: 2026-11-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4b7e2c91a6d0'
down_revision: Union[str, None] = 'd41e0a6b9c12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'evaluation_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('lock_owner', sa.String(length=64), nullable=True),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('Pending', 'Running', 'Completed', 'Failed', 'Cancelled')",
            name='ck_evaluation_jobs_status',
        ),
        sa.CheckConstraint('attempts >= 0', name='ck_evaluation_jobs_attempts_nonnegative'),
        sa.ForeignKeyConstraint(['run_id'], ['evaluation_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', name='uq_evaluation_jobs_run_id'),
    )
    op.create_index(
        'ix_evaluation_jobs_claim',
        'evaluation_jobs',
        ['status', 'available_at', 'locked_at'],
    )
    op.create_index(
        'ix_evaluation_jobs_user_id',
        'evaluation_jobs',
        ['user_id'],
    )
    op.create_index(
        'ix_evaluation_jobs_user_created',
        'evaluation_jobs',
        ['user_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_evaluation_jobs_user_created', table_name='evaluation_jobs')
    op.drop_index('ix_evaluation_jobs_user_id', table_name='evaluation_jobs')
    op.drop_index('ix_evaluation_jobs_claim', table_name='evaluation_jobs')
    op.drop_table('evaluation_jobs')
