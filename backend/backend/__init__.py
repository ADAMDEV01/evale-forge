"""Compatibility package for Vercel's backend service root.

The service root is the backend/ directory, while the application keeps its
existing backend.app.* import paths. Point this package at that service root
so those imports continue to resolve without rewriting application modules.
"""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent)]
