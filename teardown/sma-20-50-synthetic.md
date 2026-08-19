# Audit: sma-20-50-synthetic

Given immutable inputs and an explicit execution specification, Parity finds the first causal divergence between backtests, classifies it when evidence supports the classification, and emits a reproducible audit bundle.

- title: 20/50 SMA on synthetic daily bars
- isolated variable: `fill_timing`
- expected: `fill_timing`
- observed: `fill_timing`
- engines: `oracle` vs `oracle_mutated`

## Execution specification (left)

```json
{
  "fill_timing": "next_bar",
  "fill_price": "open",
  "fee": {
    "mode": "per_share",
    "value": "0.01",
    "rounding": "half_even",
    "decimals": 2
  },
  "cash": "reject",
  "simultaneous_orders": "symbol_lexicographic",
  "missing_bar": "skip",
  "session": {
    "timezone": "America/New_York",
    "calendar": "XNYS",
    "regular_hours_only": true
  },
  "adjustment": "raw",
  "dividend": "cash",
  "lookahead": "forbidden",
  "fractional_shares": false
}
```

## Execution specification (right)

```json
{
  "fill_timing": "same_bar",
  "fill_price": "open",
  "fee": {
    "mode": "per_share",
    "value": "0.01",
    "rounding": "half_even",
    "decimals": 2
  },
  "cash": "reject",
  "simultaneous_orders": "symbol_lexicographic",
  "missing_bar": "skip",
  "session": {
    "timezone": "America/New_York",
    "calendar": "XNYS",
    "regular_hours_only": true
  },
  "adjustment": "raw",
  "dividend": "cash",
  "lookahead": "forbidden",
  "fractional_shares": false
}
```

## First divergence

- timestamp: `2022-03-11T14:30:00+00:00`
- event: `fill.presence`
- left: `<missing>`
- right: `1`

## Evidence

- fill.presence <missing> vs 1

## Notes

Synthetic daily bars. Databento sample is not in this repository.

## Reproduction

`uv run parity audit sma-20-50-synthetic`
