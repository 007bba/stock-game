from __future__ import annotations

from dataclasses import dataclass

from .state import Account, Position, Quote, Tick


LOT_SIZE = 100
BUY_FEE_RATE = 0.0002


@dataclass
class RuleResult:
    ok: bool
    reject_code: str | None = None
    reject_reason: str | None = None


def estimate_buy_cost(limit_price: float, quantity: int) -> float:
    return round(limit_price * quantity * (1 + BUY_FEE_RATE), 2)


def validate_order(
    tick: Tick,
    quote: Quote,
    account: Account,
    position: Position,
    side: str,
    limit_price: float,
    quantity: int,
) -> RuleResult:
    if not tick.is_tradable:
        return RuleResult(False, "SEASON_NOT_TRADING", "tick is not tradable")

    if quantity <= 0 or quantity % LOT_SIZE != 0:
        return RuleResult(False, "LOT_SIZE_INVALID", "quantity must be in lots of 100")

    if quote.is_halted:
        return RuleResult(False, "STOCK_HALTED", "stock is halted")

    if limit_price < quote.lower_limit_price or limit_price > quote.upper_limit_price:
        return RuleResult(False, "LIMIT_PRICE_OUT_OF_BAND", "limit price out of daily band")

    if side == "buy":
        need_cash = estimate_buy_cost(limit_price=limit_price, quantity=quantity)
        if account.available_cash < need_cash:
            return RuleResult(False, "INSUFFICIENT_CASH", "insufficient available cash")
        return RuleResult(True)

    if side != "sell":
        return RuleResult(False, "AUCTION_WINDOW_CLOSED", "invalid order side")

    if position.qty_sellable < quantity:
        if position.last_settled_game_day == tick.game_day_no and position.qty_total >= quantity:
            return RuleResult(False, "SELL_T1_BLOCKED", "same-day buy cannot be sold")
        return RuleResult(False, "INSUFFICIENT_SELLABLE_QTY", "insufficient sellable quantity")

    return RuleResult(True)
