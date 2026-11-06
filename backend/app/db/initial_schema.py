from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

INITIAL_REVISION = '9f75ce1076ac'
INITIAL_SCHEMA_METADATA = MetaData()

Table(
    'datasets',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('name', String(200), nullable=False),
    Column('description', Text, nullable=False),
    Column('version', String(32), nullable=False),
    Column('cases', Integer, nullable=False),
    Column('created_at', DateTime, nullable=False),
    Column('modified_at', DateTime, nullable=False),
    Column('color', String(32), nullable=True),
)

Table(
    'rubrics',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('name', String(200), nullable=False),
    Column('description', Text, nullable=False),
    Column('active', Boolean, nullable=False),
    Column('created_at', DateTime, nullable=False),
    Column('updated_at', DateTime, nullable=False),
)

Table(
    'dataset_versions',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('dataset_id', String(64), ForeignKey('datasets.id'), nullable=False),
    Column('version', String(32), nullable=False),
    Column('created_at', DateTime, nullable=False),
    Column('case_count', Integer, nullable=False),
)

Table(
    'evaluation_runs',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('dataset_id', String(64), ForeignKey('datasets.id'), nullable=False),
    Column('dataset_version', String(32), nullable=False),
    Column('model', String(200), nullable=False),
    Column('provider', String(32), nullable=False),
    Column('dataset_name', String(200), nullable=False),
    Column('evaluation_method', String(32), nullable=False),
    Column('rubric_id', String(64), nullable=True),
    Column('rubric_snapshot_json', Text, nullable=False),
    Column('token_usage', Integer, nullable=True),
    Column('estimated_cost', Float, nullable=True),
    Column('error_type', String(64), nullable=True),
    Column('error_message', Text, nullable=True),
    Column('status', String(32), nullable=False),
    Column('accuracy', Float, nullable=False),
    Column('pass_rate', Float, nullable=False),
    Column('latency', Integer, nullable=False),
    Column('score', Float, nullable=False),
    Column('passed', Integer, nullable=False),
    Column('failed', Integer, nullable=False),
    Column('total', Integer, nullable=False),
    Column('date', String(80), nullable=False),
    Column('config_json', Text, nullable=False),
    Column('created_at', DateTime, nullable=False),
)

Table(
    'rubric_criteria',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('rubric_id', String(64), ForeignKey('rubrics.id'), nullable=False),
    Column('name', String(200), nullable=False),
    Column('description', Text, nullable=False),
    Column('weight', Integer, nullable=False),
    Column('scale', String(32), nullable=False),
    Column('expected_keywords', Text, nullable=False),
)

Table(
    'evaluation_results',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('run_id', String(64), ForeignKey('evaluation_runs.id'), nullable=False),
    Column('test_case_id', String(64), nullable=False),
    Column('sequence', Integer, nullable=False),
    Column('test_case_title', String(200), nullable=False),
    Column('category', String(100), nullable=False),
    Column('input_snapshot', Text, nullable=False),
    Column('expected', Text, nullable=False),
    Column('evaluation_method', String(32), nullable=False),
    Column('status', String(32), nullable=False),
    Column('score', Float, nullable=False),
    Column('latency_ms', Integer, nullable=False),
    Column('actual', Text, nullable=False),
    Column('token_usage', Integer, nullable=True),
    Column('criteria_breakdown_json', Text, nullable=False),
    Column('error_type', String(64), nullable=True),
    Column('passed', Boolean, nullable=False),
    Column('error_message', Text, nullable=True),
)

Table(
    'test_cases',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('dataset_id', String(64), ForeignKey('datasets.id'), nullable=False),
    Column('dataset_version_id', String(64), ForeignKey('dataset_versions.id'), nullable=True),
    Column('title', String(200), nullable=False),
    Column('input', Text, nullable=False),
    Column('expected', Text, nullable=False),
    Column('expected_keywords', Text, nullable=False),
    Column('criteria', Text, nullable=False),
    Column('category', String(100), nullable=False),
    Column('tags', Text, nullable=False),
    Column('importance', String(32), nullable=False),
    Column('expected_behavior', Text, nullable=False),
    UniqueConstraint('dataset_id', 'title', name='uq_test_case_title_dataset'),
)

Table(
    'human_reviews',
    INITIAL_SCHEMA_METADATA,
    Column('id', String(64), primary_key=True, nullable=False),
    Column('result_id', String(64), ForeignKey('evaluation_results.id'), nullable=False),
    Column('reviewer', String(200), nullable=False),
    Column('verdict', String(32), nullable=False),
    Column('note', Text, nullable=False),
    Column('created_at', DateTime, nullable=False),
)
