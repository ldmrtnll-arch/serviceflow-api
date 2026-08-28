import random
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.tickets.models import SLAPolicy, Ticket, TicketCategory


class Command(BaseCommand):
    help = "Create non-idempotent ticket volume for local performance testing."

    def add_arguments(self, parser):
        parser.add_argument("--tickets", type=int, default=1000)

    def handle(self, *args, **options):
        total = options["tickets"]
        if not 1 <= total <= 5000:
            raise CommandError("--tickets must be between 1 and 5000.")

        call_command("seed_dev", verbosity=0)
        requesters = list(User.objects.filter(role=User.Role.REQUESTER))
        agents = list(User.objects.filter(role=User.Role.AGENT))
        categories = list(TicketCategory.objects.all())
        policies = {policy.priority: policy for policy in SLAPolicy.objects.filter(is_active=True)}
        priorities = list(Ticket.Priority.values)
        statuses = [Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED]
        now = timezone.now()
        rng = random.Random(42)
        rows = []
        for index in range(total):
            priority = rng.choice(priorities)
            policy = policies[priority]
            status = rng.choice(statuses)
            rows.append(
                Ticket(
                    title=f"Performance ticket {index + 1}",
                    description="Generated locally by seed_perf for query and load testing.",
                    priority=priority,
                    status=status,
                    category=rng.choice(categories),
                    requester=rng.choice(requesters),
                    assignee=rng.choice(agents) if status != Ticket.Status.OPEN else None,
                    first_response_due_at=now + timedelta(minutes=policy.first_response_minutes),
                    resolution_due_at=now + timedelta(minutes=policy.resolution_minutes),
                )
            )
        Ticket.objects.bulk_create(rows, batch_size=500)
        self.stdout.write(self.style.SUCCESS(f"Created {total} performance tickets."))
