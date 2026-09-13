from __future__ import annotations

import csv
import io
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from tracker.constants import OpportunityStatus, Source
from tracker.models import (
    Contact,
    ContactInteraction,
    InterviewNote,
    InterviewStage,
    Opportunity,
    StatusHistory,
    Task,
)


def opportunities_csv(user) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "title",
            "company",
            "url",
            "status",
            "priority",
            "source",
            "location",
            "work_arrangement",
            "role_type",
            "deadline",
            "match_category",
            "match_score",
            "track",
            "sponsorship_status",
            "created_at",
        ]
    )
    for opp in Opportunity.objects.filter(user=user).select_related("selected_track"):
        writer.writerow(
            [
                opp.title,
                opp.company,
                opp.url,
                opp.status,
                opp.priority,
                opp.source,
                opp.location,
                opp.work_arrangement,
                opp.role_type,
                opp.deadline,
                opp.match_category,
                opp.match_score,
                opp.selected_track.name if opp.selected_track else "",
                opp.sponsorship_status,
                opp.created_at,
            ]
        )
    return buffer.getvalue()


def contacts_csv(user) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["name", "organization", "role_title", "relationship", "opportunity", "next_follow_up", "referral_status"]
    )
    for contact in Contact.objects.filter(user=user).select_related("opportunity"):
        writer.writerow(
            [
                contact.name,
                contact.organization,
                contact.role_title,
                contact.relationship,
                contact.opportunity.title if contact.opportunity else "",
                contact.next_follow_up,
                contact.referral_status,
            ]
        )
    return buffer.getvalue()


def tasks_csv(user) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["title", "due_date", "priority", "type", "completed", "opportunity"])
    for task in Task.objects.filter(user=user).select_related("opportunity"):
        writer.writerow(
            [
                task.title,
                task.due_date,
                task.priority,
                task.task_type,
                task.completed,
                task.opportunity.title if task.opportunity else "",
            ]
        )
    return buffer.getvalue()


def status_history_csv(user) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["opportunity", "company", "from_status", "to_status", "changed_at", "note"])
    history = StatusHistory.objects.filter(opportunity__user=user).select_related("opportunity")
    for row in history:
        writer.writerow(
            [
                row.opportunity.title,
                row.opportunity.company,
                row.from_status,
                row.to_status,
                row.changed_at,
                row.note,
            ]
        )
    return buffer.getvalue()


def full_json(user) -> str:
    payload = {
        "exported_at": timezone.now().isoformat(),
        "user": user.username,
        "opportunities": list(
            Opportunity.objects.filter(user=user).values(
                "id",
                "title",
                "company",
                "url",
                "status",
                "description",
                "notes",
                "match_payload",
            )
        ),
        "contacts": list(Contact.objects.filter(user=user).values()),
        "tasks": list(Task.objects.filter(user=user).values()),
        "interactions": list(ContactInteraction.objects.filter(contact__user=user).values()),
        "interviews": list(InterviewStage.objects.filter(opportunity__user=user).values()),
        "interview_notes": list(InterviewNote.objects.filter(stage__opportunity__user=user).values()),
    }
    return json.dumps(payload, cls=DjangoJSONEncoder, indent=2)


def preparation_markdown(opportunity: Opportunity) -> str:
    match = opportunity.match_payload or {}
    lines = [
        f"# {opportunity.title} at {opportunity.company}",
        "",
        f"- Status: {opportunity.get_status_display()}",
        f"- URL: {opportunity.url or 'n/a'}",
        f"- Location: {opportunity.location or 'n/a'} ({opportunity.get_work_arrangement_display()})",
        f"- Deadline: {opportunity.deadline or 'n/a'}",
        f"- Track: {opportunity.selected_track.name if opportunity.selected_track else 'n/a'}",
        f"- Match: {opportunity.get_match_category_display()} ({opportunity.match_score if opportunity.match_score is not None else 'n/a'})",
        "",
        "## Why this match",
        match.get("why", "Not scored yet."),
        "",
        "## Strengths",
    ]
    for item in match.get("strengths") or ["None recorded."]:
        lines.append(f"- {item}")
    lines += ["", "## Gaps"]
    for item in match.get("missing") or ["None recorded."]:
        lines.append(f"- {item}")
    lines += ["", "## Job description", opportunity.description or "_No description saved._", "", "## Checklist"]
    for item in opportunity.checklist_items.all():
        mark = "x" if item.completed else " "
        lines.append(f"- [{mark}] {item.label}")
    return "\n".join(lines) + "\n"


def import_opportunities_csv(user, file) -> tuple[int, list[str]]:
    text = file.read()
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    errors: list[str] = []
    valid_status = {choice[0] for choice in OpportunityStatus.choices}
    for index, row in enumerate(reader, start=2):
        title = (row.get("title") or row.get("Title") or "").strip()
        company = (row.get("company") or row.get("Company") or "").strip()
        if not title or not company:
            errors.append(f"Row {index}: title and company are required.")
            continue
        status = (row.get("status") or row.get("Status") or OpportunityStatus.SAVED).strip().lower().replace(" ", "_")
        if status not in valid_status:
            status = OpportunityStatus.SAVED
        source = (row.get("source") or "other").strip().lower().replace(" ", "_")
        if source not in {choice[0] for choice in Source.choices}:
            source = "other"
        Opportunity.objects.create(
            user=user,
            title=title,
            company=company,
            url=(row.get("url") or row.get("URL") or "").strip(),
            location=(row.get("location") or "").strip(),
            source=source,
            description=(row.get("description") or "").strip(),
            status=status,
        )
        created += 1
    return created, errors
