from __future__ import annotations

from dataclasses import dataclass, field

from tracker.constants import (
    MATCH_WEIGHTS,
    MatchCategory,
    RoleType,
    SponsorshipPreference,
    SponsorshipStatus,
    WorkArrangement,
)
from tracker.models import Opportunity, Profile, ProfileTrack
from tracker.services.text import normalize_skill, tokenize


@dataclass
class ComponentResult:
    key: str
    label: str
    weight: float
    score: float | None
    included: bool
    explanation: str
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    score: float | None
    category: str
    strengths: list[str]
    missing: list[str]
    blockers: list[str]
    uncertain: list[str]
    recommended_track: str
    suggested_keywords: list[str]
    why: str
    components: list[ComponentResult]

    def as_payload(self) -> dict:
        return {
            "score": self.score,
            "category": self.category,
            "strengths": self.strengths,
            "missing": self.missing,
            "blockers": self.blockers,
            "uncertain": self.uncertain,
            "recommended_track": self.recommended_track,
            "suggested_keywords": self.suggested_keywords,
            "why": self.why,
            "components": [
                {
                    "key": item.key,
                    "label": item.label,
                    "weight": item.weight,
                    "score": item.score,
                    "included": item.included,
                    "explanation": item.explanation,
                    "matched": item.matched,
                    "missing": item.missing,
                }
                for item in self.components
            ],
        }


def _skill_names(track: ProfileTrack | None) -> set[str]:
    if not track:
        return set()
    return {link.skill.normalized_name for link in track.profile_skills.select_related("skill")}


def _overlap(needed: list[str], have: set[str]) -> tuple[list[str], list[str], float]:
    if not needed:
        return [], [], 1.0
    matched = []
    missing = []
    for name in needed:
        normalized = normalize_skill(name)
        if not normalized:
            continue
        if normalized in have or any(normalized in item or item in normalized for item in have):
            matched.append(name)
        else:
            missing.append(name)
    total = len(matched) + len(missing)
    if total == 0:
        return matched, missing, 1.0
    return matched, missing, len(matched) / total


def _role_alignment(opportunity: Opportunity, profile: Profile, track: ProfileTrack | None) -> tuple[float, str, list[str]]:
    haystack = tokenize(opportunity.title) | tokenize(opportunity.get_role_type_display())
    needles: set[str] = set()
    matched_terms: list[str] = []
    if track:
        needles |= tokenize(track.name)
        for keyword in track.keyword_list():
            needles |= tokenize(keyword)
    for category in profile.category_list():
        needles |= tokenize(category)
    if not needles:
        return 0.5, "No role categories or track keywords are set, so alignment is uncertain.", []
    overlap = haystack & needles
    if overlap:
        matched_terms = sorted(overlap)
        return min(1.0, 0.55 + 0.15 * len(overlap)), "Title and track keywords overlap.", matched_terms
    if opportunity.role_type in {RoleType.INTERNSHIP, RoleType.COOP, RoleType.NEW_GRAD}:
        return 0.45, "Role type is plausible, but the title does not overlap track keywords.", []
    return 0.25, "Little overlap between the job title and the selected track.", []


def _education_experience(opportunity: Opportunity, profile: Profile) -> tuple[float, str, list[str]]:
    notes: list[str] = []
    score = 0.7
    blob = " ".join(
        [
            opportunity.description or "",
            opportunity.degree_requirements or "",
            opportunity.experience_requirements or "",
        ]
    ).lower()
    if profile.major and profile.major.lower() in blob:
        score += 0.2
        notes.append(f"Major '{profile.major}' appears in the posting.")
    if profile.degree and profile.degree.lower() in blob:
        score += 0.1
        notes.append(f"Degree '{profile.degree}' appears in the posting.")
    if "phd" in blob and profile.degree.lower().find("ph") == -1:
        return 0.2, "Posting appears to require a PhD, which may not match the profile.", ["Possible degree mismatch"]
    if opportunity.role_type == RoleType.INTERNSHIP:
        score = max(score, 0.8)
        notes.append("Internship role type is compatible with a student/early-career profile.")
    return min(score, 1.0), " ".join(notes) or "Education and experience requirements were not specific.", []


