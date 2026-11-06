from backend.app.services.evaluation_service import (
    evaluate_exact_match,
    evaluate_keyword_match,
    evaluate_rubric,
)


def test_fixed_evaluation_benchmark_does_not_regress():
    """Stable scoring contract used as a required CI quality gate."""
    cases = [
        evaluate_exact_match("Account verified successfully.", "Account verified successfully."),
        evaluate_exact_match("Account verified", "Account verified successfully."),
        evaluate_keyword_match(
            "The refund was approved after identity verification.",
            ["refund", "identity verification"],
        ),
        evaluate_keyword_match(
            "The refund was approved.",
            ["refund", "identity verification"],
        ),
    ]
    expected_passes = [True, False, True, False]
    actual_passes = [case["passed"] for case in cases]

    assert actual_passes == expected_passes
    baseline_accuracy = 50.0
    observed_accuracy = sum(actual_passes) / len(actual_passes) * 100
    assert observed_accuracy >= baseline_accuracy


def test_rubric_benchmark_keeps_weighted_scoring_contract():
    result = evaluate_rubric(
        "The response is accurate and clearly explains the refund process.",
        [
            {
                "name": "Accuracy",
                "weight": 70,
                "scale": "0-5",
                "expectedKeywords": ["accurate"],
            },
            {
                "name": "Clarity",
                "weight": 30,
                "scale": "0-5",
                "expectedKeywords": ["clearly explains"],
            },
        ],
    )

    assert result["passed"] is True
    assert result["score"] == 5.0
    assert result["maxScore"] == 5.0
