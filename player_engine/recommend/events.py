"""Logica pura sugli eventi di ascolto (testabile senza Flask/DB)."""

from __future__ import annotations

from .config import COMPLETE_RATIO, EVENT_TYPES, HALF_RATIO, SKIP_SECONDS


def infer_event_type(seconds: float, completion: float, provided: str | None = None) -> str:
    """Deriva l'event_type dai secondi/completion se il client non lo fornisce."""
    if provided in EVENT_TYPES:
        return provided
    if seconds < SKIP_SECONDS and completion < HALF_RATIO:
        return "skip"
    if completion >= COMPLETE_RATIO:
        return "complete"
    if completion >= HALF_RATIO:
        return "half"
    return "partial"
