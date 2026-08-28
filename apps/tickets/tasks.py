import logging

from celery import shared_task
from django.db import OperationalError

logger = logging.getLogger(__name__)


@shared_task(
    ignore_result=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def notify_ticket_event(ticket_id: int, event: str) -> None:
    from .models import Ticket

    ticket = Ticket.objects.select_related("requester", "assignee").get(pk=ticket_id)
    logger.info(
        "ticket_notification event=%s ticket_id=%s",
        event,
        ticket.public_id,
        extra={
            "ticket_public_id": str(ticket.public_id),
            "ticket_event": event,
            "requester": ticket.requester.email,
            "assignee": ticket.assignee.email if ticket.assignee else None,
        },
    )


@shared_task(
    ignore_result=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def check_sla_breaches() -> dict[str, int]:
    from .sla import check_all_sla_breaches

    return check_all_sla_breaches()
