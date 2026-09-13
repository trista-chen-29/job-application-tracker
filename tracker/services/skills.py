from __future__ import annotations

from tracker.models import Skill
from tracker.services.text import normalize_skill, split_skill_lines


def get_or_create_skill(user, name: str) -> Skill:
    normalized = normalize_skill(name)
    skill, _ = Skill.objects.get_or_create(
        user=user,
        normalized_name=normalized,
        defaults={"name": name.strip()},
    )
    return skill


def replace_track_skills(track, raw: str) -> None:
    names = split_skill_lines(raw)
    track.profile_skills.all().delete()
    for name in names:
        skill = get_or_create_skill(track.profile.user, name)
        track.profile_skills.create(skill=skill)


def replace_opportunity_skills(opportunity, required_raw: str, preferred_raw: str) -> None:
    opportunity.skills.all().delete()
    seen: set[tuple[str, str]] = set()
    for kind, raw in (("required", required_raw), ("preferred", preferred_raw)):
        for name in split_skill_lines(raw):
            normalized = normalize_skill(name)
            key = (normalized, kind)
            if not normalized or key in seen:
                continue
            seen.add(key)
            opportunity.skills.create(name=name.strip(), normalized_name=normalized, kind=kind)