def _location_score(opportunity: Opportunity, profile: Profile) -> tuple[float | None, str]:
    if opportunity.work_arrangement == WorkArrangement.UNKNOWN and not opportunity.location:
        return None, "Location and work arrangement are unknown."
    if opportunity.work_arrangement == WorkArrangement.REMOTE:
        if profile.work_arrangement_preference in {WorkArrangement.REMOTE, WorkArrangement.HYBRID, WorkArrangement.UNKNOWN}:
            return 1.0, "Remote role is compatible with the profile preference."
        return 0.6, "Remote role; profile prefers on-site or hybrid."
    preferred = {item.lower() for item in profile.location_list()}
    job_loc = (opportunity.location or "").lower()
    if preferred and job_loc and any(item in job_loc or job_loc in item for item in preferred):
        return 1.0, "Job location overlaps a preferred location."
    if preferred and job_loc:
        return 0.35, "Job location does not overlap listed preferred locations."
    return 0.6, "Location comparison is incomplete."


def _sponsorship_score(opportunity: Opportunity, profile: Profile) -> tuple[float | None, str, list[str], list[str]]:
    blockers: list[str] = []
    uncertain: list[str] = []
    if opportunity.sponsorship_status == SponsorshipStatus.UNKNOWN:
        uncertain.append("Sponsorship is unknown; it was left out of the score.")
        return None, "Unknown sponsorship is not treated as positive or negative.", blockers, uncertain
    needs = profile.sponsorship_preference in {
        SponsorshipPreference.REQUIRED,
        SponsorshipPreference.PREFERRED,
    } or profile.work_authorization == "needs_sponsorship"
    if not needs:
        return 1.0, "Profile does not require sponsorship.", blockers, uncertain
    if opportunity.sponsorship_status == SponsorshipStatus.NOT_AVAILABLE:
        blockers.append("You need sponsorship, and this posting is marked as not available.")
        return 0.0, "Sponsorship looks like a blocker based on user-recorded data.", blockers, uncertain
    if opportunity.sponsorship_status == SponsorshipStatus.USER_VERIFIED:
        return 1.0, "You verified that sponsorship information is acceptable.", blockers, uncertain
    return 0.7, "Sponsorship appears available but is not user-verified.", blockers, uncertain


