from __future__ import annotations

import os
import re
from typing import Iterable

from pydantic import BaseModel


class EvaluationMetricResult(BaseModel):
    accuracy: float
    passRate: float
    failureRate: float
    averageLatency: float
    averageScore: float
    tokenUsage: int = 0
    estimatedCost: float | None = None


def normalize(value: str) -> str:
    """Case-fold text and collapse Unicode whitespace; punctuation is preserved."""
    return ' '.join(value.casefold().split())


def exact_match(actual: str, expected: str) -> bool:
    return normalize(actual) == normalize(expected)


def keyword_match(actual: str, expected_keywords: list[str]) -> dict:
    keywords = [normalize(keyword) for keyword in expected_keywords if normalize(keyword)]
    if not keywords:
        raise ValueError('Keyword Match requires at least one non-empty expected keyword.')
    response = normalize(actual)
    matches = [
        {
            'keyword': keyword,
            'matched': re.search(rf'(?<!\w){re.escape(keyword)}(?!\w)', response, re.UNICODE) is not None,
        }
        for keyword in keywords
    ]
    passed = all(item['matched'] for item in matches)
    return {'passed': passed, 'score': sum(item['matched'] for item in matches) / len(matches), 'breakdown': matches}


def rubric_score(actual: str, rubric: list[dict]) -> dict:
    if not rubric:
        raise ValueError('Rubric Evaluation requires at least one criterion.')
    for item in rubric:
        if not isinstance(item.get('weight'), (int, float)) or not 0 <= item['weight'] <= 100:
            raise ValueError('Rubric criterion weights must be between 0 and 100.')
        if not item.get('name') or not isinstance(item.get('expectedKeywords'), list) or not item['expectedKeywords']:
            raise ValueError('Each rubric criterion must have a name and at least one expected keyword.')
        if not re.fullmatch(r'\s*0\s*[-–]\s*(\d+(?:\.\d+)?)\s*', str(item.get('scale', ''))):
            raise ValueError('Rubric criterion scales must use the format 0–N.')
        if float(re.search(r'(\d+(?:\.\d+)?)\s*$', str(item['scale'])).group(1)) <= 0:
            raise ValueError('Rubric criterion scales must have a maximum greater than zero.')
    total_weight = sum(float(item['weight']) for item in rubric)
    if total_weight <= 0:
        raise ValueError('Rubric weights must total greater than zero.')
    normalized_actual = normalize(actual)
    breakdown = []
    for criterion in rubric:
        max_score = float(re.search(r'(\d+(?:\.\d+)?)\s*$', str(criterion['scale'])).group(1))
        keywords = [normalize(keyword) for keyword in criterion['expectedKeywords'] if normalize(keyword)]
        if not keywords:
            raise ValueError(f'Rubric criterion "{criterion["name"]}" has no non-empty expected keywords.')
        matches = [
            {
                'keyword': keyword,
                'matched': re.search(rf'(?<!\w){re.escape(keyword)}(?!\w)', normalized_actual, re.UNICODE) is not None,
            }
            for keyword in keywords
        ]
        score = max_score * sum(item['matched'] for item in matches) / len(matches)
        breakdown.append({
            'name': criterion['name'],
            'weight': float(criterion['weight']),
            'score': round(score, 4),
            'maxScore': max_score,
            'weightedScore': round(score * float(criterion['weight']) / total_weight, 4),
            'expectedKeywords': matches,
        })
    return {
        'score': round(sum(item['weightedScore'] for item in breakdown), 4),
        'maxScore': round(sum(item['maxScore'] * item['weight'] / total_weight for item in breakdown), 4),
        'breakdown': breakdown,
    }


def estimate_provider_cost(
    provider: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    """Estimate API spend from configured per-million token rates.

    Local Ollama inference has no provider API charge; electricity/hosting costs
    are intentionally outside this estimate. Groq rates are deployment config
    so pricing changes do not require a code release.
    """
    normalized_provider = provider.strip().lower()
    if normalized_provider == 'ollama':
        return 0.0
    if normalized_provider != 'groq' or prompt_tokens is None or completion_tokens is None:
        return None
    try:
        input_rate = float(os.getenv('GROQ_INPUT_COST_PER_MILLION', ''))
        output_rate = float(os.getenv('GROQ_OUTPUT_COST_PER_MILLION', ''))
    except ValueError:
        return None
    if input_rate < 0 or output_rate < 0:
        return None
    cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
    return round(cost, 10)


def calculate_metrics(results: Iterable[dict]) -> EvaluationMetricResult:
    rows = list(results)
    if not rows:
        return EvaluationMetricResult(
            accuracy=0.0,
            passRate=0.0,
            failureRate=0.0,
            averageLatency=0.0,
            averageScore=0.0,
            tokenUsage=0,
            estimatedCost=None,
        )

    scored_rows = [row for row in rows if row.get('status', 'Completed') == 'Completed']
    passed = sum(1 for row in scored_rows if row.get('passed'))
    failed = sum(1 for row in scored_rows if not row.get('passed'))
    total = len(scored_rows)
    latencies = [float(row.get('latency_ms') or 0) for row in rows if row.get('latency_ms') is not None]
    average_latency = sum(latencies) / len(latencies) if latencies else 0.0
    average_score = sum(float(row.get('score') or 0.0) for row in scored_rows) / total if total else 0.0
    accuracy = (passed / total) * 100 if total else 0.0
    pass_rate = (passed / total) * 100 if total else 0.0
    failure_rate = (failed / total) * 100 if total else 0.0
    token_usage = sum(int(row.get('token_usage') or 0) for row in scored_rows)
    row_costs = [row.get('estimated_cost') for row in rows]
    estimated_cost = round(sum(float(cost) for cost in row_costs), 10) if row_costs and all(cost is not None for cost in row_costs) else None
    return EvaluationMetricResult(
        accuracy=round(accuracy, 2),
        passRate=round(pass_rate, 2),
        failureRate=round(failure_rate, 2),
        averageLatency=round(average_latency, 2),
        averageScore=round(average_score, 2),
        tokenUsage=token_usage,
        estimatedCost=estimated_cost,
    )


def evaluate_exact_match(actual: str, expected: str) -> dict:
    passed = exact_match(actual, expected)
    return {'passed': passed, 'score': 1.0 if passed else 0.0, 'breakdown': []}


def evaluate_keyword_match(actual: str, expected_keywords: list[str]) -> dict:
    return keyword_match(actual, expected_keywords)


def evaluate_rubric(actual: str, rubric: list[dict]) -> dict:
    result = rubric_score(actual, rubric)
    passed = result['score'] >= result['maxScore'] * 0.6
    return {**result, 'passed': passed}
