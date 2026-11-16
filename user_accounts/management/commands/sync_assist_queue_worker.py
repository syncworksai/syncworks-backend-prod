"""Register the durable queue worker through Django\'s installed app."""
from sync_ai.management.commands.sync_assist_queue_worker import Command  # noqa: F401
