"""Vercel entrypoint for the EvalForge FastAPI application."""
import sys
from pathlib import Path

# The Vercel backend service root is /backend, while the application uses
# absolute imports beginning with "backend.app". Add the repository root so
# those imports resolve in the deployed function as they do locally.
REPOSITORY_ROOT = str(Path(__file__).resolve().parent.parent)
if REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT)

from backend.app.main import app

__all__ = ["app"]
