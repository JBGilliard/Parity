# Parity

Backtesting engines disagree. Data vendors disagree on symbology and corporate actions. Live fills drift from the research book. Parity is the unification layer: one event ledger, explicit execution assumptions, and a first-break diff so a mismatch has a cause instead of a vibe.

This repo is the early harness — golden micro-cases, a spec interpreter, vectorbt and LEAN adapters. It is not the v1 library (vendor adapters, four engine readers, futures stitching, `parity audit run.yaml`).

`unexplained` is a valid result. Parity does not rank engines.

## Install

```
uv sync --group dev
uv run parity cases
uv run parity audit fill-timing-next-vs-same
uv run parity reproduce
```

Optional engines: `uv sync --group vectorbt` (Commons Clause — do not redistribute or sell vectorbt). LEAN reads checked-in result JSON; live runs stay in `quantconnect/lean:18008`.

Reproduce the golden corpus: [REPRODUCTION.md](REPRODUCTION.md). Cases: [cases/](cases/). Engine coverage: [docs/observability.md](docs/observability.md).

## License

Apache-2.0. Core code does not import engine SDKs.

- **LEAN:** Apache-2.0. Official Docker image; record the digest.
- **vectorbt:** Apache-2.0 with Commons Clause. Optional extra only.
- **Backtrader:** GPL-3.0-or-later. Optional extra; GPL does not enter the core tree.
- **NautilusTrader:** LGPL-3.0-or-later. Optional extra.
- **Vendor data:** never redistributed. Pin checksums; publish hashes and synthetic bundles only.
