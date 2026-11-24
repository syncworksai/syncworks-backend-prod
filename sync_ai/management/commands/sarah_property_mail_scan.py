"""Hourly opt-in Sarah property inbox scanner; scheduled externally by existing cron.

No LLM calls, email sends, full-message reads, or user-facing automatic tasks.
Stores only category counts and a timestamp. Run manually after verifying
Microsoft permissions; schedule requires explicit environment enablement.
"""
import logging
import os
from datetime import timedelta
from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from user_accounts.models import AuditLog

from sync_ai.assist_pilot_views import PILOT_EMAIL
from sync_ai.assist_multi_mailbox_views import settings, snapshot, graph
from sync_ai.assist_property_mail_analysis import classify, SCAN_ACTION, MAX_SCAN

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Opt-in, bounded hourly property email review; no external writes."

    def handle(self, *args, **options):
        if os.getenv("SYNC_ASSIST_SARAH_SCAN_ENABLED", "").lower() != "true":
            self.stdout.write("Sarah scheduled mailbox scan disabled.")
            return
        cfg = settings()
        if cfg is None:
            self.stdout.write("Sarah mailbox scan skipped: Outlook credentials unavailable on cron.")
            return
        user = get_user_model().objects.filter(email__iexact=PILOT_EMAIL, is_active=True).first()
        if user is None:
            self.stdout.write("Sarah mailbox scan skipped: account not available.")
            return
        eligible = [a for a in snapshot(user) if a.get("category") == "PROPERTY"][:3]
        if not eligible:
            self.stdout.write("Sarah mailbox scan skipped: no property mailboxes.")
            return
        processed = 0
        for account in eligible:
            identifier = account["account_id"]
            latest = AuditLog.objects.filter(
                actor=user, action=SCAN_ACTION,
                metadata__account_id=identifier,
            ).order_by("-id").first()
            if latest and latest.created_at > timezone.now() - timedelta(minutes=55):
                continue
            try:
                result = graph(user, cfg, identifier,
                               "/me/mailFolders/inbox/messages", params={
                                  "$top":MAX_SCAN,
                                  "$orderby":"receivedDateTime desc",
                                  "$select":"id,subject,from,receivedDateTime,bodyPreview,importance",
                               })
                findings = [f for item in (result.get("value") or [])[:MAX_SCAN]
                            if (f := classify(item)) is not None]
                counts = dict(Counter(f["category"] for f in findings))
                AuditLog.objects.create(actor=user, action=SCAN_ACTION, metadata={
                    "account_id":identifier,
                    "checked_at":timezone.now().isoformat(),
                    "sample_size":min(len(result.get("value") or []), MAX_SCAN),
                    "finding_count":len(findings),
                    "category_counts":counts,
                    "mode":"SCHEDULED_READ_ONLY_RULES",
                    "partial_sample":bool(result.get("@odata.nextLink")),
                })
                processed += 1
            except Exception:
                # Avoid printing personally identifying email content or tokens.
                logger.warning("Sarah scheduled mailbox review failed for a mailbox.")
        self.stdout.write(f"Sarah scheduled read-only scans completed: {processed}.")
