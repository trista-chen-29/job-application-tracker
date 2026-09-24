from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from html import unescape
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from tracker.models import SimplifyListing

H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
TABLE_RE = re.compile(r"<table\b.*?</table>", re.I | re.S)
TR_RE = re.compile(r"<tr\b.*?>(.*?)</tr>", re.I | re.S)
TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
HREF_RE = re.compile(r'<a[^>]+href="([^"]+)"', re.I)
TAG_RE = re.compile(r"<[^>]+>")

DEFAULT_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"


@dataclass
class ParsedListing:
    company: str
    title: str
    location: str
    apply_url: str
    category: str
    age_label: str
    age_days: int | None
    listing_key: str


def strip_html(value: str) -> str:
    text = TAG_RE.sub(" ", unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def listing_key(company: str, title: str, apply_url: str) -> str:
    raw = f"{company.lower()}|{title.lower()}|{apply_url.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def parse_age(label: str) -> int | None:
    match = re.search(r"(\d+)\s*(d|mo|w)", (label or "").lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return amount
    if unit == "w":
        return amount * 7
    return amount * 30


def _apply_url(cell: str) -> str:
    urls = HREF_RE.findall(cell)
    for url in urls:
        if "i.imgur.com" in url:
            continue
        if "simplify.jobs/c/" in url:
            continue
        if "simplify.jobs/p/" in url:
            continue
        return unescape(url)
    for url in urls:
        if "i.imgur.com" not in url:
            return unescape(url)
    return ""


SKIP_CATEGORY = ("faq", "legend", "contributor", "see full", "we love", "general")


def parse_listings(html: str) -> list[ParsedListing]:
    chunks = re.split(r"(?=<h2\b)", html, flags=re.I)
    results: list[ParsedListing] = []
    for chunk in chunks:
        heading_match = H2_RE.search(chunk)
        category = strip_html(heading_match.group(1)) if heading_match else ""
        category = re.sub(r"Internship Roles$", "", category).strip()
        if any(part in category.lower() for part in SKIP_CATEGORY):
            continue
        last_company = ""
        for table in TABLE_RE.findall(chunk):
            for row in TR_RE.findall(table):
                cells = TD_RE.findall(row)
                if len(cells) < 5:
                    continue
                if "company" in strip_html(cells[0]).lower() and "role" in strip_html(cells[1]).lower():
                    continue
                company = strip_html(cells[0]).lstrip("↳ ").strip()
                if not company or company == "↳":
                    company = last_company
                else:
                    last_company = company
                title = strip_html(cells[1])
                if not company or not title:
                    continue
                apply_url = _apply_url(cells[3])
                age_label = strip_html(cells[4])
                results.append(
                    ParsedListing(
                        company=company[:200],
                        title=title[:300],
                        location=strip_html(cells[2])[:400],
                        apply_url=apply_url[:1000],
                        category=category[:80],
                        age_label=age_label[:16],
                        age_days=parse_age(age_label),
                        listing_key=listing_key(company, title, apply_url),
                    )
                )
    return results


def fetch_readme(url: str | None = None) -> str:
    target = url or getattr(settings, "SIMPLIFY_README_URL", DEFAULT_README_URL)
    request = Request(target, headers={"User-Agent": "job-application-tracker/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def sync_listings(html: str | None = None) -> dict:
    payload = html if html is not None else fetch_readme()
    parsed = parse_listings(payload)
    now = timezone.now()
    keys = [item.listing_key for item in parsed]
    existing = {item.listing_key: item for item in SimplifyListing.objects.filter(listing_key__in=keys)}
    created = 0
    to_create: list[SimplifyListing] = []
    to_update: list[SimplifyListing] = []
    for item in parsed:
        row = existing.get(item.listing_key)
        if row is None:
            to_create.append(
                SimplifyListing(
                    listing_key=item.listing_key,
                    company=item.company,
                    title=item.title,
                    location=item.location,
                    apply_url=item.apply_url,
                    category=item.category,
                    age_label=item.age_label,
                    age_days=item.age_days,
                    first_seen_at=now,
                    is_active=True,
                )
            )
            created += 1
        else:
            row.company = item.company
            row.title = item.title
            row.location = item.location
            row.apply_url = item.apply_url
            row.category = item.category
            row.age_label = item.age_label
            row.age_days = item.age_days
            row.is_active = True
            to_update.append(row)
    if to_create:
        SimplifyListing.objects.bulk_create(to_create, batch_size=500)
    if to_update:
        SimplifyListing.objects.bulk_update(
            to_update,
            ["company", "title", "location", "apply_url", "category", "age_label", "age_days", "is_active"],
            batch_size=500,
        )
    if keys:
        SimplifyListing.objects.exclude(listing_key__in=keys).filter(is_active=True).update(is_active=False)
    return {"created": created, "total": len(parsed), "synced_at": now}


def new_listing_count(user, last_viewed_at) -> int:
    qs = SimplifyListing.objects.filter(is_active=True)
    if last_viewed_at:
        return qs.filter(first_seen_at__gt=last_viewed_at).count()
    return qs.filter(age_days__lte=1).count()


def should_resync() -> bool:
    latest = SimplifyListing.objects.order_by("-updated_at").first()
    if latest is None:
        return True
    minutes = int(getattr(settings, "SIMPLIFY_SYNC_MINUTES", 30))
    return latest.updated_at < timezone.now() - timedelta(minutes=minutes)
