class EvaluationLeaseLostError(RuntimeError):
    """Raised when this worker no longer owns the evaluation job lease."""
