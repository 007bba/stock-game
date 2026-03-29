# Engine MVP (P4)

This folder contains a server-authoritative matching engine MVP for the Stock Game replay environment.

## Modules

- `state.py`: in-memory state and transaction rollback container
- `rules.py`: order validation and reject-code mapping
- `matcher.py`: 5-minute batch matching (price/time priority)
- `ledger.py`: account, position, and cash ledger updates after trades
- `orchestrator.py`: tick-driven flow (order intake + matching + settlement)

## Rules Covered

- T+1 sell restriction
- Lot size 100 shares
- Limit-up/limit-down order price boundaries
- Halted stock blocking
- Sellable quantity check
- Available cash check

Reject codes align with `docs/api/openapi.yaml` `RejectCode` enum.

## How to Run E2E Replay Test

From workspace root:

```bash
python -m unittest tests.engine.test_replay_e2e -v
```

Or run all tests:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

The engine test does not require a real database and is deterministic.
