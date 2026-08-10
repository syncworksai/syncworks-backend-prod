from django.conf import settings
from django.db import models


class EdgeExchangeConnection(models.Model):
    EXCHANGES = [("KALSHI", "Kalshi"), ("POLYMARKET", "Polymarket")]
    ENVIRONMENTS = [("DEMO", "Demo"), ("LIVE", "Live")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edge_exchange_connections")
    exchange = models.CharField(max_length=24, choices=EXCHANGES)
    environment = models.CharField(max_length=12, choices=ENVIRONMENTS, default="DEMO")
    api_key_id = models.CharField(max_length=255, blank=True)
    encrypted_private_key = models.TextField(blank=True)
    can_read = models.BooleanField(default=False)
    can_trade = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "exchange", "environment")


class EdgeStrategy(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edge_strategies")
    name = models.CharField(max_length=120, default="MLB Comeback Edge")
    sport = models.CharField(max_length=16, default="MLB")
    execution_mode = models.CharField(max_length=16, default="MANUAL")
    is_armed = models.BooleanField(default=False)
    daily_risk_limit_cents = models.PositiveIntegerField(default=1500)
    per_trade_limit_cents = models.PositiveIntegerField(default=100)
    minimum_edge_bps = models.PositiveIntegerField(default=800)
    minimum_score = models.PositiveIntegerField(default=85)
    min_entry_cents = models.PositiveIntegerField(default=15)
    max_entry_cents = models.PositiveIntegerField(default=45)
    max_spread_cents = models.PositiveIntegerField(default=3)
    never_chase = models.BooleanField(default=True)
    auto_exit = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class EdgeSignal(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edge_signals")
    sport = models.CharField(max_length=16)
    event_key = models.CharField(max_length=160)
    matchup = models.CharField(max_length=180)
    game_state = models.CharField(max_length=255, blank=True)
    side = models.CharField(max_length=120)
    market_price_cents = models.PositiveIntegerField()
    model_probability_bps = models.PositiveIntegerField()
    edge_bps = models.IntegerField()
    opportunity_score = models.PositiveIntegerField(default=0)
    signal = models.CharField(max_length=16)
    max_entry_cents = models.PositiveIntegerField(null=True, blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at"]


class EdgePaperTrade(models.Model):
    STATUSES = [("OPEN", "Open"), ("EXITED", "Exited"), ("SETTLED", "Settled"), ("SKIPPED", "Skipped")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edge_paper_trades")
    signal = models.ForeignKey(EdgeSignal, on_delete=models.SET_NULL, null=True, blank=True, related_name="paper_trades")
    strategy = models.ForeignKey(EdgeStrategy, on_delete=models.SET_NULL, null=True, blank=True, related_name="paper_trades")
    side = models.CharField(max_length=120)
    risk_cents = models.PositiveIntegerField(default=100)
    entry_price_cents = models.PositiveIntegerField()
    exit_price_cents = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default="OPEN")
    pnl_cents = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)


class EdgeAuditEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edge_audit_events")
    event_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class EdgeHistoricalSnapshot(models.Model):
    """One-minute replay point joining a historical MLB state to a Kalshi price."""

    game_pk = models.BigIntegerField()
    market_ticker = models.CharField(max_length=180)
    event_ticker = models.CharField(max_length=180, blank=True)
    observed_at = models.DateTimeField(db_index=True)
    away_code = models.CharField(max_length=8)
    home_code = models.CharField(max_length=8)
    side_code = models.CharField(max_length=8)
    away_score = models.PositiveSmallIntegerField(default=0)
    home_score = models.PositiveSmallIntegerField(default=0)
    inning = models.PositiveSmallIntegerField(null=True, blank=True)
    inning_half = models.CharField(max_length=8, blank=True)
    outs = models.PositiveSmallIntegerField(default=0)
    runners_on_base = models.PositiveSmallIntegerField(default=0)
    yes_bid_cents = models.PositiveSmallIntegerField(null=True, blank=True)
    yes_ask_cents = models.PositiveSmallIntegerField(null=True, blank=True)
    yes_close_cents = models.PositiveSmallIntegerField(null=True, blank=True)
    market_result = models.CharField(max_length=8, blank=True)
    model_probability_bps = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["market_ticker", "observed_at"], name="edge_hist_market_time_uniq"),
        ]
        indexes = [
            models.Index(fields=["game_pk", "observed_at"]),
            models.Index(fields=["side_code", "away_score", "home_score", "inning"]),
        ]
        ordering = ["observed_at"]
