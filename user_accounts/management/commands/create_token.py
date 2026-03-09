from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token
from user_accounts.models import User


class Command(BaseCommand):
    help = "Create (or fetch) a DRF token for a user by email."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)

    def handle(self, *args, **kwargs):
        email = kwargs["email"].lower()
        user = User.objects.filter(email=email).first()
        if not user:
            self.stderr.write(f"User not found: {email}")
            return
        token, _ = Token.objects.get_or_create(user=user)
        self.stdout.write(token.key)
