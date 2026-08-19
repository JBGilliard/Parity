# Reproduction

```
uv sync --group dev --frozen
uv run pytest -q
uv run parity reproduce
```

That recomputes every golden case from source and checks the classification against the catalog. No vendor data is shipped.
