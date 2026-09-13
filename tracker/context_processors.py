from django.utils import timezone

from tracker.constants import OpportunityStatus
from tracker.models import Task


def nav_counts(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    today = timezone.localdate()
    return {
        "nav_overdue": Task.objects.filter(user=user, completed=False, due_date__lt=today).count(),
        "nav_active": user.opportunities.filter(is_archived=False)
        .exclude(
            status__in=[
                OpportunityStatus.REJECTED,
                OpportunityStatus.WITHDRAWN,
                OpportunityStatus.CLOSED,
                OpportunityStatus.ACCEPTED,
            ]
        )
        .count(),
    }
