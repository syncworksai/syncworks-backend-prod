from datetime import datetime

from django.utils import timezone

from user_accounts.models import CustomerSettings

from .connection_store import list_connections
from .sync_service import sync_connection


def sync_due_connections():
    due = 0
    synced = 0
    failed = 0
    now = timezone.now()
    for customer_settings in CustomerSettings.objects.select_related("user").all().iterator():
        for connection in list_connections(customer_settings.user):
            if not connection.get("enabled", True) or connection.get("sync_cadence") == "MANUAL":
                continue
            value = connection.get("next_sync_at")
            if value:
                try:
                    if datetime.fromisoformat(str(value).replace("Z", "+00:00")) > now:
                        continue
                except ValueError:
                    pass
            due += 1
            result = sync_connection(customer_settings.user, connection)
            if result.get("ok"):
                synced += 1
            else:
                failed += 1
    return {"due": due, "synced": synced, "failed": failed}
