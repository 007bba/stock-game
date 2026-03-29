-- Stock Game MVP schema
-- PostgreSQL 15+

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'season_status') THEN
    CREATE TYPE season_status AS ENUM ('draft', 'scheduled', 'running', 'ended', 'archived');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'market_role') THEN
    CREATE TYPE market_role AS ENUM ('leader', 'follower', 'trend');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'session_phase') THEN
    CREATE TYPE session_phase AS ENUM ('open_auction', 'am_continuous', 'lunch_break', 'pm_continuous', 'close_auction');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'matching_mode') THEN
    CREATE TYPE matching_mode AS ENUM ('accept_only', 'batch_match', 'open_call_auction', 'close_call_auction', 'frozen');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_side') THEN
    CREATE TYPE order_side AS ENUM ('buy', 'sell');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_status') THEN
    CREATE TYPE order_status AS ENUM ('pending', 'active', 'partially_filled', 'filled', 'canceled', 'rejected', 'expired');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ledger_entry_type') THEN
    CREATE TYPE ledger_entry_type AS ENUM (
      'freeze', 'unfreeze', 'trade_buy', 'trade_sell', 'fee', 'tax', 'settlement', 'manual_adjustment'
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'etl_job_status') THEN
    CREATE TYPE etl_job_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'canceled');
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  login_name VARCHAR(64) UNIQUE NOT NULL,
  display_name VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS seasons (
  id BIGSERIAL PRIMARY KEY,
  season_code VARCHAR(32) UNIQUE NOT NULL,
  season_name VARCHAR(128) NOT NULL,
  status season_status NOT NULL DEFAULT 'draft',
  total_game_days INT NOT NULL DEFAULT 10 CHECK (total_game_days > 0),
  day_minutes INT NOT NULL DEFAULT 60 CHECK (day_minutes = 60),
  start_at TIMESTAMPTZ,
  end_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS season_days (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  game_day_no INT NOT NULL CHECK (game_day_no > 0),
  market_date DATE NOT NULL,
  start_at TIMESTAMPTZ,
  end_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (season_id, game_day_no),
  UNIQUE (season_id, market_date)
);

CREATE TABLE IF NOT EXISTS season_universe (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  ts_code VARCHAR(16) NOT NULL,
  role market_role NOT NULL,
  event_tag VARCHAR(64) NOT NULL,
  rank_in_theme INT NOT NULL CHECK (rank_in_theme > 0),
  labels TEXT[] NOT NULL DEFAULT '{}',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (season_id, ts_code)
);

CREATE TABLE IF NOT EXISTS trading_calendar (
  exchange VARCHAR(8) NOT NULL DEFAULT 'SSE',
  cal_date DATE NOT NULL,
  is_open BOOLEAN NOT NULL,
  pretrade_date DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE IF NOT EXISTS raw_minute_bars (
  id BIGSERIAL PRIMARY KEY,
  ts_code VARCHAR(16) NOT NULL,
  trade_time TIMESTAMPTZ NOT NULL,
  trade_date DATE NOT NULL,
  open_price NUMERIC(12, 3) NOT NULL CHECK (open_price > 0),
  high_price NUMERIC(12, 3) NOT NULL CHECK (high_price > 0),
  low_price NUMERIC(12, 3) NOT NULL CHECK (low_price > 0),
  close_price NUMERIC(12, 3) NOT NULL CHECK (close_price > 0),
  vol BIGINT NOT NULL DEFAULT 0 CHECK (vol >= 0),
  amount NUMERIC(20, 3) NOT NULL DEFAULT 0 CHECK (amount >= 0),
  source_name VARCHAR(32) NOT NULL DEFAULT 'tushare',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ts_code, trade_time)
);

CREATE TABLE IF NOT EXISTS corp_actions (
  id BIGSERIAL PRIMARY KEY,
  ts_code VARCHAR(16) NOT NULL,
  ex_date DATE NOT NULL,
  action_type VARCHAR(32) NOT NULL,
  adjust_factor NUMERIC(20, 10),
  cash_dividend NUMERIC(12, 4),
  split_ratio NUMERIC(12, 6),
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ts_code, ex_date, action_type)
);

