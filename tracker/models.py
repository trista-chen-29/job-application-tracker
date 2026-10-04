from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from tracker.constants import (
    DEFAULT_CHECKLIST,
    InterviewNoteType,
    MatchCategory,
    MaterialType,
    OpportunityStatus,
    Priority,
    ReferralStatus,
    Relationship,
    RoleType,
    SkillKind,
    Source,
    SponsorshipPreference,
    SponsorshipStatus,
    TaskPriority,
    TaskType,
    WorkArrangement,
    WorkAuthorization,
)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Profile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    linkedin_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    website_url = models.URLField(blank=True)
    school = models.CharField(max_length=200, blank=True)
    degree = models.CharField(max_length=120, blank=True)
    major = models.CharField(max_length=120, blank=True)
    graduation_date = models.DateField(null=True, blank=True)
    preferred_role_categories = models.CharField(
        max_length=400,
        blank=True,
        help_text="Comma-separated role categories, e.g. Software, Embedded/Systems",
    )
    preferred_locations = models.CharField(max_length=400, blank=True)
    work_arrangement_preference = models.CharField(
        max_length=20,
        choices=WorkArrangement.choices,
        default=WorkArrangement.UNKNOWN,
    )
    work_authorization = models.CharField(
        max_length=32,
        choices=WorkAuthorization.choices,
        default=WorkAuthorization.OTHER,
    )
    sponsorship_preference = models.CharField(
        max_length=20,
        choices=SponsorshipPreference.choices,
        default=SponsorshipPreference.NOT_NEEDED,
    )
    professional_pitch = models.TextField(blank=True)
    openings_last_viewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.full_name or self.user.get_username()

    def category_list(self) -> list[str]:
        return [part.strip() for part in self.preferred_role_categories.split(",") if part.strip()]

    def location_list(self) -> list[str]:
        return [part.strip() for part in self.preferred_locations.split(",") if part.strip()]


class ProfileTrack(TimeStampedModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="tracks")
    name = models.CharField(max_length=120)
    keywords = models.TextField(blank=True, help_text="Comma or newline separated keywords")
    pitch = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "name"], name="unique_track_name_per_profile"),
        ]

    def __str__(self) -> str:
        return self.name

    def keyword_list(self) -> list[str]:
        raw = self.keywords.replace("\n", ",")
        return [part.strip() for part in raw.split(",") if part.strip()]


class Skill(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="skills")
    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "normalized_name"], name="unique_skill_per_user"),
        ]

    def __str__(self) -> str:
        return self.name


class ProfileSkill(TimeStampedModel):
    track = models.ForeignKey(ProfileTrack, on_delete=models.CASCADE, related_name="profile_skills")
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="profile_links")
    proficiency = models.CharField(max_length=80, blank=True)
    evidence_notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["track", "skill"], name="unique_skill_per_track"),
        ]


class Experience(TimeStampedModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="experiences")
    title = models.CharField(max_length=200)
    organization = models.CharField(max_length=200, blank=True)
    experience_type = models.CharField(
        max_length=32,
        default="work",
        help_text="work, coursework, certification, or achievement",
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date", "-id"]


class Project(TimeStampedModel):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    technologies = models.CharField(max_length=400, blank=True)
    description = models.TextField(blank=True)
    highlights = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]


def material_upload_to(instance: ApplicationMaterial, filename: str) -> str:
    return f"materials/user_{instance.user_id}/{filename}"


class ApplicationMaterial(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="materials")
    name = models.CharField(max_length=200)
    material_type = models.CharField(max_length=32, choices=MaterialType.choices)
    track = models.ForeignKey(
        ProfileTrack,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="materials",
    )
    file = models.FileField(upload_to=material_upload_to, blank=True)
    link = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.file and self.file.size and self.file.size > settings.MAX_UPLOAD_BYTES:
            raise ValidationError({"file": "File must be 5 MB or smaller."})
        if self.file:
            suffix = "." + self.file.name.rsplit(".", 1)[-1].lower() if "." in self.file.name else ""
            if suffix not in settings.ALLOWED_MATERIAL_EXTENSIONS:
                raise ValidationError({"file": "Unsupported file type."})

    def __str__(self) -> str:
        return self.name


class Opportunity(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opportunities")
    title = models.CharField(max_length=300)
    company = models.CharField(max_length=200)
    url = models.URLField(max_length=1000, blank=True)
    source = models.CharField(max_length=32, choices=Source.choices, default=Source.OTHER)
    location = models.CharField(max_length=200, blank=True)
    work_arrangement = models.CharField(
        max_length=20,
        choices=WorkArrangement.choices,
        default=WorkArrangement.UNKNOWN,
    )
    role_type = models.CharField(max_length=20, choices=RoleType.choices, default=RoleType.INTERNSHIP)
    posting_date = models.DateField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    degree_requirements = models.TextField(blank=True)
    experience_requirements = models.TextField(blank=True)
    sponsorship_status = models.CharField(
        max_length=32,
        choices=SponsorshipStatus.choices,
        default=SponsorshipStatus.UNKNOWN,
    )
    salary = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=32,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.SAVED,
    )
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    priority_override_reason = models.CharField(max_length=300, blank=True)
    selected_track = models.ForeignKey(
        ProfileTrack,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opportunities",
    )
    is_archived = models.BooleanField(default=False)
    match_score = models.FloatField(null=True, blank=True)
    match_category = models.CharField(
        max_length=16,
        choices=MatchCategory.choices,
        default=MatchCategory.UNKNOWN,
    )
    match_payload = models.JSONField(default=dict, blank=True)
    last_status_changed_at = models.DateTimeField(default=timezone.now)
    simplify_key = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.title} · {self.company}"


