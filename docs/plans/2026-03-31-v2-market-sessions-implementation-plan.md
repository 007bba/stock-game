# V2 Market Sessions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first backend slice of stock-game v2 with standalone training session tables and APIs for create session, load replay timeline, submit trades with notes, and finish a session with computed results.

**Architecture:** Keep v2 isolated from the legacy `season/accounts/orders` multiplayer model. Reuse existing replay market data (`market_ticks` + `market_tick_quotes`) as the price source, but persist v2 session state in dedicated `market_sessions*` tables and a dedicated service module. Expose the new flow under `/v2/market-sessions/*` so current v1 endpoints and frontend fallbacks keep working.

**Tech Stack:** FastAPI, PostgreSQL via psycopg2/SQLAlchemy-compatible SQL, existing Supabase JWT auth helpers, Python `unittest` with `fastapi.testclient`.

---

### Task 1: Add v2 session tables to schema

**Files:**
- Modify: `db/schema.sql`

**Step 1: Add minimal standalone tables**

- Add `market_session_status` and `market_trade_side` enums.
- Add `market_sessions`, `market_session_positions`, `market_session_trades`, `market_session_trade_notes`, `market_session_results`.
- Keep foreign keys pointing to `users` and `seasons`, but do not reference legacy `accounts/orders/trades`.

**Step 2: Keep indexes minimal**

- Add lookup indexes by `user_id`, `season_id`, and `session_id`.
- Add uniqueness on one position row per `(session_id, ts_code)` and one result row per session.

**Step 3: Sanity-check naming**

- Avoid collisions with existing `positions`, `trades`, and `orders`.

### Task 2: Implement v2 service layer

**Files:**
- Create: `scripts/service/market_session_service.py`

**Step 1: Write service contract**

- `create_session(user_id, email, season_id, ts_code, initial_cash)`
- `get_session(session_id, user_id)`
- `get_timeline(session_id, user_id)`
- `submit_trade(session_id, user_id, side, quantity, step_no, note, tag)`
- `finish_session(session_id, user_id, step_no)`
- `get_result(session_id, user_id)`

**Step 2: Reuse replay data**

- Load timeline rows from `market_ticks` + `market_tick_quotes` for the chosen `season_id` and `ts_code`.
- Return `stepNo`, `tickId`, `gameDayNo`, `minuteOfDay`, `phase`, `price`, and `volume`.

**Step 3: Implement minimal trade rules**

- Session must be `running`.
- Quantity must be positive and in lots of 100.
- `step_no` must map to an existing timeline row.
- Buy checks cash; sell checks position quantity.
- Persist trade row, optional note row, update cash and position snapshot atomically.

**Step 4: Implement finish logic**

- Session transitions to `finished`.
- Final assets = cash + position qty * current step price.
- Persist trade count, realized return, and a short rule-based summary.

### Task 3: Expose v2 API endpoints

**Files:**
- Modify: `scripts/service/api.py`
- Modify: `scripts/main.py`

**Step 1: Add request/response models**

- Create body models for create session, submit trade, and finish session.

**Step 2: Add endpoints**

- `POST /v2/market-sessions`
- `GET /v2/market-sessions/{sessionId}`
- `GET /v2/market-sessions/{sessionId}/timeline`
- `POST /v2/market-sessions/{sessionId}/trades`
- `GET /v2/market-sessions/{sessionId}/trades`
- `POST /v2/market-sessions/{sessionId}/finish`
- `GET /v2/market-sessions/{sessionId}/result`

**Step 3: Keep v1 behavior unchanged**

- Make `market_session_service` optional in `create_app`.
- Wire the concrete DB-backed service in `scripts/main.py`.

### Task 4: Add API tests for the v2 flow

**Files:**
- Create: `tests/service/test_market_session_api.py`

**Step 1: Use an in-memory fake service**

- Avoid DB dependency in route contract tests.
- Cover auth required, create session success, timeline fetch, trade submit, finish, and result fetch.

**Step 2: Cover main error paths**

- Missing session -> `404`
- Invalid quantity or step -> `400`
- Insufficient cash / insufficient position -> `400`

### Task 5: Verify and document progress

**Files:**
- Modify: `docs/plans/2026-03-31-v2-refactor-progress.md`

**Step 1: Run focused verification**

- `python -m unittest tests.service.test_market_session_api -v`
- `python -m unittest tests.service.test_api_orders tests.service.test_tick_api -v`
- If local typecheck is touched later: `cd frontend && npx tsc -p tsconfig.app.json --noEmit`

**Step 2: Update progress doc**

- Record that v2 backend API skeleton now exists separately from legacy season trading.
