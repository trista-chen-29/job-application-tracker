from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from tracker.constants import (
    APPLIED_OR_LATER,
    INTERVIEW_OR_LATER,
    OFFER_OR_LATER,
    OpportunityStatus,
    SCREEN_OR_LATER,
)
from tracker.models import Opportunity, Task


def _enough(count: int) -> bool:
    return count >= settings.ANALYTICS_MIN_SAMPLE


def conversion(numerator: int, denominator: int) -> dict:
    if not _enough(denominator):
        return {
            "label": "Not enough data",
            "value": None,
            "numerator": numerator,
            "denominator": denominator,
            "explanation": f"Needs at least {settings.ANALYTICS_MIN_SAMPLE} applications in range; found {denominator}.",
        }
    rate = round(100 * numerator / denominator, 1)
    return {
        "label": f"{rate}%",
        "value": rate,
        "numerator": numerator,
        "denominator": denominator,
        "explanation": f"{numerator} of {denominator} applied opportunities ({rate}%).",
    }


def dashboard_metrics(user, start: date | None = None, end: date | None = None) -> dict:
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    opportunities = Opportunity.objects.filter(user=user, is_archived=False)
    if start:
        opportunities = opportunities.filter(created_at__date__gte=start)
    if end:
        opportunities = opportunities.filter(created_at__date__lte=end)

    by_status = {
        row["status"]: row["total"]
        for row in opportunities.values("status").annotate(total=Count("id"))
    }
    applied_qs = Opportunity.objects.filter(user=user, is_archived=False, status__in=APPLIED_OR_LATER)
    if start:
        applied_qs = applied_qs.filter(application__applied_at__date__gte=start)
    if end:
        applied_qs = applied_qs.filter(application__applied_at__date__lte=end)

    applied_count = applied_qs.count()
    screens = applied_qs.filter(status__in=SCREEN_OR_LATER).count()
    interviews = applied_qs.filter(status__in=INTERVIEW_OR_LATER).count()
    offers = applied_qs.filter(status__in=OFFER_OR_LATER).count()

    overdue_tasks = Task.objects.filter(user=user, completed=False, due_date__lt=today)
    upcoming_interviews = user.opportunities.filter(
        is_archived=False,
        interview_stages__scheduled_at__date__gte=today,
    ).distinct()

    return {
        "by_status": by_status,
        "status_rows": [
            {"value": value, "label": label, "total": by_status.get(value, 0)}
            for value, label in OpportunityStatus.choices
        ],
        "status_labels": OpportunityStatus.choices,
        "applied_this_week": Opportunity.objects.filter(
            user=user,
            application__applied_at__date__gte=week_start,
        ).count(),
        "applied_this_month": Opportunity.objects.filter(
            user=user,
            application__applied_at__date__gte=month_start,
        ).count(),
        "overdue_followups": overdue_tasks.count(),
        "upcoming_interviews": upcoming_interviews.count(),
        "needs_action": Opportunity.objects.filter(
            user=user,
            is_archived=False,
            status__in=[OpportunityStatus.SAVED, OpportunityStatus.RESEARCHING, OpportunityStatus.PREPARING],
        ).count(),
        "strong_unapplied": Opportunity.objects.filter(
            user=user,
            is_archived=False,
            match_category="strong",
        ).exclude(status__in=APPLIED_OR_LATER).count(),
        "response_rate": conversion(screens, applied_count),
        "interview_rate": conversion(interviews, applied_count),
        "offer_rate": conversion(offers, interviews if interviews else applied_count),
        "by_source": list(
            opportunities.values("source").annotate(total=Count("id")).order_by("-total")
        ),
        "by_track": list(
            opportunities.values("selected_track__name").annotate(total=Count("id")).order_by("-total")
        ),
        "by_location": list(
            opportunities.exclude(location="").values("location").annotate(total=Count("id")).order_by("-total")[:8]
        ),
        "by_resume": list(
            user.opportunities.filter(application__material_snapshots__material_type="resume")
            .values("application__material_snapshots__name")
            .annotate(total=Count("id", distinct=True))
            .order_by("-total")
        ),
        "overdue_tasks": overdue_tasks.select_related("opportunity")[:8],
        "next_interviews": user.opportunities.filter(
            interview_stages__scheduled_at__gte=timezone.now()
        )
        .distinct()
        .prefetch_related("interview_stages")[:5],
        "next_deadlines": Opportunity.objects.filter(
            user=user,
            is_archived=False,
            deadline__gte=today,
        ).order_by("deadline")[:6],
        "today": today,
    }


def breakdown_explanation() -> str:
    return (
        "Response rate = screening-or-later / applied. "
        "Interview conversion = interviewing-or-later / applied. "
        "Offer conversion = offer-or-later / interviewing-or-later when interviews exist, otherwise / applied. "
        f"Rates hide when the denominator is below {settings.ANALYTICS_MIN_SAMPLE}."
    )
