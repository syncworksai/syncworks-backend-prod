"""Opt-in GameCast launch emails for team fans. Never expose the subscriber list."""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from platform_social.models import GroupFollow
from platform_sports.models import SportsGame
from .emails import frontend_url


def notify_fans_gamecast_live(game):
    if game.status != SportsGame.Status.LIVE or not game.gamecast_enabled:
        return False
    # Exactly one launch announcement per game, even if both the Start and
    # Enable GameCast buttons are clicked in close succession.
    with transaction.atomic():
        changed = SportsGame.objects.filter(
            pk=game.pk, fan_gamecast_notified_at__isnull=True
        ).update(fan_gamecast_notified_at=timezone.now())
        if not changed:
            return False

    email_list = list(dict.fromkeys(
        email.strip().lower()
        for email in GroupFollow.objects.filter(
            group_id=game.team.group_id, gamecast_email_updates=True
        ).values_list("user__email", flat=True)
        if email and email.strip()
    ))
    if not email_list:
        return False
    team_name = game.team.group.name
    url = f"{frontend_url()}/gamecast/{game.gamecast_token}"
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "SyncWorks <no-reply@syncworksapp.com>")
    message = EmailMultiAlternatives(
        subject=f"{team_name} GameCast is live",
        body=(
            f"{team_name} is playing {game.opponent_name}!\n\n"
            f"Watch the live GameCast: {url}\n\n"
            "You subscribed to live game alerts for this team. "
            "To stop them, open your team Fan page in SyncWorks and turn off email updates."
        ),
        from_email=sender,
        to=[],
        bcc=email_list,
    )
    try:
        return bool(message.send(fail_silently=False))
    except Exception:
        # Allow a manager to retry by switching GameCast off and back on after
        # email delivery is repaired; no scoring operation should fail due to SMTP.
        SportsGame.objects.filter(pk=game.pk).update(fan_gamecast_notified_at=None)
        return False
