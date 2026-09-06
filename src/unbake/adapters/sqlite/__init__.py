"""SQLite 저장소 adapter — workflow 상태머신 + revision + evaluation run."""
from .store import InvalidTransition, Store

__all__ = ["Store", "InvalidTransition"]
