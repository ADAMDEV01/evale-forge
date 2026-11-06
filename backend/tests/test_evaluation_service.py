import pytest

from backend.app.services.evaluation_service import (
    calculate_metrics,
    evaluate_exact_match,
    evaluate_keyword_match,
    evaluate_rubric,
    estimate_provider_cost,
)


def test_exact_match_normalizes_case_and_whitespace_but_preserves_punctuation():
    assert evaluate_exact_match('  Hello\n WORLD ', 'hello world')['passed'] is True
    assert evaluate_exact_match('Hello, world', 'Hello world')['passed'] is False
    assert evaluate_exact_match('different response', 'the prompt')['passed'] is False


def test_keyword_match_requires_every_keyword_and_matches_whole_phrases():
    assert evaluate_keyword_match('Business plan includes audit logs', ['business plan', 'audit logs'])['passed']
    assert not evaluate_keyword_match('The starter plan has logs', ['starter', 'audit logs'])['passed']
    assert not evaluate_keyword_match('airplane', ['plane'])['passed']


def test_keyword_match_rejects_empty_criteria():
    with pytest.raises(ValueError, match='at least one'):
        evaluate_keyword_match('any response', [' ', ''])


def test_rubric_score_uses_weighted_criterion_breakdown_and_zero_weight():
    outcome = evaluate_rubric('correct and clear', [
        {'name': 'Accuracy', 'weight': 75, 'scale': '0–5', 'expectedKeywords': ['correct']},
        {'name': 'Clarity', 'weight': 25, 'scale': '0–5', 'expectedKeywords': ['clear', 'concise']},
        {'name': 'Optional', 'weight': 0, 'scale': '0–5', 'expectedKeywords': ['optional']},
    ])
    assert outcome['score'] == 4.375
    assert outcome['passed'] is True
    assert outcome['breakdown'][0]['weightedScore'] == 3.75
    assert outcome['breakdown'][2]['weightedScore'] == 0
    assert outcome['breakdown'][2]['weight'] == 0


@pytest.mark.parametrize('criteria', [
    [],
    [{'name': 'Accuracy', 'weight': 0, 'scale': '0–5', 'expectedKeywords': ['correct']}],
    [{'name': 'Accuracy', 'weight': 101, 'scale': '0–5', 'expectedKeywords': ['correct']}],
    [{'name': 'Accuracy', 'weight': 100, 'scale': '0–5', 'expectedKeywords': []}],
    [{'name': 'Accuracy', 'weight': 100, 'scale': '0-0', 'expectedKeywords': ['correct']}],
])
def test_rubric_rejects_invalid_scoring_configuration(criteria):
    with pytest.raises(ValueError):
        evaluate_rubric('correct', criteria)


def test_metrics_exclude_engine_errors_and_leave_cost_unavailable():
    metrics = calculate_metrics([
        {'status': 'Completed', 'passed': True, 'score': 1, 'latency_ms': 100, 'token_usage': 8},
        {'status': 'Error', 'passed': False, 'score': 0, 'latency_ms': 10, 'token_usage': None},
    ])
    assert metrics.accuracy == 100
    assert metrics.averageLatency == 55
    assert metrics.tokenUsage == 8
    assert metrics.estimatedCost is None


def test_provider_cost_estimation_uses_configured_groq_token_rates(monkeypatch):
    monkeypatch.setenv('GROQ_INPUT_COST_PER_MILLION', '0.10')
    monkeypatch.setenv('GROQ_OUTPUT_COST_PER_MILLION', '0.40')
    assert estimate_provider_cost('groq', 1000, 500) == 0.0003
    assert estimate_provider_cost('ollama', 1000, 500) == 0.0
    assert estimate_provider_cost('groq', None, 500) is None


def test_metrics_sum_known_per_case_costs():
    metrics = calculate_metrics([
        {'status': 'Completed', 'passed': True, 'score': 1, 'latency_ms': 10, 'token_usage': 10, 'estimated_cost': 0.0001},
        {'status': 'Completed', 'passed': False, 'score': 0, 'latency_ms': 20, 'token_usage': 20, 'estimated_cost': 0.0002},
    ])
    assert metrics.estimatedCost == 0.0003


def test_metrics_treat_null_completed_values_as_zero_or_exclude_null_latency():
    metrics = calculate_metrics([
        {'status': 'Completed', 'passed': True, 'score': None, 'latency_ms': None, 'token_usage': None},
        {'status': 'Completed', 'passed': False, 'score': 0.5, 'latency_ms': 80, 'token_usage': None},
    ])

    assert metrics.accuracy == 50
    assert metrics.passRate == 50
    assert metrics.averageScore == 0.25
    assert metrics.averageLatency == 80
    assert metrics.tokenUsage == 0
    assert metrics.estimatedCost is None
