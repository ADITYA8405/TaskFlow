from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import OperationalError
from django.utils import timezone

from .models import Task

logger = get_task_logger(__name__)


@shared_task(
    # Retry only database connection failures (e.g. PostgreSQL restarting).
    # Programming errors fail immediately instead of being retried.
    autoretry_for=(OperationalError,),
    # At most 6 attempts in total; then the task ends in FAILURE.
    max_retries=5,
    # Waits double from 2s (2, 4, 8, 16, 32; about a minute at most), capped at
    # 60s each, and are randomised so retries do not all arrive at once.
    retry_backoff=2,
    retry_backoff_max=60,
    retry_jitter=True,
    # Acknowledge the message after the task finishes, so a task interrupted by
    # the whole worker stopping is redelivered rather than lost. Safe because the
    # task is read-only. reject_on_worker_lost is deliberately not set: a crashing
    # child process records FAILURE instead of being redelivered without limit.
    acks_late=True,
    # Report STARTED while running, so running is distinguishable from queued.
    track_started=True,
    # Stop a hung run: an exception after 30s, the process is killed after 60s.
    soft_time_limit=30,
    time_limit=60,
)
def find_overdue_tasks():
    """Report tasks past their due date that are not completed.

    Read-only: uses the same overdue rule as the dashboard and changes no records.
    That makes it idempotent, so retries and redelivery are safe; each run reports
    the state at the time it succeeds.
    """
    today = timezone.localdate()
    overdue = (
        Task.objects
        .filter(due_date__lt=today)
        .exclude(status='COMPLETED')
        .order_by('due_date', 'id')
    )
    overdue_ids = list(overdue.values_list('id', flat=True))
    logger.info('Found %d overdue task(s) on %s', len(overdue_ids), today.isoformat())
    return {
        'checked_on': today.isoformat(),
        'overdue_count': len(overdue_ids),
        'overdue_task_ids': overdue_ids,
    }
