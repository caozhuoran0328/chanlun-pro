# Plan
## Goal
Create `get_duokong_bi.py` with a BI-level state machine (following `get_duokong_xd.py`'s pattern), and integrate it to replace the old BI-level code in `get_duokong_suidao.py`.

## Scope
- In scope:
  - Create `get_duokong_bi.py` with `Bi_DuoKong_Process` state machine (8 states, 4 signal types)
  - Create `Bi_DuoKong` signal class and `Bi_DuoKong_Process_Status` enum
  - Write `compute_duokong_bi()` entry function (BI-level, returns `dksd_high[]`, `dksd_low[]`, `signals`, `tunnels`)
  - Replace `compute_duokong_suidao()` in `get_duokong_suidao.py` to use the new BI state machine
  - Update `cl.py` caller code to use new function
  - Write unit tests for the BI state machine
  - Ensure all existing tests pass
- Out of scope:
  - Modifying XD-level code (stays in `get_duokong_suidao.py` or `get_duokong_xd.py`)
  - Front-end changes
  - Class 3 `sub_signals` parameter (state machine handles class 3 via THREE_NO_PO_ONE state, no external sub_signals needed)

## Deliverables
- [ ] `src/chanlun/get_duokong_bi.py` — BI-level state machine module
- [ ] Updated `src/chanlun/get_duokong_suidao.py` — BI-level entry function uses new state machine
- [ ] Updated `src/chanlun/cl.py` — caller uses new `compute_duokong_bi()`
- [ ] `tests/test_get_duokong_bi.py` — BI state machine unit tests
- [ ] All tests pass

## Technical Approach

### Architecture
Mirror `get_duokong_xd.py` structure:

```
get_duokong_bi.py
├── DuoKong_Status (reuse from get_duokong_xd.py or redefine)
├── Bi_DuoKong — signal object (status, typeNum, compare_price, duokong_price)
├── Bi_DuoKong_Process_Status — 8 states enum (START, LEFT, LEFT_AFTER, LEFT_AFTER_NORMAL, MIDDLE, MIDDLE_AFTER, TURN_V, THREE_NO_PO_ONE)
├── Bi_DuoKong_Process — state machine class
│   └── find_duokong_status(bi: BI) → Bi_DuoKong | None
└── compute_duokong_bi(bis, klines) → dict  — entry function
```

### Key Differences from XD version
| Aspect | XD version | BI version |
|--------|-----------|------------|
| Input | `List[XD]` | `List[BI]` |
| Direction check | `XianDuanType.UP/DOWN` | `BiType.UP/DOWN` |
| K-line trigger | `_find_kline_after_xd()` — first kline after XD end date | First kline after BI end date (same pattern) |
| Price fields | `xd.high`, `xd.low` | `bi.high`, `bi.low` |
| FX access | `xd.end.k.date` | `bi.end.k.date` |

### Integration
- `compute_duokong_suidao()` in `get_duokong_suidao.py` will call `compute_duokong_bi()` internally
- Return format: `{dksd_high, dksd_low, signals, tunnels}` (same as XD-level)
- `cl.py` caller updated to use new return format (no more `tunnels_high/tunnels_low` with `old_high/old_low`)

### Trigger K-line Logic
BI-level uses the first kline whose date >= BI.end.k.date, same pattern as XD-level. The trigger condition:
- DUO signal: trigger_k.h > sig.compare_price
- KONG signal: trigger_k.l < sig.compare_price

## Research Guidance
- Source file: `/Users/caojing/Margay-Projects/chanlun-pro/src/chanlun/get_duokong_xd.py` — the state machine to replicate
- Source file: `/Users/caojing/Margay-Projects/chanlun-pro/src/chanlun/get_duokong_suidao.py` — current BI/XD code
- Integration: `/Users/caojing/Margay-Projects/chanlun-pro/src/chanlun/cl.py` — caller code
- Types: `/Users/caojing/Margay-Projects/chanlun-pro/src/chanlun/cl_interface.py` — BI, BiType, FX, CLKline definitions
- Tests: `/Users/caojing/Margay-Projects/chanlun-pro/tests/test_get_duokong_suidao.py` — existing BI tests

## Acceptance Criteria
1. `get_duokong_bi.py` contains a working `Bi_DuoKong_Process` state machine with all 8 states
2. State machine correctly detects all 4 signal types (转多/转空, 强多/强空, 多强/空强, 反多/反空)
3. `compute_duokong_bi()` returns `dksd_high[]`, `dksd_low[]`, `signals`, `tunnels`
4. Integration: `cl.py` can call the new function without errors
5. All unit tests pass (new BI tests + existing XD tests)
6. Web server can load SZ.300491 without KeyError

## Phase Context
Previous phase: XD-level state machine implemented in `get_duokong_xd.py`, integrated into `get_duokong_suidao.py` as `_compute_dk_sequences`. All 50 tests passing (22 BI-level old style + 28 XD-level state machine).
Current issue: BI-level still uses old direct-pattern-matching approach; need to migrate to state machine pattern.
