# Engine event coverage

vectorbt 1.1.0 exposes filled orders, per-bar cash/position logs, and Filled/Ignored/rejected-style status when log=True. LEAN local results expose Orders, order-events (fill price/qty/fee), and equity charts. Position series in LEAN JSON is reconstructed from fills when holdings are absent. Corporate-action and lookahead evidence are native in the spec interpreter and reconstructed or gap-flagged in the engine adapters.

## Primary engines

### vectorbt

- pin: `1.1.0`
- extra: optional `uv` group `vectorbt` (Commons Clause). core never imports it.

| event | status | notes |
|---|---|---|
| bar | native | input bars retained in the ledger |
| signal | native | Parity signal table is retained, not a vectorbt object |
| order | native | filled orders via Portfolio.orders; rejects via logs |
| fill | native | order records are fills |
| fee | native | orders.Fees column |
| cash | native | logs New Cash and pf.cash() |
| position | native | logs New Position and pf.assets() |
| corporate_action | unavailable | no native CA stream; input table stored as raw |

### lean

- pin: `quantconnect/lean:18008`
- reader: always importable. live docker is opt-in.

| event | status | notes |
|---|---|---|
| bar | native | input bars retained; LEAN data files are not redistributed |
| signal | gap | only present if the algorithm logs insights |
| order | native | Orders key in the backtest JSON |
| fill | native | order-events.json fillPrice/fillQuantity |
| fee | native | order-events orderFeeAmount |
| cash | reconstructed | equity chart minus reconstructed market value |
| position | reconstructed | holdings time series often absent locally |
| corporate_action | gap | requires LEAN data mappings; not in a bare result JSON |

## Gaps

- vectorbt `orders` are fills. Unfilled/rejected intent lives in `logs` when `log=True`.
- vectorbt has no native corporate-action stream; adapters record the input CA table beside the run.
- LEAN local JSON often omits a holdings time series; positions are reconstructed from fills and marked as such.
- Per-share fee rounding to banker's decimals is an interpreter property. vectorbt uses binary floats.
- Live `docker run quantconnect/lean:18008` is optional. The reader is first-class; a missing daemon is not a missing schema.

