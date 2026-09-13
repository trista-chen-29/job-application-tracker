from __future__ import annotations

from difflib import SequenceMatcher

from django.db.models import Q

from tracker.models import Opportunity
from tracker.services.text import normalize_skill


def find_duplicates(user, *, title: str, company: str, url: str, description: str, exclude_id: int | None = None) -> list[Opportunity]:
    qs = Opportunity.objects.filter(user=user, is_archived=False)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)

    matches: dict[int, Opportunity] = {}
    if url:
        for opp in qs.filter(url=url):
            matches[opp.pk] = opp

    company_norm = normalize_skill(company)
    title_norm = normalize_skill(title)
    if company_norm and title_norm:
        for opp in qs.filter(Q(company__icontains=company) | Q(title__icontains=title)):
            if normalize_skill(opp.company) == company_norm and normalize_skill(opp.title) == title_norm:
                matches[opp.pk] = opp

    if description and len(description) > 80:
        for opp in qs.exclude(description=""):
            if opp.pk in matches:
                continue
            ratio = SequenceMatcher(None, description[:4000], opp.description[:4000]).ratio()
            if ratio >= 0.86:
                matches[opp.pk] = opp
    return list(matches.values())
