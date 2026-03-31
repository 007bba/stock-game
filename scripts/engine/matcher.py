from __future__ import annotations

from dataclasses import dataclass
import math

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


def _is_call_auction_tick(tick: Tick) -> bool:
    return tick.matching_mode in {"open_call_auction", "close_call_auction"}


def _executable_qty(orders: list[Order], *, side: str, price: float) -> int:
    if side == "buy":
        return sum(order.remaining_qty for order in orders if order.limit_price >= price)
    return sum(order.remaining_qty for order in orders if order.limit_price <= price)


def _resolve_call_auction_price(buys: list[Order], sells: list[Order], quote: Quote) -> float | None:
    if not buys or not sells:
        return None

    candidate_prices = {quote.ref_price}
    candidate_prices.update(order.limit_price for order in buys)
    candidate_prices.update(order.limit_price for order in sells)

    best_price: float | None = None
    best_volume = -1
    best_abs_imbalance = math.inf
    best_ref_distance = math.inf

    for price in sorted(candidate_prices):
        executable_buy = _executable_qty(buys, side="buy", price=price)
        executable_sell = _executable_qty(sells, side="sell", price=price)
        executable_volume = min(executable_buy, executable_sell)
        abs_imbalance = abs(executable_buy - executable_sell)
        ref_distance = abs(price - quote.ref_price)

        if executable_volume > best_volume:
            best_price = price
            best_volume = executable_volume
            best_abs_imbalance = abs_imbalance
            best_ref_distance = ref_distance
            continue

        if executable_volume < best_volume:
            continue

        if abs_imbalance < best_abs_imbalance:
            best_price = price
            best_abs_imbalance = abs_imbalance
            best_ref_distance = ref_distance
            continue

        if abs_imbalance > best_abs_imbalance:
            continue

        if ref_distance < best_ref_distance:
            best_price = price
            best_ref_distance = ref_distance
            continue

        if ref_distance == best_ref_distance and (best_price is None or price > best_price):
            best_price = price

    if best_volume <= 0:
        return None

    return best_price


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
    if _is_call_auction_tick(tick):
        resolved = _resolve_call_auction_price(buys, sells, quote)
        if resolved is None:
            return MatchResult(trades=[])
        trade_price = resolved
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
