# W3: Add weighted quota consumption

Understand this repository and add weighted request costs to the public quota API.

Requirements:

- Change `RateLimitService.check` to accept a keyword-only `cost: int = 1`.
- A successful request consumes exactly `cost` units from the selected route's quota.
- A request that would exceed the limit is denied atomically: it must not change the stored usage.
- `cost` must be a positive integer. Reject zero, negative values, non-integers, and booleans with `ValueError` before changing state.
- Preserve existing behavior for callers that omit `cost`.
- Add focused tests for the new behavior without adding dependencies.
- Run `pytest -q` before and after the change.
