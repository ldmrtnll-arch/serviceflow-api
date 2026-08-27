import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def notify_ticket_event(ticket_id: int, event: str) -> None:
    from .models import Ticket

    ticket = Ticket.objects.select_related("requester", "assignee").get(pk=ticket_id)
    logger.info(
        "ticket_notification",
        extra={
            "ticket_public_id": str(ticket.public_id),
            "event": event,
            "requester": ticket.requester.email,
            "assignee": ticket.assignee.email if ticket.assignee else None,
        },
    )
