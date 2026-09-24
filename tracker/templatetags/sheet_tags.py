from django import template

from tracker.constants import SHEET_STATUS_FROM_FULL, OpportunityStatus

register = template.Library()


@register.filter
def as_sheet_status(status: str) -> str:
    return SHEET_STATUS_FROM_FULL.get(status, OpportunityStatus.SAVED)