CREATE TABLE IF NOT EXISTS trading_halts (
  id BIGSERIAL PRIMARY KEY,
  ts_code VARCHAR(16) NOT NULL,
  trade_date DATE NOT NULL,
  suspend_type VARCHAR(1) NOT NULL CHECK (suspend_type IN ('S', 'R')),
  suspend_timing VARCHAR(64) NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (ts_code, trade_date, suspend_type, suspend_timing)
);

CREATE TABLE IF NOT EXISTS etl_jobs (
  id BIGSERIAL PRIMARY KEY,
  job_type VARCHAR(32) NOT NULL,
  season_id BIGINT REFERENCES seasons(id) ON DELETE SET NULL,
  start_date DATE,
  end_date DATE,
  status etl_job_status NOT NULL DEFAULT 'pending',
  attempt INT NOT NULL DEFAULT 1 CHECK (attempt > 0),
  row_count BIGINT NOT NULL DEFAULT 0,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_ticks (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  game_day_no INT NOT NULL CHECK (game_day_no > 0),
  minute_of_day SMALLINT NOT NULL CHECK (minute_of_day BETWEEN 1 AND 60),
  phase session_phase NOT NULL,
  matching_mode matching_mode NOT NULL,
  is_tradable BOOLEAN NOT NULL,
  is_matching_point BOOLEAN NOT NULL DEFAULT FALSE,
  scheduled_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (season_id, game_day_no, minute_of_day)
);

CREATE TABLE IF NOT EXISTS market_tick_quotes (
  id BIGSERIAL PRIMARY KEY,
  tick_id BIGINT NOT NULL REFERENCES market_ticks(id) ON DELETE CASCADE,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  ts_code VARCHAR(16) NOT NULL,
  ref_price NUMERIC(12, 3) NOT NULL CHECK (ref_price > 0),
  open_price NUMERIC(12, 3),
  high_price NUMERIC(12, 3),
  low_price NUMERIC(12, 3),
  close_price NUMERIC(12, 3),
  vwap_price NUMERIC(12, 3),
  volume BIGINT NOT NULL DEFAULT 0 CHECK (volume >= 0),
  volume_factor NUMERIC(12, 6) NOT NULL DEFAULT 1,
  upper_limit_price NUMERIC(12, 3) NOT NULL,
  lower_limit_price NUMERIC(12, 3) NOT NULL,
  is_halted BOOLEAN NOT NULL DEFAULT FALSE,
  auction_imbalance_ratio NUMERIC(12, 6),
  auction_hint_level SMALLINT NOT NULL DEFAULT 0 CHECK (auction_hint_level BETWEEN 0 AND 3),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tick_id, ts_code)
);

CREATE TABLE IF NOT EXISTS accounts (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  initial_cash NUMERIC(18, 2) NOT NULL DEFAULT 1000000 CHECK (initial_cash >= 0),
  available_cash NUMERIC(18, 2) NOT NULL DEFAULT 1000000,
  frozen_cash NUMERIC(18, 2) NOT NULL DEFAULT 0,
  realized_pnl NUMERIC(18, 2) NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (season_id, user_id),
  CHECK (available_cash >= 0),
  CHECK (frozen_cash >= 0)
);

CREATE TABLE IF NOT EXISTS positions (
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ts_code VARCHAR(16) NOT NULL,
  qty_total BIGINT NOT NULL DEFAULT 0 CHECK (qty_total >= 0),
  qty_sellable BIGINT NOT NULL DEFAULT 0 CHECK (qty_sellable >= 0),
  avg_cost NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (avg_cost >= 0),
  last_settled_game_day INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (season_id, user_id, ts_code),
  CHECK (qty_sellable <= qty_total),
  CHECK ((qty_total % 100) = 0),
  CHECK ((qty_sellable % 100) = 0)
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  client_order_id VARCHAR(64) NOT NULL,
  ts_code VARCHAR(16) NOT NULL,
  side order_side NOT NULL,
  limit_price NUMERIC(12, 3) NOT NULL CHECK (limit_price > 0),
  quantity BIGINT NOT NULL CHECK (quantity > 0 AND (quantity % 100) = 0),
  remaining_qty BIGINT NOT NULL CHECK (remaining_qty >= 0 AND (remaining_qty % 100) = 0),
  status order_status NOT NULL DEFAULT 'pending',
  phase_submitted session_phase NOT NULL,
  submitted_tick_id BIGINT REFERENCES market_ticks(id) ON DELETE SET NULL,
  effective_tick_id BIGINT REFERENCES market_ticks(id) ON DELETE SET NULL,
  reject_code VARCHAR(64),
  reject_reason TEXT,
  created_seq INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  canceled_at TIMESTAMPTZ,
  UNIQUE (season_id, user_id, client_order_id)
);

