from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from tracker.models import (
    ApplicationMaterial,
    Contact,
    ContactInteraction,
    Experience,
    InterviewNote,
    InterviewStage,
    Opportunity,
    Profile,
    ProfileTrack,
    Project,
    SavedTemplate,
    Task,
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "input"
            if isinstance(field.widget, forms.Textarea):
                css = "input textarea"
            elif isinstance(field.widget, forms.Select):
                css = "input select"
            elif isinstance(field.widget, forms.CheckboxInput):
                css = "checkbox"
            elif isinstance(field.widget, forms.FileInput):
                css = "input"
            field.widget.attrs.setdefault("class", css)


class RegisterForm(StyledFormMixin, UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = (
            "full_name",
            "phone",
            "linkedin_url",
            "github_url",
            "website_url",
            "school",
            "degree",
            "major",
            "graduation_date",
            "preferred_role_categories",
            "preferred_locations",
            "work_arrangement_preference",
            "work_authorization",
            "sponsorship_preference",
            "professional_pitch",
        )
        widgets = {
            "graduation_date": forms.DateInput(attrs={"type": "date"}),
            "professional_pitch": forms.Textarea(attrs={"rows": 4}),
        }


class TrackForm(StyledFormMixin, forms.ModelForm):
    skills_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "class": "input textarea"}),
        help_text="One skill per line.",
    )

    class Meta:
        model = ProfileTrack
        fields = ("name", "keywords", "pitch", "is_default")
        widgets = {
            "keywords": forms.Textarea(attrs={"rows": 3}),
            "pitch": forms.Textarea(attrs={"rows": 3}),
        }


class ExperienceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Experience
        fields = ("title", "organization", "experience_type", "start_date", "end_date", "description")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class ProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "url", "technologies", "description", "highlights")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "highlights": forms.Textarea(attrs={"rows": 3}),
        }


class MaterialForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ApplicationMaterial
        fields = ("name", "material_type", "track", "file", "link", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["track"].queryset = ProfileTrack.objects.filter(profile__user=user)


class OpportunityForm(StyledFormMixin, forms.ModelForm):
    required_skills_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "class": "input textarea"}),
        help_text="One required skill per line.",
    )
    preferred_skills_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "input textarea"}),
        help_text="One preferred skill per line.",
    )

    class Meta:
        model = Opportunity
        fields = (
            "title",
            "company",
            "url",
            "description",
            "source",
            "location",
            "work_arrangement",
            "role_type",
            "posting_date",
            "deadline",
            "degree_requirements",
            "experience_requirements",
            "sponsorship_status",
            "salary",
            "notes",
            "priority",
            "priority_override_reason",
            "selected_track",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 8}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "degree_requirements": forms.Textarea(attrs={"rows": 2}),
            "experience_requirements": forms.Textarea(attrs={"rows": 2}),
            "posting_date": forms.DateInput(attrs={"type": "date"}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["selected_track"].queryset = ProfileTrack.objects.filter(profile__user=user)


class StatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=Opportunity._meta.get_field("status").choices)
    note = forms.CharField(required=False, max_length=300)


class TaskForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ("title", "due_date", "priority", "task_type", "opportunity", "contact", "notes")
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["opportunity"].queryset = Opportunity.objects.filter(user=user, is_archived=False)
            self.fields["contact"].queryset = Contact.objects.filter(user=user)


class ContactForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Contact
        fields = (
            "name",
            "organization",
            "role_title",
            "relationship",
            "opportunity",
            "profile_link",
            "channel",
            "last_contact_date",
            "next_follow_up",
            "referral_status",
            "notes",
        )
        widgets = {
            "last_contact_date": forms.DateInput(attrs={"type": "date"}),
            "next_follow_up": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["opportunity"].queryset = Opportunity.objects.filter(user=user, is_archived=False)


class InteractionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ContactInteraction
        fields = ("occurred_on", "channel", "notes")
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class InterviewStageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = InterviewStage
        fields = (
            "stage_name",
            "scheduled_at",
            "format",
            "interviewer_names",
            "interviewer_roles",
            "next_step",
            "expected_response_date",
            "thank_you_sent",
        )
        widgets = {
            "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "expected_response_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]


class InterviewNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = InterviewNote
        fields = ("note_type", "content")
        widgets = {"content": forms.Textarea(attrs={"rows": 4})}


class TemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SavedTemplate
        fields = ("name", "template_type", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}


class OpportunityFilterForm(forms.Form):
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "input", "placeholder": "Search company or title"}))
    status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "input select"}))
    match_category = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "input select"}))
    priority = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "input select"}))
    source = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "input select"}))
    work_arrangement = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "input select"}))
    sponsorship_status = forms.ChoiceField(required=False, widget=forms.Select(attrs={"class": "input select"}))
    track = forms.IntegerField(required=False, widget=forms.Select(attrs={"class": "input select"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from tracker.constants import MatchCategory, Priority, Source, SponsorshipStatus, WorkArrangement
        from tracker.models import Opportunity as Opp
        from tracker.models import ProfileTrack

        def choices(items):
            return [("", "Any")] + list(items)

        self.fields["status"].choices = choices(Opp._meta.get_field("status").choices)
        self.fields["match_category"].choices = choices(MatchCategory.choices)
        self.fields["priority"].choices = choices(Priority.choices)
        self.fields["source"].choices = choices(Source.choices)
        self.fields["work_arrangement"].choices = choices(WorkArrangement.choices)
        self.fields["sponsorship_status"].choices = choices(SponsorshipStatus.choices)
        track_choices = [("", "Any track")]
        if user is not None:
            track_choices += [(track.id, track.name) for track in ProfileTrack.objects.filter(profile__user=user)]
        self.fields["track"].widget = forms.Select(attrs={"class": "input select"}, choices=track_choices)
