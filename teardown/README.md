# Teardown

First public artifact. Vendor data is not here.

- Golden cases: `uv run parity reproduce` writes [reproduction.md](reproduction.md)
- 20/50 SMA on synthetic daily bars (`parity.strategy.synthetic_daily_bars`)
- Manual ports: [ports/sma_vectorbt.py](ports/sma_vectorbt.py), [ports/sma_lean.py](ports/sma_lean.py)

Regenerate case files with `uv run python scripts/publish_artifacts.py`. Generated SMA bundles land in `bundles/` (gitignored).
