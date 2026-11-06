"""Add nullable ownership to top-level business records.

Existing records remain unowned until an explicitly approved adoption operation.

Revision ID: ce4d8129ab31
Revises: b762c47d8e10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ce4d8129ab31'
down_revision: Union[str, None] = 'b762c47d8e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_references_consistent(connection) -> None:
    checks = (
        (
            'dataset_versions.dataset_id',
            'SELECT dv.id FROM dataset_versions dv '
            'LEFT JOIN datasets d ON d.id = dv.dataset_id WHERE d.id IS NULL LIMIT 1',
        ),
        (
            'test_cases.dataset_id',
            'SELECT tc.id FROM test_cases tc '
            'LEFT JOIN datasets d ON d.id = tc.dataset_id WHERE d.id IS NULL LIMIT 1',
        ),
        (
            'test_cases.dataset_version_id',
            'SELECT tc.id FROM test_cases tc LEFT JOIN dataset_versions dv '
            'ON dv.id = tc.dataset_version_id AND dv.dataset_id = tc.dataset_id '
            'WHERE tc.dataset_version_id IS NOT NULL AND dv.id IS NULL LIMIT 1',
        ),
        (
            'evaluation_runs.dataset_id',
            'SELECT r.id FROM evaluation_runs r '
            'LEFT JOIN datasets d ON d.id = r.dataset_id WHERE d.id IS NULL LIMIT 1',
        ),
        (
            'evaluation_runs.rubric_id',
            'SELECT r.id FROM evaluation_runs r '
            'LEFT JOIN rubrics rb ON rb.id = r.rubric_id '
            'WHERE r.rubric_id IS NOT NULL AND rb.id IS NULL LIMIT 1',
        ),
        (
            'rubric_criteria.rubric_id',
            'SELECT rc.id FROM rubric_criteria rc '
            'LEFT JOIN rubrics rb ON rb.id = rc.rubric_id WHERE rb.id IS NULL LIMIT 1',
        ),
        (
            'evaluation_results.run_id',
            'SELECT er.id FROM evaluation_results er '
            'LEFT JOIN evaluation_runs r ON r.id = er.run_id WHERE r.id IS NULL LIMIT 1',
        ),
        (
            'human_reviews.result_id',
            'SELECT hr.id FROM human_reviews hr '
            'LEFT JOIN evaluation_results er ON er.id = hr.result_id WHERE er.id IS NULL LIMIT 1',
        ),
        (
            'auth_refresh_tokens.user_id',
            'SELECT rt.id FROM auth_refresh_tokens rt '
            'LEFT JOIN users u ON u.id = rt.user_id WHERE u.id IS NULL LIMIT 1',
        ),
    )
    inconsistent = [
        reference
        for reference, query in checks
        if connection.exec_driver_sql(query).first() is not None
    ]
    if inconsistent:
        raise RuntimeError(
            'Ownership migration aborted before schema changes because legacy references '
            'are orphaned or inconsistent: ' + ', '.join(inconsistent)
        )


def upgrade() -> None:
    connection = op.get_bind()
    _assert_references_consistent(connection)

    for table_name in ('datasets', 'rubrics', 'evaluation_runs'):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column('user_id', sa.String(length=32), nullable=True))
            batch.create_foreign_key(
                f'fk_{table_name}_user_id_users',
                'users',
                ['user_id'],
                ['id'],
                ondelete='RESTRICT',
            )
            batch.create_index(
                f'ix_{table_name}_user_id',
                ['user_id'],
                unique=False,
            )


def downgrade() -> None:
    connection = op.get_bind()
    assigned = [
        table_name
        for table_name in ('datasets', 'rubrics', 'evaluation_runs')
        if connection.exec_driver_sql(
            f'SELECT id FROM {table_name} WHERE user_id IS NOT NULL LIMIT 1'
        ).first() is not None
    ]
    if assigned:
        raise RuntimeError(
            'Ownership migration cannot be downgraded while ownership assignments exist: '
            + ', '.join(assigned)
        )

    for table_name in ('evaluation_runs', 'rubrics', 'datasets'):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_index(f'ix_{table_name}_user_id')
            batch.drop_constraint(
                f'fk_{table_name}_user_id_users',
                type_='foreignkey',
            )
            batch.drop_column('user_id')
