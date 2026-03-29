from __future__ import annotations

from .rules import BUY_FEE_RATE
from .state import CashLedgerEntry, InMemoryState, Tick, Trade


def _append_ledger(
    state: InMemoryState,
    season_id: int,
    user_id: str,
    account_id: int,
    entry_type: str,
    amount: float,
    balance_after: float,
    ref_order_id: int | None,
    ref_trade_id: int | None,
    note: str,
):
    if amount == 0:
        return
    state.cash_ledger.append(
        CashLedgerEntry(
            id=state.create_ledger_id(),
            season_id=season_id,
            user_id=user_id,
            account_id=account_id,
            entry_type=entry_type,
            amount=round(amount, 2),
            balance_after=round(balance_after, 2),
            ref_order_id=ref_order_id,
            ref_trade_id=ref_trade_id,
            note=note,
        )
    )


def apply_trade(state: InMemoryState, tick: Tick, trade: Trade):
    buy_order = state.orders[trade.buy_order_id]
    sell_order = state.orders[trade.sell_order_id]
    buy_account = state.accounts[buy_order.account_id]
    sell_account = state.accounts[sell_order.account_id]

    notional = round(trade.trade_price * trade.quantity, 2)

    buy_reserved = round(buy_order.limit_price * trade.quantity * (1 + BUY_FEE_RATE), 2)
    buy_actual_cost = round(notional + trade.fee_buy, 2)
    buy_refund = round(buy_reserved - buy_actual_cost, 2)

    buy_account.frozen_cash = round(buy_account.frozen_cash - buy_reserved, 2)
    buy_account.available_cash = round(buy_account.available_cash + buy_refund, 2)

    _append_ledger(
        state=state,
        season_id=tick.season_id,
        user_id=buy_order.user_id,
        account_id=buy_account.id,
        entry_type="unfreeze",
        amount=buy_reserved,
        balance_after=buy_account.available_cash,
        ref_order_id=buy_order.id,
        ref_trade_id=trade.id,
        note="release frozen cash after match",
    )
    _append_ledger(
        state=state,
        season_id=tick.season_id,
        user_id=buy_order.user_id,
        account_id=buy_account.id,
        entry_type="trade_buy",
        amount=-notional,
        balance_after=buy_account.available_cash,
        ref_order_id=buy_order.id,
        ref_trade_id=trade.id,
        note="buy trade cost",
    )
    _append_ledger(
        state=state,
        season_id=tick.season_id,
        user_id=buy_order.user_id,
        account_id=buy_account.id,
        entry_type="fee",
        amount=-trade.fee_buy,
        balance_after=buy_account.available_cash,
        ref_order_id=buy_order.id,
        ref_trade_id=trade.id,
        note="buy fee",
    )

    buy_position = state.get_position(tick.season_id, buy_order.user_id, trade.ts_code)
    old_qty = buy_position.qty_total
    old_cost = buy_position.avg_cost
    new_qty = old_qty + trade.quantity
    aggregate_cost = old_qty * old_cost + notional + trade.fee_buy
    buy_position.qty_total = new_qty
    buy_position.avg_cost = round(aggregate_cost / new_qty, 4) if new_qty else 0.0
    buy_position.last_settled_game_day = tick.game_day_no

    sell_position = state.get_position(tick.season_id, sell_order.user_id, trade.ts_code)
    sell_avg_cost = sell_position.avg_cost
    sell_position.qty_total -= trade.quantity
    sell_position.qty_sellable -= trade.quantity
    if sell_position.qty_total == 0:
        sell_position.avg_cost = 0.0

    sell_income = round(notional - trade.fee_sell - trade.tax_sell, 2)
    sell_account.available_cash = round(sell_account.available_cash + sell_income, 2)
    pnl = round((trade.trade_price - sell_avg_cost) * trade.quantity - trade.fee_sell - trade.tax_sell, 2)
    sell_account.realized_pnl = round(sell_account.realized_pnl + pnl, 2)

    _append_ledger(
        state=state,
        season_id=tick.season_id,
        user_id=sell_order.user_id,
        account_id=sell_account.id,
        entry_type="trade_sell",
        amount=notional,
        balance_after=sell_account.available_cash,
        ref_order_id=sell_order.id,
        ref_trade_id=trade.id,
        note="sell trade proceed",
    )
    _append_ledger(
        state=state,
        season_id=tick.season_id,
        user_id=sell_order.user_id,
        account_id=sell_account.id,
        entry_type="fee",
        amount=-trade.fee_sell,
        balance_after=sell_account.available_cash,
        ref_order_id=sell_order.id,
        ref_trade_id=trade.id,
        note="sell fee",
    )
    _append_ledger(
        state=state,
        season_id=tick.season_id,
        user_id=sell_order.user_id,
        account_id=sell_account.id,
        entry_type="tax",
        amount=-trade.tax_sell,
        balance_after=sell_account.available_cash,
        ref_order_id=sell_order.id,
        ref_trade_id=trade.id,
        note="sell stamp tax",
    )

    state.trades.append(trade)
