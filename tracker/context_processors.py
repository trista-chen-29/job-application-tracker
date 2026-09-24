from django.utils import timezone

from tracker.constants import OpportunityStatus
from tracker.models import GmailAccount, Task
from tracker.services.gmail import gmail_configured
from tracker.services.simplify import new_listing_count


def nav_counts(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    today = timezone.localdate()
    profile = getattr(user, "profile", None)
    last_viewed = profile.openings_last_viewed_at if profile else None
    try:
        new_openings = new_listing_count(user, last_viewed)
    except Exception:
        new_openings = 0
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
        "nav_new_openings": new_openings,
        "gmail_connected": GmailAccount.objects.filter(user=user).exists(),
        "gmail_ready": gmail_configured(),
    }
