"""Stock Game matching engine package (P4 MVP)."""

from .ledger import apply_trade
from .orchestrator import EngineOrchestrator, PlaceOrderRequest
from .state import (
    Account,
    CashLedgerEntry,
    InMemoryState,
    Order,
    Position,
    Quote,
    Tick,
    Trade,
)

try:
    from .pg_state import PgState
except Exception:  # pragma: no cover - optional DB dependency
    PgState = None

__all__ = [
    "Account",
    "apply_trade",
    "CashLedgerEntry",
    "EngineOrchestrator",
    "InMemoryState",
    "Order",
    "PgState",
    "PlaceOrderRequest",
    "Position",
    "Quote",
    "Tick",
    "Trade",
]
