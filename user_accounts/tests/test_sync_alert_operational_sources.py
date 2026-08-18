from django.contrib.auth import get_user_model
from django.test import TestCase

from platform_growth.models import GrowthChannelConnection, GrowthContentDraft, GrowthContentQueueItem
from user_accounts.models import Business, Notification, OperationalAlert, OperationalEvent, ServiceRequest, Ticket
from user_accounts.services.sync_alert_operational_sources import (
    sync_operational_alerts,
    sync_social_failure_alerts,
)


class SyncAlertOperationalSourceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alert-owner",
            email="alert-owner@example.com",
            password="password-123",
        )
        self.other = get_user_model().objects.create_user(
            username="alert-other",
            email="alert-other@example.com",
            password="password-123",
        )

    def test_failed_social_post_becomes_one_owner_scoped_sync_alert(self):
        connection = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            external_account_id="alert-page-1",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.user,
        )
        draft = GrowthContentDraft.objects.create(
            title="Post",
            body="Caption",
            status=GrowthContentDraft.Status.APPROVED,
            created_by=self.user,
        )
        item = GrowthContentQueueItem.objects.create(
            draft=draft,
            channel_connection=connection,
            status=GrowthContentQueueItem.Status.FAILED,
            fail_reason="Meta rejected the publish request.",
            created_by=self.user,
        )

        first = sync_social_failure_alerts()
        second = sync_social_failure_alerts()

        rows = Notification.objects.filter(recipient=self.user, data__source="SOCIAL")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(rows.first().data["payload"]["queue_item_id"], item.id)
        self.assertFalse(Notification.objects.filter(recipient=self.other, data__source="SOCIAL").exists())

    def _ticket(self):
        business = Business.objects.create(owner=self.user, name="Alert Test Business")
        request = ServiceRequest.objects.create(customer=self.other, title="Repair sink", status="NEW")
        ticket = Ticket.objects.create(
            customer=self.other,
            service_request=request,
            assigned_business=business,
            work_title="Repair sink",
            status="SCHEDULED",
        )
        return business, ticket

    def test_existing_operational_alert_is_mirrored_to_same_recipient_only(self):
        business, ticket = self._ticket()
        event = OperationalEvent.objects.create(
            business=business,
            ticket=ticket,
            event_type=OperationalEvent.EventType.DELAY_REPORTED,
            visibility=OperationalEvent.Visibility.BOTH,
            title="Arrival delayed",
            message="Crew is running 25 minutes behind.",
            created_by=self.user,
        )
        source_alert = OperationalAlert.objects.create(
            event=event,
            recipient=self.other,
            audience=OperationalAlert.Audience.CUSTOMER,
            channel=OperationalAlert.Channel.IN_APP,
            status=OperationalAlert.Status.PENDING,
            dedupe_key="ops-alert-source-1",
        )

        first = sync_operational_alerts()
        second = sync_operational_alerts()

        rows = Notification.objects.filter(recipient=self.other, data__code="DELAY_REPORTED")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(rows.first().data["payload"]["operational_alert_id"], source_alert.id)
        self.assertFalse(Notification.objects.filter(recipient=self.user, data__code="DELAY_REPORTED").exists())

    def test_suppressed_operational_alert_is_not_mirrored(self):
        business, ticket = self._ticket()
        event = OperationalEvent.objects.create(
            business=business,
            ticket=ticket,
            event_type=OperationalEvent.EventType.JOB_BLOCKED,
            visibility=OperationalEvent.Visibility.BOTH,
            title="Job blocked",
            message="Waiting on approval.",
            created_by=self.user,
        )
        OperationalAlert.objects.create(
            event=event,
            recipient=self.other,
            audience=OperationalAlert.Audience.CUSTOMER,
            channel=OperationalAlert.Channel.IN_APP,
            status=OperationalAlert.Status.SUPPRESSED,
            dedupe_key="ops-alert-suppressed",
        )

        result = sync_operational_alerts()
        self.assertEqual(result["created"], 0)
        self.assertFalse(Notification.objects.filter(recipient=self.other, data__code="JOB_BLOCKED").exists())
