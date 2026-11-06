from sqlalchemy import text

from backend.app.db.schema_lifecycle import check_schema_compatibility


def _replace_human_reviews(
    engine,
    constraints: str,
    note_nullable: bool = False,
    result_type: str = 'VARCHAR(64)',
) -> None:
    note_definition = 'TEXT' if note_nullable else 'TEXT NOT NULL'
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE human_reviews'))
        connection.execute(text(f'''
            CREATE TABLE human_reviews (
                id VARCHAR(64) NOT NULL,
                result_id {result_type} NOT NULL,
                reviewer VARCHAR(200) NOT NULL,
                verdict VARCHAR(32) NOT NULL,
                note {note_definition},
                created_at DATETIME NOT NULL
                {constraints}
            )
        '''))


def _replace_test_cases_without_unique_constraint(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE test_cases'))
        connection.execute(text('''
            CREATE TABLE test_cases (
                id VARCHAR(64) NOT NULL PRIMARY KEY,
                dataset_id VARCHAR(64) NOT NULL,
                dataset_version_id VARCHAR(64),
                title VARCHAR(200) NOT NULL,
                input TEXT NOT NULL,
                expected TEXT NOT NULL,
                expected_keywords TEXT NOT NULL,
                criteria TEXT NOT NULL,
                category VARCHAR(100) NOT NULL,
                tags TEXT NOT NULL,
                importance VARCHAR(32) NOT NULL,
                expected_behavior TEXT NOT NULL,
                FOREIGN KEY(dataset_id) REFERENCES datasets(id),
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id)
            )
        '''))


def _report(engine):
    with engine.connect() as connection:
        return check_schema_compatibility(connection)


def test_missing_table_is_reported(migrated_test_engine):
    with migrated_test_engine.begin() as connection:
        connection.execute(text('DROP TABLE human_reviews'))

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'missing table human_reviews' in report.differences


def test_missing_column_is_reported(migrated_test_engine):
    with migrated_test_engine.begin() as connection:
        connection.execute(text('ALTER TABLE human_reviews DROP COLUMN note'))

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'human_reviews: missing column note' in report.differences


def test_nullability_mismatch_is_reported(migrated_test_engine):
    _replace_human_reviews(
        migrated_test_engine,
        ', PRIMARY KEY(id), FOREIGN KEY(result_id) REFERENCES evaluation_results(id)',
        note_nullable=True,
    )

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert any('human_reviews.note: nullability mismatch' in item for item in report.differences)


def test_column_type_mismatch_is_reported(migrated_test_engine):
    _replace_human_reviews(
        migrated_test_engine,
        ', PRIMARY KEY(id), FOREIGN KEY(result_id) REFERENCES evaluation_results(id)',
        result_type='TEXT',
    )

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert any('human_reviews.result_id: type mismatch' in item for item in report.differences)


def test_primary_key_mismatch_is_reported(migrated_test_engine):
    _replace_human_reviews(migrated_test_engine, '')

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'human_reviews: primary-key mismatch' in report.differences


def test_foreign_key_mismatch_is_reported(migrated_test_engine):
    _replace_human_reviews(migrated_test_engine, ', PRIMARY KEY(id)')

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'human_reviews: foreign-key mismatch' in report.differences


def test_unique_constraint_mismatch_is_reported(migrated_test_engine):
    _replace_test_cases_without_unique_constraint(migrated_test_engine)

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'test_cases: unique-constraint mismatch' in report.differences


def test_unexpected_index_is_reported(migrated_test_engine):
    with migrated_test_engine.begin() as connection:
        connection.execute(text('CREATE INDEX unexpected_dataset_name ON datasets(name)'))

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'datasets: index mismatch' in report.differences


def test_unexpected_table_is_reported(migrated_test_engine):
    with migrated_test_engine.begin() as connection:
        connection.execute(text('CREATE TABLE legacy_extra (id INTEGER PRIMARY KEY)'))

    report = _report(migrated_test_engine)

    assert report.status == 'incompatible'
    assert 'unexpected table legacy_extra' in report.differences