def score_opportunity(opportunity: Opportunity, profile: Profile | None = None, track: ProfileTrack | None = None) -> MatchResult:
    profile = profile or getattr(opportunity.user, "profile", None)
    track = track or opportunity.selected_track
    if track is None and profile:
        track = profile.tracks.filter(is_default=True).first() or profile.tracks.first()

    if not profile:
        result = MatchResult(
            score=None,
            category=MatchCategory.UNKNOWN,
            strengths=[],
            missing=[],
            blockers=[],
            uncertain=["Create a profile before matching."],
            recommended_track="",
            suggested_keywords=[],
            why="A profile is required to compare this job to your background.",
            components=[],
        )
        return result

    have = _skill_names(track)
    required = [item.name for item in opportunity.skills.filter(kind="required")]
    preferred = [item.name for item in opportunity.skills.filter(kind="preferred")]
    req_matched, req_missing, req_score = _overlap(required, have)
    pref_matched, pref_missing, pref_score = _overlap(preferred, have)
    role_score, role_expl, role_terms = _role_alignment(opportunity, profile, track)
    edu_score, edu_expl, edu_blockers = _education_experience(opportunity, profile)
    loc_score, loc_expl = _location_score(opportunity, profile)
    spons_score, spons_expl, spons_blockers, spons_uncertain = _sponsorship_score(opportunity, profile)

    components = [
        ComponentResult(
            "required_skills",
            "Required skills",
            MATCH_WEIGHTS["required_skills"],
            req_score if required else None,
            bool(required),
            "No required skills were listed." if not required else f"{len(req_matched)} of {len(required)} required skills overlap the selected track.",
            req_matched,
            req_missing,
        ),
        ComponentResult("role_alignment", "Role / category alignment", MATCH_WEIGHTS["role_alignment"], role_score, True, role_expl, role_terms, []),
        ComponentResult("education_experience", "Education and experience", MATCH_WEIGHTS["education_experience"], edu_score, True, edu_expl, [], edu_blockers),
        ComponentResult(
            "location",
            "Location / work arrangement",
            MATCH_WEIGHTS["location"],
            loc_score,
            loc_score is not None,
            loc_expl,
        ),
        ComponentResult(
            "sponsorship",
            "Work authorization / sponsorship",
            MATCH_WEIGHTS["sponsorship"],
            spons_score,
            spons_score is not None,
            spons_expl,
        ),
        ComponentResult(
            "preferred_skills",
            "Preferred skills",
            MATCH_WEIGHTS["preferred_skills"],
            pref_score if preferred else None,
            bool(preferred),
            "No preferred skills were listed." if not preferred else f"{len(pref_matched)} of {len(preferred)} preferred skills overlap.",
            pref_matched,
            pref_missing,
        ),
    ]

    included = [item for item in components if item.included and item.score is not None]
    weight_total = sum(item.weight for item in included) or 1.0
    overall = sum((item.score or 0) * item.weight for item in included) / weight_total

    blockers = list(spons_blockers) + list(edu_blockers)
    if req_missing:
        blockers = blockers  # missing required skills are gaps, not hard blockers unless many
    uncertain = list(spons_uncertain)
    if not required:
        uncertain.append("Required skills were not listed on the opportunity.")
    if loc_score is None:
        uncertain.append("Location was unknown and omitted from the score.")

    strengths = []
    if req_matched:
        strengths.append("Matching required skills: " + ", ".join(req_matched[:8]))
    if pref_matched:
        strengths.append("Matching preferred skills: " + ", ".join(pref_matched[:6]))
    if role_terms:
        strengths.append("Role keywords: " + ", ".join(role_terms[:6]))
    if edu_score >= 0.8:
        strengths.append(edu_expl)

    missing = [f"Required: {name}" for name in req_missing] + [f"Preferred: {name}" for name in pref_missing]

    if blockers and overall < 0.5:
        category = MatchCategory.WEAK
    elif overall >= 0.7 and not blockers:
        category = MatchCategory.STRONG
    elif overall >= 0.4:
        category = MatchCategory.POSSIBLE
    else:
        category = MatchCategory.WEAK

    suggested = []
    for name in req_missing + pref_missing:
        normalized = normalize_skill(name)
        evidence = []
        for project in profile.projects.all():
            blob = f"{project.name} {project.technologies} {project.description}".lower()
            if normalized and normalized in blob:
                evidence.append(project.name)
        if evidence:
            suggested.append(f"{name} (from {evidence[0]})")
        elif name in req_missing[:5]:
            suggested.append(name)

    recommended = track.name if track else "Add a profile track"
    percent = round(overall * 100)
    why = (
        f"This is a {category} match ({percent}/100) against the '{recommended}' track. "
        "The score is guidance from weighted overlap, not a hiring probability. "
        + (" ".join(uncertain) if uncertain else "")
    )
    return MatchResult(
        score=round(overall, 4),
        category=category,
        strengths=strengths,
        missing=missing,
        blockers=blockers,
        uncertain=uncertain,
        recommended_track=recommended,
        suggested_keywords=suggested[:8],
        why=why.strip(),
        components=components,
    )


def refresh_match(opportunity: Opportunity) -> MatchResult:
    profile = getattr(opportunity.user, "profile", None)
    result = score_opportunity(opportunity, profile, opportunity.selected_track)
    opportunity.match_score = None if result.score is None else round(result.score * 100, 0)
    opportunity.match_category = result.category
    opportunity.match_payload = result.as_payload()
    opportunity.save(update_fields=["match_score", "match_category", "match_payload", "updated_at"])
    return result
