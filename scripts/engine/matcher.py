from __future__ import annotations

from dataclasses import dataclass

from .state import InMemoryState, Order, Quote, Tick, Trade


SELL_FEE_RATE = 0.0002
SELL_TAX_RATE = 0.0005
BUY_FEE_RATE = 0.0002


@dataclass
class MatchResult:
    trades: list[Trade]


def _is_active(order: Order) -> bool:
    return order.status in {"active", "partially_filled"} and order.remaining_qty > 0


def _mark_status(order: Order):
    if order.remaining_qty == 0:
        order.status = "filled"
    elif order.remaining_qty < order.quantity:
        order.status = "partially_filled"


def run_batch_match(state: InMemoryState, tick: Tick, quote: Quote) -> MatchResult:
    if not tick.is_matching_point:
        return MatchResult(trades=[])

    buys = [
        order
        for order in state.orders.values()
        if order.ts_code == quote.ts_code and order.side == "buy" and _is_active(order)
    ]
    sells = [
        order
        for order in state.orders.values()
        if order.ts_code == quote.ts_code and order.side == "sell" and _is_active(order)
    ]

    buys.sort(key=lambda item: (-item.limit_price, item.created_seq, item.id))
    sells.sort(key=lambda item: (item.limit_price, item.created_seq, item.id))

    trade_price = quote.ref_price
    trades: list[Trade] = []

    buy_idx = 0
    sell_idx = 0
    while buy_idx < len(buys) and sell_idx < len(sells):
        buy = buys[buy_idx]
        sell = sells[sell_idx]

        if trade_price > buy.limit_price:
            buy_idx += 1
            continue
        if trade_price < sell.limit_price:
            sell_idx += 1
            continue

        qty = min(buy.remaining_qty, sell.remaining_qty)
        fee_buy = round(trade_price * qty * BUY_FEE_RATE, 2)
        fee_sell = round(trade_price * qty * SELL_FEE_RATE, 2)
        tax_sell = round(trade_price * qty * SELL_TAX_RATE, 2)

        trade = Trade(
            id=state.create_trade_id(),
            season_id=tick.season_id,
            tick_id=tick.id,
            ts_code=quote.ts_code,
            trade_price=trade_price,
            quantity=qty,
            buy_order_id=buy.id,
            sell_order_id=sell.id,
            fee_buy=fee_buy,
            fee_sell=fee_sell,
            tax_sell=tax_sell,
            matched_at=state.now(),
        )
        trades.append(trade)

        buy.remaining_qty -= qty
        sell.remaining_qty -= qty

        now = state.now()
        buy.updated_at = now
        sell.updated_at = now
        _mark_status(buy)
        _mark_status(sell)

        if buy.remaining_qty == 0:
            buy_idx += 1
        if sell.remaining_qty == 0:
            sell_idx += 1

    return MatchResult(trades=trades)
