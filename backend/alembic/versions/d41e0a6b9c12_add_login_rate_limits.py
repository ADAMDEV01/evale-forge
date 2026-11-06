"""Add persistent login rate-limit buckets.

Revision ID: d41e0a6b9c12
Revises: ce4d8129ab31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd41e0a6b9c12'
down_revision: Union[str, None] = 'ce4d8129ab31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'auth_login_attempts',
        sa.Column('key_hash', sa.String(length=64), primary_key=True),
        sa.Column('window_started_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('auth_login_attempts')
