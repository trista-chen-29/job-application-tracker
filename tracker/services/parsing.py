from __future__ import annotations

import re
from datetime import date, datetime

from tracker.constants import SponsorshipStatus, WorkArrangement

DEADLINE_RE = re.compile(
    r"(?:apply by|deadline|closes? on|applications? due)\s*[:\-]?\s*"
    r"([A-Za-z]{3,9}\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.I,
)


def parse_deadline(description: str) -> date | None:
    match = DEADLINE_RE.search(description or "")
    if not match:
        return None
    raw = match.group(1)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d", "%b %d", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=date.today().year)
            return parsed.date()
        except ValueError:
            continue
    return None


def infer_work_arrangement(text: str) -> str:
    lowered = (text or "").lower()
    if "remote" in lowered:
        return WorkArrangement.REMOTE
    if "hybrid" in lowered:
        return WorkArrangement.HYBRID
    if "on-site" in lowered or "onsite" in lowered or "on site" in lowered:
        return WorkArrangement.ONSITE
    return WorkArrangement.UNKNOWN


def infer_sponsorship(text: str) -> str:
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in ("does not sponsor", "no sponsorship", "not offer sponsorship", "unable to sponsor")):
        return SponsorshipStatus.NOT_AVAILABLE
    if any(phrase in lowered for phrase in ("sponsorship available", "will sponsor", "h1b", "h-1b", "visa sponsorship")):
        return SponsorshipStatus.APPEARS_AVAILABLE
    return SponsorshipStatus.UNKNOWN


def extract_skill_section(description: str, heading_words: tuple[str, ...]) -> list[str]:
    if not description:
        return []
    lines = description.splitlines()
    capturing = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower().rstrip(":")
        if any(lowered.startswith(word) for word in heading_words):
            capturing = True
            remainder = stripped.split(":", 1)[-1].strip() if ":" in stripped else ""
            if remainder:
                collected.append(remainder)
            continue
        if capturing and stripped and not stripped.endswith(":") and len(stripped) < 80 and stripped[0].isalpha() and " " not in stripped[:20] and stripped.endswith(":"):
            capturing = False
            continue
        if capturing and stripped.startswith(("#", "##")):
            capturing = False
            continue
        if capturing and stripped:
            if stripped[0] in "-•*" or stripped[:2].isdigit():
                collected.append(re.sub(r"^[\-•*\d.\)\s]+", "", stripped))
            elif len(collected) < 12:
                collected.append(stripped)
        elif capturing and not stripped:
            capturing = False
    return [item for item in collected if 1 < len(item) < 80]
