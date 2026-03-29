from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import ledger, matcher, rules
from .state import CashLedgerEntry, InMemoryState, Order, Quote, Tick

if TYPE_CHECKING:
    from .pg_state import PgState


@dataclass
class PlaceOrderRequest:
    season_id: int
    user_id: str
    account_id: int
    client_order_id: str
    ts_code: str
    side: str
    limit_price: float
    quantity: int


class EngineOrchestrator:
    def __init__(
        self,
        state: "InMemoryState | PgState",
        season_id: int | None = None,
    ):
        self.state = state
        if season_id is not None and hasattr(state, "load_season_state"):
            state.load_season_state(season_id)

    def place_order(self, tick: Tick, quote: Quote, req: PlaceOrderRequest) -> Order:
        with self.state.transaction():
            account = self.state.accounts[req.account_id]
            position = self.state.get_position(req.season_id, req.user_id, req.ts_code)
            now = self.state.now()

            rule_result = rules.validate_order(
                tick=tick,
                quote=quote,
                account=account,
                position=position,
                side=req.side,
                limit_price=req.limit_price,
                quantity=req.quantity,
            )

            order = Order(
                id=self.state.create_order_id(),
                season_id=req.season_id,
                user_id=req.user_id,
                account_id=req.account_id,
                client_order_id=req.client_order_id,
                ts_code=req.ts_code,
                side=req.side,
                limit_price=req.limit_price,
                quantity=req.quantity,
                remaining_qty=req.quantity,
                status="active" if rule_result.ok else "rejected",
                phase_submitted=tick.phase,
                submitted_tick_id=tick.id,
                reject_code=rule_result.reject_code,
                reject_reason=rule_result.reject_reason,
                created_seq=self.state.create_sequence(),
                created_at=now,
                updated_at=now,
            )
            self.state.orders[order.id] = order

            if not rule_result.ok:
                return order

            if order.side == "buy":
                reserve = rules.estimate_buy_cost(order.limit_price, order.quantity)
                account.available_cash = round(account.available_cash - reserve, 2)
                account.frozen_cash = round(account.frozen_cash + reserve, 2)
                self.state.cash_ledger.append(
                    CashLedgerEntry(
                        id=self.state.create_ledger_id(),
                        season_id=order.season_id,
                        user_id=order.user_id,
                        account_id=account.id,
                        entry_type="freeze",
                        amount=-reserve,
                        balance_after=account.available_cash,
                        ref_order_id=order.id,
                        ref_trade_id=None,
                        note="freeze cash for buy order",
                    )
                )

            return order

    def process_tick(self, tick: Tick, quotes_by_code: dict[str, Quote]) -> list[int]:
        processed_trade_ids: list[int] = []

        try:
            with self.state.transaction():
                if not tick.is_matching_point:
                    return processed_trade_ids

                for ts_code, quote in quotes_by_code.items():
                    if quote.ts_code != ts_code:
                        raise ValueError(f"quote key mismatch for {ts_code}")

                    result = matcher.run_batch_match(state=self.state, tick=tick, quote=quote)
                    for trade in result.trades:
                        ledger.apply_trade(state=self.state, tick=tick, trade=trade)
                        processed_trade_ids.append(trade.id)

            return processed_trade_ids
        except Exception as exc:
            message = f"process_tick failed for tick_id={tick.id}"
            self.state.append_error(f"{message}: {exc!r}")
            raise RuntimeError(message) from exc
