from __future__ import annotations

from django.utils import timezone

from tracker.constants import APPLIED_OR_LATER, OpportunityStatus
from tracker.models import Application, ApplicationMaterialSnapshot, Opportunity, StatusHistory, ensure_default_checklist
from tracker.services.matching import refresh_match
from tracker.services.parsing import infer_sponsorship, infer_work_arrangement, parse_deadline
from tracker.services.skills import replace_opportunity_skills


def change_status(opportunity: Opportunity, new_status: str, note: str = "") -> None:
    if new_status == opportunity.status:
        return
    StatusHistory.objects.create(
        opportunity=opportunity,
        from_status=opportunity.status,
        to_status=new_status,
        note=note,
    )
    opportunity.status = new_status
    opportunity.last_status_changed_at = timezone.now()
    opportunity.save(update_fields=["status", "last_status_changed_at", "updated_at"])
    if new_status in APPLIED_OR_LATER:
        application, _ = Application.objects.get_or_create(opportunity=opportunity)
        if application.applied_at is None:
            application.applied_at = timezone.now()
            application.save(update_fields=["applied_at"])


def snapshot_materials(opportunity: Opportunity, material_ids: list[int]) -> None:
    application, _ = Application.objects.get_or_create(opportunity=opportunity)
    application.material_snapshots.all().delete()
    materials = opportunity.user.materials.filter(pk__in=material_ids)
    for material in materials:
        ApplicationMaterialSnapshot.objects.create(
            application=application,
            material=material,
            name=material.name,
            material_type=material.material_type,
            notes=material.notes,
            file_name=material.file.name if material.file else "",
            link=material.link,
        )


def initialize_opportunity(opportunity: Opportunity, required_skills: str = "", preferred_skills: str = "") -> None:
    ensure_default_checklist(opportunity)
    if not opportunity.work_arrangement or opportunity.work_arrangement == "unknown":
        opportunity.work_arrangement = infer_work_arrangement(
            f"{opportunity.description} {opportunity.location}"
        )
    if opportunity.sponsorship_status == "unknown":
        inferred = infer_sponsorship(opportunity.description)
        opportunity.sponsorship_status = inferred
    if opportunity.deadline is None:
        opportunity.deadline = parse_deadline(opportunity.description)
    opportunity.save()
    if required_skills or preferred_skills:
        replace_opportunity_skills(opportunity, required_skills, preferred_skills)
    elif opportunity.description:
        from tracker.services.parsing import extract_skill_section

        required = extract_skill_section(
            opportunity.description,
            ("requirements", "required", "must have", "basic qualifications", "minimum qualifications"),
        )
        preferred = extract_skill_section(
            opportunity.description,
            ("preferred", "nice to have", "bonus", "preferred qualifications"),
        )
        replace_opportunity_skills(opportunity, "\n".join(required), "\n".join(preferred))
    StatusHistory.objects.create(
        opportunity=opportunity,
        from_status="",
        to_status=opportunity.status or OpportunityStatus.SAVED,
        note="Created",
    )
    refresh_match(opportunity)


def duplicate_opportunity(opportunity: Opportunity) -> Opportunity:
    skills = list(opportunity.skills.all())
    clone = Opportunity.objects.get(pk=opportunity.pk)
    clone.pk = None
    clone.id = None
    clone.title = f"{opportunity.title} (copy)"
    clone.status = OpportunityStatus.SAVED
    clone.is_archived = False
    clone.match_payload = {}
    clone.match_score = None
    clone.save()
    for skill in skills:
        clone.skills.create(name=skill.name, normalized_name=skill.normalized_name, kind=skill.kind)
    ensure_default_checklist(clone)
    StatusHistory.objects.create(
        opportunity=clone,
        from_status="",
        to_status=clone.status,
        note="Duplicated",
    )
    refresh_match(clone)
    return clone
