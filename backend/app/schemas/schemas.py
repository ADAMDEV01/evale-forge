from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class DatasetSchema(BaseModel):
    id: str
    name: str
    description: str = ''
    version: str = 'v1.0'
    cases: int = 0
    createdAt: str = ''
    modifiedAt: str = ''
    color: str = 'violet'


class TestCaseSchema(BaseModel):
    id: str
    datasetId: str
    title: str
    input: str
    expected: str
    expectedKeywords: list[str] = Field(default_factory=list)
    criteria: str = ''
    category: str = 'General'
    tags: list[str] = Field(default_factory=list)
    importance: Literal['Critical', 'High', 'Medium', 'Low'] = 'Medium'
    expectedBehavior: str = ''


class RubricCriterionSchema(BaseModel):
    id: str | None = None
    name: str
    description: str = ''
    weight: int = Field(default=0, ge=0, le=100)
    scale: str = '0–5'
    expectedKeywords: list[str] = Field(default_factory=list)


class RubricSchema(BaseModel):
    id: str
    name: str
    description: str = ''
    active: bool = True
    criteria: list[RubricCriterionSchema] = Field(default_factory=list)


class EvaluationRunFields(BaseModel):
    id: str
    datasetVersion: str
    model: str
    provider: str = 'mock'
    evaluationMethod: str = 'exact_match'
    tokenUsage: int | None = None
    estimatedCost: float | None = None
    errorType: str | None = None
    errorMessage: str | None = None
    accuracy: float = 0.0
    passRate: float = 0.0
    latency: int = 0
    status: Literal['Completed', 'Running', 'Failed', 'Pending', 'Cancelled'] = 'Pending'
    date: str = ''
    passed: int = 0
    failed: int = 0
    total: int = 0
    config: Optional[dict] = None


class EvaluationRunSchema(EvaluationRunFields):
    dataset: str
    persisted_results_count: int


class EvaluationRunCreateSchema(EvaluationRunFields):
    dataset_id: str = Field(min_length=1)

    @field_validator('dataset_id')
    @classmethod
    def dataset_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('dataset_id must not be blank')
        return value


class FailureSchema(BaseModel):
    id: str
    testCase: str
    dataset: str
    model: str
    run_status: str | None = None
    run_provider: str | None = None
    failure_type: Literal['evaluation_failure', 'evaluation_error'] | None = None
    category: str
    score: float = 0.0
    timestamp: str = ''
    input: str = ''
    expected: str = ''
    actual: str = ''
    explanation: str = ''
    reviewed: bool = False
    note: Optional[str] = None
    humanJudgment: Optional[Literal['pass', 'fail']] = None


class EvaluationRequest(BaseModel):
    datasetId: str
    provider: Literal['ollama', 'groq'] = 'ollama'
    model: str = ''
    models: list[str] = Field(default_factory=list)
    evaluationMethod: Literal['exact_match', 'keyword_match', 'rubric'] = 'exact_match'
    rubric: str = 'default'
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class MetricResult(BaseModel):
    accuracy: float
    passRate: float
    failureRate: float
    averageLatency: float
    averageScore: float
    tokenUsage: int = 0
    estimatedCost: float | None = None


class EvaluationResultSchema(BaseModel):
    id: str
    testCaseId: str
    testCaseTitle: str
    category: str
    status: str
    score: float
    latencyMs: int
    input: str
    expected: str
    actual: str
    passed: bool
    evaluationMethod: str
    tokenUsage: int | None = None
    criteriaBreakdown: list[dict] = Field(default_factory=list)
    errorType: str | None = None
    errorMessage: str | None = None


class HealthResponse(BaseModel):
    status: str = 'ok'