class OpportunitySkill(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="skills")
    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=SkillKind.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "normalized_name", "kind"],
                name="unique_opp_skill_kind",
            ),
        ]


class Application(TimeStampedModel):
    opportunity = models.OneToOneField(Opportunity, on_delete=models.CASCADE, related_name="application")
    applied_at = models.DateTimeField(null=True, blank=True)
    confirmation_number = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)


class ApplicationMaterialSnapshot(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="material_snapshots")
    material = models.ForeignKey(
        ApplicationMaterial,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="snapshots",
    )
    name = models.CharField(max_length=200)
    material_type = models.CharField(max_length=32)
    notes = models.TextField(blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    link = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class StatusHistory(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32, choices=OpportunityStatus.choices)
    note = models.CharField(max_length=300, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at"]


class ChecklistItem(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="checklist_items")
    key = models.CharField(max_length=40)
    label = models.CharField(max_length=200)
    completed = models.BooleanField(default=False)
    is_custom = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["opportunity", "key"], name="unique_checklist_key"),
        ]


class Contact(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contacts")
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
    )
    name = models.CharField(max_length=200)
    organization = models.CharField(max_length=200, blank=True)
    role_title = models.CharField(max_length=200, blank=True)
    relationship = models.CharField(max_length=32, choices=Relationship.choices, default=Relationship.OTHER)
    profile_link = models.URLField(blank=True)
    channel = models.CharField(max_length=80, blank=True)
    last_contact_date = models.DateField(null=True, blank=True)
    next_follow_up = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    referral_status = models.CharField(
        max_length=20,
        choices=ReferralStatus.choices,
        default=ReferralStatus.NONE,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ContactInteraction(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="interactions")
    occurred_on = models.DateField(default=timezone.localdate)
    channel = models.CharField(max_length=80, blank=True)
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_on", "-id"]


class Task(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks")
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasks",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    title = models.CharField(max_length=200)
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=16, choices=TaskPriority.choices, default=TaskPriority.MEDIUM)
    task_type = models.CharField(max_length=32, choices=TaskType.choices, default=TaskType.OTHER)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["completed", "due_date", "-priority"]


class InterviewStage(TimeStampedModel):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="interview_stages")
    stage_name = models.CharField(max_length=120)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    format = models.CharField(max_length=80, blank=True)
    interviewer_names = models.CharField(max_length=300, blank=True)
    interviewer_roles = models.CharField(max_length=300, blank=True)
    next_step = models.CharField(max_length=300, blank=True)
    expected_response_date = models.DateField(null=True, blank=True)
    thank_you_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["scheduled_at", "id"]


class InterviewNote(TimeStampedModel):
    stage = models.ForeignKey(InterviewStage, on_delete=models.CASCADE, related_name="notes")
    note_type = models.CharField(max_length=20, choices=InterviewNoteType.choices, default=InterviewNoteType.GENERAL)
    content = models.TextField()

    class Meta:
        ordering = ["note_type", "id"]


class SavedTemplate(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="templates")
    name = models.CharField(max_length=120)
    template_type = models.CharField(max_length=40, default="message")
    body = models.TextField()

    class Meta:
        ordering = ["name"]


def ensure_default_checklist(opportunity: Opportunity) -> None:
    if opportunity.checklist_items.exists():
        return
    items = [
        ChecklistItem(opportunity=opportunity, key=key, label=label, sort_order=index)
        for index, (key, label) in enumerate(DEFAULT_CHECKLIST)
    ]
    ChecklistItem.objects.bulk_create(items)


class SimplifyListing(TimeStampedModel):
    listing_key = models.CharField(max_length=64, unique=True)
    company = models.CharField(max_length=200)
    title = models.CharField(max_length=300)
    location = models.CharField(max_length=400, blank=True)
    apply_url = models.URLField(max_length=1000, blank=True)
    category = models.CharField(max_length=80, blank=True)
    age_label = models.CharField(max_length=16, blank=True)
    age_days = models.PositiveIntegerField(null=True, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["age_days", "-first_seen_at"]

    def __str__(self) -> str:
        return f"{self.company} · {self.title}"


class UserListingState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listing_states")
    listing = models.ForeignKey(SimplifyListing, on_delete=models.CASCADE, related_name="user_states")
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="listing_states",
    )
    hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "listing"], name="unique_user_listing"),
        ]


class GmailAccount(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gmail_account")
    email = models.EmailField(blank=True)
    token_json = models.TextField()
    spreadsheet_id = models.CharField(max_length=80, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)


class GmailProcessedMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gmail_messages")
    message_id = models.CharField(max_length=128)
    thread_id = models.CharField(max_length=128, blank=True)
    subject = models.CharField(max_length=300, blank=True)
    parser_version = models.PositiveSmallIntegerField(default=0)
    parse_status = models.CharField(max_length=20, blank=True)
    application_key = models.CharField(max_length=300, blank=True)
    tab = models.CharField(max_length=40, blank=True)
    last_error = models.TextField(blank=True)
    fetch_attempts = models.PositiveSmallIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "message_id"], name="unique_user_gmail_message"),
        ]
