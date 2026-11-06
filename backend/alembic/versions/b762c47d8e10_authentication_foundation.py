"""Add local authentication users and refresh-token sessions.

Revision ID: b762c47d8e10
Revises: 9f75ce1076ac
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b762c47d8e10'
down_revision: Union[str, None] = '9f75ce1076ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_users_email'),
    )
    op.create_table(
        'auth_refresh_tokens',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('family_id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('replaced_by_id', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_auth_refresh_tokens_token_hash'),
    )
    op.create_index(
        'ix_auth_refresh_tokens_family_id',
        'auth_refresh_tokens',
        ['family_id'],
        unique=False,
    )
    op.create_index(
        'ix_auth_refresh_tokens_user_id',
        'auth_refresh_tokens',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_auth_refresh_tokens_user_id', table_name='auth_refresh_tokens')
    op.drop_index('ix_auth_refresh_tokens_family_id', table_name='auth_refresh_tokens')
    op.drop_table('auth_refresh_tokens')
    op.drop_table('users')
