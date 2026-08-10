# EDGE Research Backtest

This module replays completed MLB game states to test calibration of the experimental win-probability model. It does not ingest historical Kalshi prices and does not place exchange orders.

Use the authenticated endpoint `GET /api/v1/edge/research/mlb/backtest/?days=14&max_games=100` to run a bounded test.

A profitable market-strategy conclusion requires a separate dataset containing historical market prices, bid/ask spreads, fees, and executable timing.
