from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from platform_growth.services.runtime import (
    prepare_due_scheduled_posts,
    publish_ready_scheduled_posts,
    run_due_recipes,
)


class Command(BaseCommand):
    help = "Run due SyncWorks Growth bots, prepare approved posts, and publish READY social jobs."

    def add_arguments(self, parser):
        parser.add_argument("--recipe-limit", type=int, default=100)
        parser.add_argument("--post-limit", type=int, default=50)
        parser.add_argument("--publish-limit", type=int, default=25)
        parser.add_argument(
            "--skip-post-prep",
            action="store_true",
            help="Run recipes without preparing due scheduled social jobs.",
        )
        parser.add_argument(
            "--skip-publish",
            action="store_true",
            help="Prepare approved jobs without sending READY jobs to providers.",
        )

    def handle(self, *args, **options):
        started_at = timezone.now()
        recipe_results = run_due_recipes(limit=max(1, options["recipe_limit"]), now=started_at)

        post_counts = {"ready": 0, "skipped": 0}
        if not options["skip_post_prep"]:
            post_counts = prepare_due_scheduled_posts(
                limit=max(1, options["post_limit"]),
                now=started_at,
            )

        publish_counts = {"published": 0, "failed": 0, "skipped": 0}
        if not options["skip_publish"]:
            publish_counts = publish_ready_scheduled_posts(
                limit=max(1, options["publish_limit"]),
                now=started_at,
            )

        completed = sum(1 for _, result in recipe_results if result.status == "COMPLETED")
        failed = sum(1 for _, result in recipe_results if result.status == "FAILED")
        skipped = sum(1 for _, result in recipe_results if result.status == "SKIPPED")

        self.stdout.write(
            self.style.SUCCESS(
                "Growth runtime finished: "
                f"recipes={len(recipe_results)} completed={completed} failed={failed} skipped={skipped}; "
                f"scheduled_posts_ready={post_counts['ready']} post_prep_skipped={post_counts['skipped']}; "
                f"published={publish_counts['published']} publish_failed={publish_counts['failed']} "
                f"publish_skipped={publish_counts['skipped']}."
            )
        )

        for recipe_id, result in recipe_results:
            self.stdout.write(f"recipe={recipe_id} status={result.status} message={result.message}")
