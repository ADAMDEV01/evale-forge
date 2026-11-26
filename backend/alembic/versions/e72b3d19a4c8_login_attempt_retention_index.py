"""Index login attempt buckets for bounded retention cleanup.

Revision ID: e72b3d19a4c8
Revises: 4b7e2c91a6d0
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e72b3d19a4c8'
down_revision: Union[str, None] = '4b7e2c91a6d0'
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
