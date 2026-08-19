# Golden reproduction

| case | expected | actual | ok |
|---|---|---|---|
| fill-timing-next-vs-same | fill_timing | fill_timing | True |
| fill-timing-matched | None | None | True |
| fill-price-open-vs-close | fill_price | fill_price | True |
| fill-price-matched | None | None | True |
| fee-rounding-half-even-vs-truncate | fee | fee | True |
| fee-matched | None | None | True |
| cash-reject-vs-partial | cash_margin_rejection | cash_margin_rejection | True |
| cash-matched | None | None | True |
| missing-bar-left-gap | bar_session_alignment | bar_session_alignment | True |
| bar-matched | None | None | True |
| timezone-ny-vs-utc | bar_session_alignment | bar_session_alignment | True |
| split-applied-vs-ignored | corporate_action | corporate_action | True |
| split-matched | None | None | True |
| dividend-cash-vs-omitted | corporate_action | corporate_action | True |
| lookahead-sentinel | lookahead | lookahead | True |
| lookahead-matched | None | None | True |
| rebalance-ordering | unexplained | unexplained | True |
| rebalance-matched | None | None | True |
