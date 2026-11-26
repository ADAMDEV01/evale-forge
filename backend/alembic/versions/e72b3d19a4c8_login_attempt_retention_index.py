"""Index login attempt buckets for bounded retention cleanup.

Revision ID: e72b3d19a4c8
Revises: d41e0a6b9c12
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e72b3d19a4c8'
down_revision: Union[str, None] = 'd41e0a6b9c12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_auth_login_attempts_updated_at',
        'auth_login_attempts',
        ['updated_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_auth_login_attempts_updated_at',
        table_name='auth_login_attempts',
    )
