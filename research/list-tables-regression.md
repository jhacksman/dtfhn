# list_tables() Regression Report — 2025-07-18

## Summary

A sub-agent applied a "fix" to replace deprecated `db.table_names()` with `db.list_tables()` in `src/storage.py`. The fix was correct in intent but wrong in execution: `list_tables()` returns a `ListTablesResponse` Pydantic object, not `list[str]`. The `in` operator on this object always returns `False`, causing every `get_*_table()` call to attempt `create_table()` on existing tables, crashing with `ValueError: Table 'stories' already exists`.

**Impact:** Pipeline run killed. Required emergency fix and re-run.

---

## Timeline

1. **Post-fix audit** (`research/post-fix-audit.md`) identified `table_names()` deprecation warnings as Issue #6 (LOW severity)
2. A sub-agent replaced all `db.table_names()` calls with `db.list_tables()` — a mechanical find-and-replace
3. Pipeline crashed on first `get_stories_table()` call
4. Emergency fix: added `_table_names()` helper that extracts `.tables` from the response object

---

## Root Cause Analysis

### The Bug

In LanceDB 0.27.1:

```python
db.table_names()    # → ['stories', 'episodes', 'segments']  (list[str], deprecated)
db.list_tables()    # → ListTablesResponse(tables=['stories', ...], page_token=None)
```

`ListTablesResponse` is a Pydantic model. It implements `__iter__` (yielding field name/value tuples: `('tables', [...])`, `('page_token', None)`) but does NOT implement `__contains__`. So:

```python
"stories" in db.table_names()     # True  ✓
"stories" in db.list_tables()     # False ✗ (iterates Pydantic fields, not table names)
```

The `in` operator silently returns `False` — no error, no warning. This is a Python behavior: when `__contains__` is missing, Python falls back to `__iter__`, which yields Pydantic field tuples, none of which match a string.

### Why It Happened

The sub-agent that applied the fix:
1. Read the deprecation warning: "table_names() is deprecated, use list_tables() instead"
2. Assumed `list_tables()` was a drop-in replacement (same return type)
3. Did a mechanical replacement across all call sites
4. **Did not test the actual behavior** — no REPL check, no test script, no reading of the actual API

This is a classic **untested API migration** bug. The deprecation message implied equivalence; the actual API broke the contract.

### Why It Wasn't Caught

- No type checking (`list_tables()` return type isn't annotated as `list[str]` — it's `ListTablesResponse`)
- No unit tests for the table accessor functions
- The `in` operator silently degrades (no TypeError, no warning)
- The sub-agent had no feedback loop — it applied the fix and reported success without running the code

---

## The Fix

A `_table_names()` helper function was added to `src/storage.py`:

```python
def _table_names(db) -> list[str]:
    """Get table names from LanceDB, handling both old and new API."""
    result = db.list_tables()
    if hasattr(result, 'tables'):
        return result.tables
    return list(result)
```

All 6 call sites in `src/storage.py` now use `_table_names(db)`. The helper is forward-compatible: if a future LanceDB version changes `list_tables()` to return `list[str]` directly, the `hasattr` check will take the fallback path.

**Additional fix (this audit):** `scripts/scrape_and_load.py:27` still had a raw `db.list_tables()` call. Updated to use `_table_names(db)` via import.

---

## Verification

All tests pass (`tests/test_table_names.py`):

| Test | Result |
|------|--------|
| `list_tables()` returns `ListTablesResponse` (not `list`) | ✓ |
| `"x" in db.list_tables()` is always `False` (the bug) | ✓ Reproduced |
| `_table_names()` helper returns `list[str]` | ✓ |
| All 3 tables (episodes, stories, segments) create/check/open | ✓ |
| `create_table` on existing table crashes (regression) | ✓ Reproduced |
| `_table_names()` prevents the regression | ✓ |
| Old `table_names()` still works (with deprecation warning) | ✓ |

---

## API Stability Assessment

### Is `.tables` stable?

`ListTablesResponse` is a Pydantic model in `lance_namespace_urllib3_client.models`. The `.tables` attribute is a typed field (`list[str]`). This is part of the LanceDB Cloud/namespace client, which follows OpenAPI spec conventions. **Likely stable** — changing it would break all clients.

### Will `table_names()` be removed?

Unknown timeline. The deprecation warning gives no version target. In practice, deprecated methods in Python libraries tend to survive for multiple major versions. But relying on it is tech debt.

### Other API changes to watch

The `list_tables()` response also includes `page_token` (for pagination). This suggests future versions may paginate large table lists. Our `_table_names()` helper doesn't handle pagination — if we ever have hundreds of tables, we'd need to loop.

---

## Lessons

1. **Never apply API migrations without testing the actual return value.** Deprecation warnings describe intent, not behavior. Always run `type(result)` and `repr(result)` in a REPL before assuming equivalence.

2. **Silent type mismatches are the most dangerous bugs.** Python's duck typing means `in` on a Pydantic model doesn't raise — it just gives wrong answers. Type hints and runtime checks are the defense.

3. **Sub-agents need a verification step.** Any code change must be tested before reporting success. "It compiles" is not "it works."

4. **Centralize API boundary functions.** The `_table_names()` helper encapsulates the LanceDB API quirk in one place. If the API changes again, we fix one function, not six call sites.
