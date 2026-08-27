from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.tickets.models import TicketCategory


class Command(BaseCommand):
    help = "Create idempotent local development users and categories."

    def handle(self, *args, **options):
        users = (
            ("admin@serviceflow.local", User.Role.ADMIN, True),
            ("agent@serviceflow.local", User.Role.AGENT, False),
            ("requester@serviceflow.local", User.Role.REQUESTER, False),
        )
        for email, role, is_staff in users:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": role.title(),
                    "last_name": "User",
                    "role": role,
                    "is_staff": is_staff,
                    "is_superuser": role == User.Role.ADMIN,
                },
            )
            if created:
                user.set_password("ServiceFlow123!")
                user.save(update_fields=["password"])

        for name in ("Software", "Hardware", "Access", "Network", "Other"):
            TicketCategory.objects.get_or_create(
                slug=name.lower(), defaults={"name": name, "description": f"{name} requests"}
            )
        self.stdout.write(self.style.SUCCESS("Development data is ready."))