CREATE TABLE IF NOT EXISTS trades (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  tick_id BIGINT NOT NULL REFERENCES market_ticks(id) ON DELETE RESTRICT,
  ts_code VARCHAR(16) NOT NULL,
  trade_price NUMERIC(12, 3) NOT NULL CHECK (trade_price > 0),
  quantity BIGINT NOT NULL CHECK (quantity > 0 AND (quantity % 100) = 0),
  buy_order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  sell_order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  fee_buy NUMERIC(18, 2) NOT NULL DEFAULT 0,
  fee_sell NUMERIC(18, 2) NOT NULL DEFAULT 0,
  tax_sell NUMERIC(18, 2) NOT NULL DEFAULT 0,
  matched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (buy_order_id <> sell_order_id)
);

CREATE TABLE IF NOT EXISTS cash_ledger (
  id BIGSERIAL PRIMARY KEY,
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
  entry_type ledger_entry_type NOT NULL,
  amount NUMERIC(18, 2) NOT NULL CHECK (amount <> 0),
  balance_after NUMERIC(18, 2) NOT NULL,
  ref_order_id BIGINT REFERENCES orders(id) ON DELETE SET NULL,
  ref_trade_id BIGINT REFERENCES trades(id) ON DELETE SET NULL,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_account_snapshots (
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game_day_no INT NOT NULL CHECK (game_day_no > 0),
  cash_balance NUMERIC(18, 2) NOT NULL,
  market_value NUMERIC(18, 2) NOT NULL,
  total_asset NUMERIC(18, 2) NOT NULL,
  daily_return_pct NUMERIC(9, 4) NOT NULL,
  cumulative_return_pct NUMERIC(9, 4) NOT NULL,
  max_drawdown_pct NUMERIC(9, 4) NOT NULL,
  score NUMERIC(9, 4) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (season_id, user_id, game_day_no)
);

CREATE TABLE IF NOT EXISTS season_leaderboard (
  season_id BIGINT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rank_no INT NOT NULL CHECK (rank_no > 0),
  score NUMERIC(9, 4) NOT NULL,
  cumulative_return_pct NUMERIC(9, 4) NOT NULL,
  max_drawdown_pct NUMERIC(9, 4) NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (season_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_season_universe_season ON season_universe(season_id);
CREATE INDEX IF NOT EXISTS idx_raw_minute_code_date ON raw_minute_bars(ts_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_minute_code_time ON raw_minute_bars(ts_code, trade_time);
CREATE INDEX IF NOT EXISTS idx_corp_actions_code_date ON corp_actions(ts_code, ex_date);
CREATE INDEX IF NOT EXISTS idx_halts_code_date ON trading_halts(ts_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_market_ticks_season_time ON market_ticks(season_id, game_day_no, minute_of_day);
CREATE INDEX IF NOT EXISTS idx_market_tick_quotes_lookup ON market_tick_quotes(season_id, ts_code, tick_id);
CREATE INDEX IF NOT EXISTS idx_orders_lookup ON orders(season_id, ts_code, status, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_user_lookup ON orders(season_id, user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_trades_lookup ON trades(season_id, ts_code, tick_id);
CREATE INDEX IF NOT EXISTS idx_ledger_account_time ON cash_ledger(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_snapshot_season_score ON daily_account_snapshots(season_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_leaderboard_rank ON season_leaderboard(season_id, rank_no);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_seasons_updated_at ON seasons;
CREATE TRIGGER trg_seasons_updated_at BEFORE UPDATE ON seasons
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_accounts_updated_at ON accounts;
CREATE TRIGGER trg_accounts_updated_at BEFORE UPDATE ON accounts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_positions_updated_at ON positions;
CREATE TRIGGER trg_positions_updated_at BEFORE UPDATE ON positions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_orders_updated_at ON orders;
CREATE TRIGGER trg_orders_updated_at BEFORE UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

