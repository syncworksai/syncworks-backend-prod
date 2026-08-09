from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="EdgeStrategy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="MLB Comeback Edge", max_length=120)),
                ("sport", models.CharField(default="MLB", max_length=16)),
                ("execution_mode", models.CharField(default="MANUAL", max_length=16)),
                ("is_armed", models.BooleanField(default=False)),
                ("daily_risk_limit_cents", models.PositiveIntegerField(default=1500)),
                ("per_trade_limit_cents", models.PositiveIntegerField(default=100)),
                ("minimum_edge_bps", models.PositiveIntegerField(default=800)),
                ("minimum_score", models.PositiveIntegerField(default=85)),
                ("min_entry_cents", models.PositiveIntegerField(default=15)),
                ("max_entry_cents", models.PositiveIntegerField(default=45)),
                ("max_spread_cents", models.PositiveIntegerField(default=3)),
                ("never_chase", models.BooleanField(default=True)),
                ("auto_exit", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edge_strategies", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="EdgeExchangeConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("exchange", models.CharField(choices=[("KALSHI", "Kalshi"), ("POLYMARKET", "Polymarket")], max_length=24)),
                ("environment", models.CharField(choices=[("DEMO", "Demo"), ("LIVE", "Live")], default="DEMO", max_length=12)),
                ("api_key_id", models.CharField(blank=True, max_length=255)),
                ("encrypted_private_key", models.TextField(blank=True)),
                ("can_read", models.BooleanField(default=False)),
                ("can_trade", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edge_exchange_connections", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "exchange", "environment")}},
        ),
        migrations.CreateModel(
            name="EdgeSignal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sport", models.CharField(max_length=16)),
                ("event_key", models.CharField(max_length=160)),
                ("matchup", models.CharField(max_length=180)),
                ("game_state", models.CharField(blank=True, max_length=255)),
                ("side", models.CharField(max_length=120)),
                ("market_price_cents", models.PositiveIntegerField()),
                ("model_probability_bps", models.PositiveIntegerField()),
                ("edge_bps", models.IntegerField()),
                ("opportunity_score", models.PositiveIntegerField(default=0)),
                ("signal", models.CharField(max_length=16)),
                ("max_entry_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("observed_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edge_signals", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-observed_at"]},
        ),
        migrations.CreateModel(
            name="EdgePaperTrade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("side", models.CharField(max_length=120)),
                ("risk_cents", models.PositiveIntegerField(default=100)),
                ("entry_price_cents", models.PositiveIntegerField()),
                ("exit_price_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("EXITED", "Exited"), ("SETTLED", "Settled"), ("SKIPPED", "Skipped")], default="OPEN", max_length=16)),
                ("pnl_cents", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("signal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="paper_trades", to="platform_edge.edgesignal")),
                ("strategy", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="paper_trades", to="platform_edge.edgestrategy")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edge_paper_trades", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="EdgeAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(max_length=80)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edge_audit_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
