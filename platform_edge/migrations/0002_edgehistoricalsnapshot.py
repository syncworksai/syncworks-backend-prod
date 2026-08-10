from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_edge", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EdgeHistoricalSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("game_pk", models.BigIntegerField()),
                ("market_ticker", models.CharField(max_length=180)),
                ("event_ticker", models.CharField(blank=True, max_length=180)),
                ("observed_at", models.DateTimeField(db_index=True)),
                ("away_code", models.CharField(max_length=8)),
                ("home_code", models.CharField(max_length=8)),
                ("side_code", models.CharField(max_length=8)),
                ("away_score", models.PositiveSmallIntegerField(default=0)),
                ("home_score", models.PositiveSmallIntegerField(default=0)),
                ("inning", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("inning_half", models.CharField(blank=True, max_length=8)),
                ("outs", models.PositiveSmallIntegerField(default=0)),
                ("runners_on_base", models.PositiveSmallIntegerField(default=0)),
                ("yes_bid_cents", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("yes_ask_cents", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("yes_close_cents", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("market_result", models.CharField(blank=True, max_length=8)),
                ("model_probability_bps", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="edgehistoricalsnapshot",
            constraint=models.UniqueConstraint(fields=("market_ticker", "observed_at"), name="edge_hist_market_time_uniq"),
        ),
        migrations.AddIndex(
            model_name="edgehistoricalsnapshot",
            index=models.Index(fields=["game_pk", "observed_at"], name="platform_ed_game_pk_8a9b7f_idx"),
        ),
        migrations.AddIndex(
            model_name="edgehistoricalsnapshot",
            index=models.Index(fields=["side_code", "away_score", "home_score", "inning"], name="platform_ed_side_co_7d8f0e_idx"),
        ),
    ]
