from celery import shared_task
from django.utils import timezone

from .models import Task


@shared_task
def find_overdue_tasks():
    """Report tasks past their due date that are not completed.

    Read-only: uses the same overdue rule as the dashboard and changes no records.
    """
    today = timezone.localdate()
    overdue = (
        Task.objects
        .filter(due_date__lt=today)
        .exclude(status='COMPLETED')
        .order_by('due_date', 'id')
    )
    overdue_ids = list(overdue.values_list('id', flat=True))
    return {
        'checked_on': today.isoformat(),
        'overdue_count': len(overdue_ids),
        'overdue_task_ids': overdue_ids,
    }
