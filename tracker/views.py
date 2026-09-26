from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, TemplateView

from tracker.forms import (
    ContactForm,
    ExperienceForm,
    InteractionForm,
    InterviewStageForm,
    MaterialForm,
    OpportunityFilterForm,
    OpportunityForm,
    ProfileForm,
    ProjectForm,
    RegisterForm,
    StatusForm,
    TaskForm,
    TemplateForm,
    TrackForm,
)
from tracker.constants import SHEET_STATUSES, SHEET_STATUS_FROM_FULL, OpportunityStatus, Source
from tracker.models import (
    ApplicationMaterial,
    ChecklistItem,
    Contact,
    Experience,
    GmailAccount,
    GmailProcessedMessage,
    InterviewStage,
    Opportunity,
    ProfileTrack,
    Project,
    SavedTemplate,
    SimplifyListing,
    Task,
    UserListingState,
)
from tracker.services.analytics import breakdown_explanation, dashboard_metrics
from tracker.services.duplicates import find_duplicates
from tracker.services.exporting import (
    contacts_csv,
    full_json,
    import_opportunities_csv,
    opportunities_csv,
    preparation_markdown,
    status_history_csv,
    tasks_csv,
)
from tracker.services.matching import refresh_match
from tracker.services.ownership import owned
from tracker.services.skills import replace_opportunity_skills, replace_track_skills
from tracker.services import ensure_profile
from tracker.services.simplify import new_listing_count, should_resync, sync_listings
from tracker.services.gmail import (
    credentials_from_json,
    credentials_to_json,
    fetch_job_messages,
    fetch_messages_by_ids,
    flow_for,
    gmail_configured,
    refresh_if_needed,
)
from tracker.services.gsheet import hint_from_mail, push_hints, spreadsheet_id_from_url
from tracker.services.mailparse import PARSER_VERSION, apply_mail_hints, parse_message, parse_pasted_emails, to_sheet_hint
from tracker.services.workflow import (
    change_status,
    duplicate_opportunity,
    initialize_opportunity,
    snapshot_materials,
)


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("home")
        return render(request, "registration/register.html", {"form": RegisterForm()})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            user.email = form.cleaned_data["email"]
            user.save(update_fields=["email"])
            ensure_profile(user)
            login(request, user)
            messages.success(request, "Welcome. Add a row when you apply, or browse new openings.")
            return redirect("home")
        return render(request, "registration/register.html", {"form": form})


class AccountView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "account.html")

    def post(self, request):
        if request.POST.get("confirm") != "DELETE":
            messages.error(request, "Type DELETE to confirm account deletion.")
            return redirect("account")
        user = request.user
        user.delete()
        messages.success(request, "Your account and data were deleted.")
        return redirect("login")


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        ensure_profile(user)
        metrics = dashboard_metrics(user)
        context.update(metrics)
        context["recent"] = Opportunity.objects.filter(user=user, is_archived=False)[:8]
        context["open_tasks"] = Task.objects.filter(user=user, completed=False).order_by("due_date")[:8]
        return context


class OpportunityListView(LoginRequiredMixin, View):
    def get(self, request):
        ensure_profile(request.user)
        q = (request.GET.get("q") or "").strip()
        status = request.GET.get("status") or ""
        qs = Opportunity.objects.filter(user=request.user, is_archived=False).select_related("application")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(company__icontains=q) | Q(location__icontains=q))
        if status:
            mapped = [key for key, value in SHEET_STATUS_FROM_FULL.items() if value == status]
            qs = qs.filter(status__in=mapped or [status])
        return render(
            request,
            "opportunities/list.html",
            {
                "opportunities": qs,
                "sheet_statuses": SHEET_STATUSES,
                "q": q,
                "status": status,
                "status_counts": _sheet_counts(request.user),
                "gmail_account": GmailAccount.objects.filter(user=request.user).first(),
                "gmail_ready": gmail_configured(),
            },
        )

    def post(self, request):
        company = (request.POST.get("company") or "").strip()
        title = (request.POST.get("title") or "").strip()
        url = (request.POST.get("url") or "").strip()
        status = request.POST.get("status") or OpportunityStatus.SAVED
        if not company or not title:
            messages.error(request, "Company and role are enough to add a row.")
            return redirect("opportunity_list")
        opportunity = Opportunity.objects.create(
            user=request.user,
            company=company,
            title=title,
            url=url,
            status=OpportunityStatus.SAVED,
            source=Source.OTHER,
        )
        initialize_opportunity(opportunity)
        if status != OpportunityStatus.SAVED:
            change_status(opportunity, status, "Added from sheet")
        messages.success(request, f"Added {title} at {company}.")
        return redirect("opportunity_list")


def _sheet_counts(user):
    mapped = {value: 0 for value, _label in SHEET_STATUSES}
    for status in Opportunity.objects.filter(user=user, is_archived=False).values_list("status", flat=True):
        key = SHEET_STATUS_FROM_FULL.get(status, OpportunityStatus.SAVED)
        mapped[key] = mapped.get(key, 0) + 1
    return mapped


class OpportunityBoardView(LoginRequiredMixin, View):
    def get(self, request):
        from tracker.constants import OpportunityStatus

        qs = Opportunity.objects.filter(user=request.user, is_archived=False)
        columns = []
        for value, label in OpportunityStatus.choices:
            columns.append({"value": value, "label": label, "items": [opp for opp in qs if opp.status == value]})
        return render(request, "opportunities/board.html", {"columns": columns, "status_form": StatusForm()})


class OpportunityCreateView(LoginRequiredMixin, View):
    def get(self, request):
        ensure_profile(request.user)
        form = OpportunityForm(user=request.user)
        return render(request, "opportunities/form.html", {"form": form, "mode": "create"})

    def post(self, request):
        form = OpportunityForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, "opportunities/form.html", {"form": form, "mode": "create"})
        duplicates = find_duplicates(
            request.user,
            title=form.cleaned_data["title"],
            company=form.cleaned_data["company"],
            url=form.cleaned_data.get("url") or "",
            description=form.cleaned_data.get("description") or "",
        )
        if duplicates and request.POST.get("confirm_duplicate") != "1":
            return render(
                request,
                "opportunities/form.html",
                {"form": form, "mode": "create", "duplicates": duplicates},
            )
        opportunity = form.save(commit=False)
        opportunity.user = request.user
        if not opportunity.selected_track:
            profile = ensure_profile(request.user)
            opportunity.selected_track = profile.tracks.filter(is_default=True).first() or profile.tracks.first()
        opportunity.save()
        initialize_opportunity(
            opportunity,
            form.cleaned_data.get("required_skills_text") or "",
            form.cleaned_data.get("preferred_skills_text") or "",
        )
        messages.success(request, "Opportunity saved. Review the match summary next.")
        return redirect("opportunity_detail", pk=opportunity.pk)


class OpportunityUpdateView(LoginRequiredMixin, View):
    def get(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        form = OpportunityForm(instance=opportunity, user=request.user)
        form.fields["required_skills_text"].initial = "\n".join(
            skill.name for skill in opportunity.skills.filter(kind="required")
        )
        form.fields["preferred_skills_text"].initial = "\n".join(
            skill.name for skill in opportunity.skills.filter(kind="preferred")
        )
        return render(request, "opportunities/form.html", {"form": form, "mode": "edit", "opportunity": opportunity})

    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        form = OpportunityForm(request.POST, instance=opportunity, user=request.user)
        if not form.is_valid():
            return render(request, "opportunities/form.html", {"form": form, "mode": "edit", "opportunity": opportunity})
        form.save()
        replace_opportunity_skills(
            opportunity,
            form.cleaned_data.get("required_skills_text") or "",
            form.cleaned_data.get("preferred_skills_text") or "",
        )
        refresh_match(opportunity)
        messages.success(request, "Opportunity updated.")
        return redirect("opportunity_detail", pk=opportunity.pk)


class OpportunityDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        if not opportunity.match_payload:
            refresh_match(opportunity)
            opportunity.refresh_from_db()
        materials = request.user.materials.all()
        selected_ids = list(
            opportunity.application.material_snapshots.values_list("material_id", flat=True)
        ) if hasattr(opportunity, "application") else []
        return render(
            request,
            "opportunities/detail.html",
            {
                "opportunity": opportunity,
                "status_form": StatusForm(initial={"status": opportunity.status}),
                "task_form": TaskForm(user=request.user, initial={"opportunity": opportunity}),
                "contact_form": ContactForm(user=request.user, initial={"opportunity": opportunity}),
                "interview_form": InterviewStageForm(),
                "materials": materials,
                "selected_material_ids": selected_ids,
                "duplicates": find_duplicates(
                    request.user,
                    title=opportunity.title,
                    company=opportunity.company,
                    url=opportunity.url,
                    description=opportunity.description,
                    exclude_id=opportunity.pk,
                ),
                "templates": SavedTemplate.objects.filter(user=request.user),
            },
        )


class StatusChangeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        form = StatusForm(request.POST)
        if form.is_valid():
            change_status(opportunity, form.cleaned_data["status"], form.cleaned_data.get("note") or "")
            if not request.htmx:
                messages.success(request, "Status updated.")
        opportunity.refresh_from_db()
        if request.htmx:
            return render(
                request,
                "opportunities/_sheet_row.html",
                {"opp": opportunity, "sheet_statuses": SHEET_STATUSES},
            )
        return redirect(request.POST.get("next") or reverse("opportunity_detail", args=[pk]))


class SheetNotesView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        opportunity.notes = (request.POST.get("notes") or "").strip()
        opportunity.save(update_fields=["notes", "updated_at"])
        if request.htmx:
            return render(
                request,
                "opportunities/_sheet_row.html",
                {"opp": opportunity, "sheet_statuses": SHEET_STATUSES},
            )
        return redirect("home")


class OpeningsView(LoginRequiredMixin, View):
    def get(self, request):
        profile = ensure_profile(request.user)
        error = ""
        created = 0
        if request.GET.get("refresh") == "1" or should_resync():
            try:
                result = sync_listings()
                created = result["created"]
            except Exception as exc:  # noqa: BLE001 — show a friendly fetch error
                error = f"Could not refresh the GitHub list ({exc}). Showing the last saved copy."
        last_viewed = profile.openings_last_viewed_at
        listings = SimplifyListing.objects.filter(is_active=True)
        q = (request.GET.get("q") or "").strip()
        category = request.GET.get("category") or ""
        if q:
            listings = listings.filter(Q(company__icontains=q) | Q(title__icontains=q) | Q(location__icontains=q))
        if category:
            listings = listings.filter(category=category)
        if request.GET.get("new") == "1":
            if last_viewed:
                listings = listings.filter(first_seen_at__gt=last_viewed)
            else:
                listings = listings.filter(age_days__lte=1)
        saved_keys = set(
            Opportunity.objects.filter(user=request.user).exclude(simplify_key="").values_list("simplify_key", flat=True)
        )
        hidden_ids = set(
            UserListingState.objects.filter(user=request.user, hidden=True).values_list("listing_id", flat=True)
        )
        listings = listings.exclude(id__in=hidden_ids)[:250]
        categories = (
            SimplifyListing.objects.filter(is_active=True)
            .exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        new_count = new_listing_count(request.user, last_viewed)
        profile.openings_last_viewed_at = timezone.now()
        profile.save(update_fields=["openings_last_viewed_at"])
        return render(
            request,
            "openings/list.html",
            {
                "listings": listings,
                "saved_keys": saved_keys,
                "categories": categories,
                "q": q,
                "category": category,
                "error": error,
                "created": created,
                "new_count": new_count,
                "last_viewed": last_viewed,
            },
        )


class OpeningSaveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        listing = get_object_or_404(SimplifyListing, pk=pk)
        applied = request.POST.get("applied") == "1"
        existing = Opportunity.objects.filter(user=request.user, simplify_key=listing.listing_key).first()
        if existing:
            messages.info(request, "That role is already on your sheet.")
            return redirect("home")
        opportunity = Opportunity.objects.create(
            user=request.user,
            company=listing.company,
            title=listing.title,
            url=listing.apply_url,
            location=listing.location,
            source=Source.SIMPLIFY,
            simplify_key=listing.listing_key,
            notes=f"From SimplifyJobs · {listing.category}",
        )
        initialize_opportunity(opportunity)
        if applied:
            change_status(opportunity, OpportunityStatus.APPLIED, "Applied from openings list")
        UserListingState.objects.update_or_create(
            user=request.user,
            listing=listing,
            defaults={"opportunity": opportunity},
        )
        messages.success(request, f"{'Applied and saved' if applied else 'Saved'} {listing.title} at {listing.company}.")
        return redirect(request.POST.get("next") or "home")


class OpportunityArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        opportunity.is_archived = not opportunity.is_archived
        opportunity.save(update_fields=["is_archived", "updated_at"])
        return redirect("opportunity_list")


class OpportunityDuplicateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        clone = duplicate_opportunity(opportunity)
        return redirect("opportunity_detail", pk=clone.pk)


class OpportunityDeleteView(LoginRequiredMixin, DeleteView):
    model = Opportunity
    template_name = "confirm_delete.html"
    success_url = reverse_lazy("opportunity_list")

    def get_queryset(self):
        return Opportunity.objects.filter(user=self.request.user)


class ChecklistToggleView(LoginRequiredMixin, View):
    def post(self, request, pk, item_id):
        opportunity = owned(Opportunity, request.user, pk)
        item = get_object_or_404(ChecklistItem, pk=item_id, opportunity=opportunity)
        item.completed = not item.completed
        item.save(update_fields=["completed"])
        if request.htmx:
            return render(request, "opportunities/_checklist_item.html", {"item": item, "opportunity": opportunity})
        return redirect("opportunity_detail", pk=pk)


class ChecklistAddView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        label = (request.POST.get("label") or "").strip()
        if label:
            ChecklistItem.objects.create(
                opportunity=opportunity,
                key=f"custom_{timezone.now().timestamp()}",
                label=label,
                is_custom=True,
                sort_order=opportunity.checklist_items.count() + 1,
            )
        return redirect("opportunity_detail", pk=pk)


class MaterialsSelectView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        ids = [int(value) for value in request.POST.getlist("materials") if value.isdigit()]
        snapshot_materials(opportunity, ids)
        messages.success(request, "Saved the material versions used for this application.")
        return redirect("opportunity_detail", pk=pk)


class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        profile = ensure_profile(request.user)
        return render(
            request,
            "profile/edit.html",
            {
                "form": ProfileForm(instance=profile),
                "track_form": TrackForm(),
                "experience_form": ExperienceForm(),
                "project_form": ProjectForm(),
                "profile": profile,
            },
        )

    def post(self, request):
        profile = ensure_profile(request.user)
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile saved.")
            return redirect("profile")
        return render(
            request,
            "profile/edit.html",
            {
                "form": form,
                "track_form": TrackForm(),
                "experience_form": ExperienceForm(),
                "project_form": ProjectForm(),
                "profile": profile,
            },
        )


class TrackCreateView(LoginRequiredMixin, View):
    def post(self, request):
        profile = ensure_profile(request.user)
        form = TrackForm(request.POST)
        if form.is_valid():
            track = form.save(commit=False)
            track.profile = profile
            if track.is_default:
                profile.tracks.update(is_default=False)
            track.save()
            replace_track_skills(track, form.cleaned_data.get("skills_text") or "")
            messages.success(request, f"Added track “{track.name}”.")
        else:
            messages.error(request, "Could not add that track. Check the name.")
        return redirect("profile")


class TrackUpdateView(LoginRequiredMixin, View):
    def get(self, request, pk):
        track = get_object_or_404(ProfileTrack, pk=pk, profile__user=request.user)
        form = TrackForm(instance=track)
        form.fields["skills_text"].initial = "\n".join(link.skill.name for link in track.profile_skills.select_related("skill"))
        return render(request, "profile/track_form.html", {"form": form, "track": track})

    def post(self, request, pk):
        track = get_object_or_404(ProfileTrack, pk=pk, profile__user=request.user)
        form = TrackForm(request.POST, instance=track)
        if form.is_valid():
            if form.cleaned_data.get("is_default"):
                track.profile.tracks.update(is_default=False)
            form.save()
            replace_track_skills(track, form.cleaned_data.get("skills_text") or "")
            messages.success(request, "Track updated.")
            return redirect("profile")
        return render(request, "profile/track_form.html", {"form": form, "track": track})


class TrackDeleteView(LoginRequiredMixin, DeleteView):
    model = ProfileTrack
    template_name = "confirm_delete.html"
    success_url = reverse_lazy("profile")

    def get_queryset(self):
        return ProfileTrack.objects.filter(profile__user=self.request.user)


class ExperienceCreateView(LoginRequiredMixin, View):
    def post(self, request):
        profile = ensure_profile(request.user)
        form = ExperienceForm(request.POST)
        if form.is_valid():
            experience = form.save(commit=False)
            experience.profile = profile
            experience.save()
        return redirect("profile")


class ExperienceDeleteView(LoginRequiredMixin, DeleteView):
    model = Experience
    success_url = reverse_lazy("profile")
    template_name = "confirm_delete.html"

    def get_queryset(self):
        return Experience.objects.filter(profile__user=self.request.user)


class ProjectCreateView(LoginRequiredMixin, View):
    def post(self, request):
        profile = ensure_profile(request.user)
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.profile = profile
            project.save()
        return redirect("profile")


class ProjectDeleteView(LoginRequiredMixin, DeleteView):
    model = Project
    success_url = reverse_lazy("profile")
    template_name = "confirm_delete.html"

    def get_queryset(self):
        return Project.objects.filter(profile__user=self.request.user)


class MaterialListView(LoginRequiredMixin, View):
    def get(self, request):
        return render(
            request,
            "materials/list.html",
            {
                "materials": request.user.materials.select_related("track"),
                "form": MaterialForm(user=request.user),
            },
        )

    def post(self, request):
        form = MaterialForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            material = form.save(commit=False)
            material.user = request.user
            material.save()
            messages.success(request, "Material saved.")
            return redirect("materials")
        return render(
            request,
            "materials/list.html",
            {"materials": request.user.materials.select_related("track"), "form": form},
        )


class MaterialDeleteView(LoginRequiredMixin, DeleteView):
    model = ApplicationMaterial
    success_url = reverse_lazy("materials")
    template_name = "confirm_delete.html"

    def get_queryset(self):
        return ApplicationMaterial.objects.filter(user=self.request.user)


class MaterialDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        material = owned(ApplicationMaterial, request.user, pk)
        if not material.file:
            raise Http404()
        return FileResponse(material.file.open("rb"), as_attachment=True, filename=material.file.name.rsplit("/", 1)[-1])


class TaskListView(LoginRequiredMixin, View):
    def get(self, request):
        tasks = Task.objects.filter(user=request.user)
        if request.GET.get("open") == "1":
            tasks = tasks.filter(completed=False)
        return render(request, "tasks/list.html", {"tasks": tasks, "form": TaskForm(user=request.user)})

    def post(self, request):
        form = TaskForm(request.POST, user=request.user)
        if form.is_valid():
            task = form.save(commit=False)
            task.user = request.user
            if task.opportunity_id and task.opportunity.user_id != request.user.id:
                raise Http404()
            task.save()
            messages.success(request, "Task added.")
            return redirect(request.POST.get("next") or "tasks")
        return render(request, "tasks/list.html", {"tasks": Task.objects.filter(user=request.user), "form": form})


class TaskToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        task = owned(Task, request.user, pk)
        task.completed = not task.completed
        task.completed_at = timezone.now() if task.completed else None
        task.save(update_fields=["completed", "completed_at", "updated_at"])
        return redirect(request.POST.get("next") or "tasks")


class TaskDeleteView(LoginRequiredMixin, DeleteView):
    model = Task
    success_url = reverse_lazy("tasks")
    template_name = "confirm_delete.html"

    def get_queryset(self):
        return Task.objects.filter(user=self.request.user)


class ContactListView(LoginRequiredMixin, View):
    def get(self, request):
        return render(
            request,
            "contacts/list.html",
            {
                "contacts": Contact.objects.filter(user=request.user).select_related("opportunity"),
                "form": ContactForm(user=request.user),
                "templates": SavedTemplate.objects.filter(user=request.user),
                "template_form": TemplateForm(),
            },
        )

    def post(self, request):
        form = ContactForm(request.POST, user=request.user)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.user = request.user
            contact.save()
            messages.success(request, "Contact saved.")
            next_url = request.POST.get("next")
            if next_url:
                return redirect(next_url)
            return redirect("contacts")
        return render(
            request,
            "contacts/list.html",
            {
                "contacts": Contact.objects.filter(user=request.user),
                "form": form,
                "templates": SavedTemplate.objects.filter(user=request.user),
                "template_form": TemplateForm(),
            },
        )


class ContactDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        contact = owned(Contact, request.user, pk)
        return render(
            request,
            "contacts/detail.html",
            {
                "contact": contact,
                "form": ContactForm(instance=contact, user=request.user),
                "interaction_form": InteractionForm(),
            },
        )

    def post(self, request, pk):
        contact = owned(Contact, request.user, pk)
        if request.POST.get("intent") == "interaction":
            form = InteractionForm(request.POST)
            if form.is_valid():
                interaction = form.save(commit=False)
                interaction.contact = contact
                interaction.save()
                contact.last_contact_date = interaction.occurred_on
                contact.save(update_fields=["last_contact_date"])
            return redirect("contact_detail", pk=pk)
        form = ContactForm(request.POST, instance=contact, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Contact updated.")
            return redirect("contact_detail", pk=pk)
        return render(
            request,
            "contacts/detail.html",
            {"contact": contact, "form": form, "interaction_form": InteractionForm()},
        )


class ContactDeleteView(LoginRequiredMixin, DeleteView):
    model = Contact
    success_url = reverse_lazy("contacts")
    template_name = "confirm_delete.html"

    def get_queryset(self):
        return Contact.objects.filter(user=self.request.user)


class TemplateCreateView(LoginRequiredMixin, View):
    def post(self, request):
        form = TemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.user = request.user
            template.save()
        return redirect("contacts")


class TemplateDeleteView(LoginRequiredMixin, DeleteView):
    model = SavedTemplate
    success_url = reverse_lazy("contacts")
    template_name = "confirm_delete.html"

    def get_queryset(self):
        return SavedTemplate.objects.filter(user=self.request.user)


class InterviewCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        form = InterviewStageForm(request.POST)
        if form.is_valid():
            stage = form.save(commit=False)
            stage.opportunity = opportunity
            stage.save()
            messages.success(request, "Interview stage added.")
        return redirect("opportunity_detail", pk=pk)


class InterviewNoteCreateView(LoginRequiredMixin, View):
    def post(self, request, pk, stage_id):
        opportunity = owned(Opportunity, request.user, pk)
        stage = get_object_or_404(InterviewStage, pk=stage_id, opportunity=opportunity)
        form = InterviewNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.stage = stage
            note.save()
        return redirect("opportunity_detail", pk=pk)


class AnalyticsView(LoginRequiredMixin, View):
    def get(self, request):
        start = request.GET.get("start")
        end = request.GET.get("end")
        start_date = datetime.strptime(start, "%Y-%m-%d").date() if start else None
        end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else None
        metrics = dashboard_metrics(request.user, start_date, end_date)
        metrics["explanation"] = breakdown_explanation()
        metrics["start"] = start or ""
        metrics["end"] = end or ""
        return render(request, "analytics.html", metrics)


class ImportExportView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "import_export.html")

    def post(self, request):
        upload = request.FILES.get("csv_file")
        if not upload:
            messages.error(request, "Choose a CSV file first.")
            return redirect("import_export")
        created, errors = import_opportunities_csv(request.user, upload)
        for error in errors[:8]:
            messages.warning(request, error)
        messages.success(request, f"Imported {created} opportunities.")
        return redirect("opportunity_list")


class ExportDownloadView(LoginRequiredMixin, View):
    def get(self, request, kind):
        user = request.user
        if kind == "opportunities":
            return HttpResponse(opportunities_csv(user), content_type="text/csv", headers={"Content-Disposition": 'attachment; filename="opportunities.csv"'})
        if kind == "contacts":
            return HttpResponse(contacts_csv(user), content_type="text/csv", headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})
        if kind == "tasks":
            return HttpResponse(tasks_csv(user), content_type="text/csv", headers={"Content-Disposition": 'attachment; filename="tasks.csv"'})
        if kind == "status-history":
            return HttpResponse(status_history_csv(user), content_type="text/csv", headers={"Content-Disposition": 'attachment; filename="status-history.csv"'})
        if kind == "json":
            return HttpResponse(full_json(user), content_type="application/json", headers={"Content-Disposition": 'attachment; filename="account-export.json"'})
        raise Http404()


class BriefExportView(LoginRequiredMixin, View):
    def get(self, request, pk):
        opportunity = owned(Opportunity, request.user, pk)
        content = preparation_markdown(opportunity)
        filename = f"{opportunity.company}-{opportunity.title}-brief.md".replace(" ", "_")
        return HttpResponse(content, content_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class GmailConnectView(LoginRequiredMixin, View):
    def get(self, request):
        account = GmailAccount.objects.filter(user=request.user).first()
        sheet_id = ""
        if account and account.spreadsheet_id:
            sheet_id = account.spreadsheet_id
        elif request.session.get("spreadsheet_id"):
            sheet_id = request.session["spreadsheet_id"]
        else:
            sheet_id = getattr(settings, "GOOGLE_SHEET_ID", "")
        return render(
            request,
            "gmail/connect.html",
            {
                "account": account,
                "gmail_ready": gmail_configured(),
                "spreadsheet_id": sheet_id,
                "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else "",
            },
        )

    def post(self, request):
        sheet_url = request.POST.get("spreadsheet_url") or ""
        if request.POST.get("save_sheet"):
            sheet_id = spreadsheet_id_from_url(sheet_url)
            if not sheet_id:
                messages.error(request, "Paste the full Google Sheet link.")
                return redirect("gmail_connect")
            previous = request.session.get("spreadsheet_id") or ""
            request.session["spreadsheet_id"] = sheet_id
            account = GmailAccount.objects.filter(user=request.user).first()
            if account:
                previous = account.spreadsheet_id or previous
                account.spreadsheet_id = sheet_id
                account.save(update_fields=["spreadsheet_id", "updated_at"])
            if previous and previous != sheet_id:
                # A different sheet has none of the rows, so every logged message must be re-applied.
                GmailProcessedMessage.objects.filter(user=request.user).update(parse_status="")
            messages.success(request, "Google Sheet saved. Sync will write to the internships and newgrad tabs.")
            return redirect("gmail_connect")
        pasted = request.POST.get("pasted") or ""
        if pasted.strip():
            hints = parse_pasted_emails(pasted)
            result = apply_mail_hints(request.user, hints)
            sheet_result = _push_mail_hints(request, hints)
            extra = ""
            if sheet_result:
                extra = f" Google Sheet: added {sheet_result['created']}, updated {sheet_result['updated']}."
            messages.success(
                request,
                f"Read {len(hints)} recruiter emails. Added {result['created']}, updated {result['updated']}.{extra}",
            )
            return redirect("home")
        if not gmail_configured():
            messages.error(request, "Add Google OAuth keys to .env first, or paste emails below.")
            return redirect("gmail_connect")
        import os

        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
        flow = flow_for(request)
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        request.session["gmail_oauth_state"] = state
        request.session["gmail_code_verifier"] = flow.code_verifier
        request.session.save()
        return redirect(authorization_url)


class GmailCallbackView(LoginRequiredMixin, View):
    def get(self, request):
        if not gmail_configured():
            return redirect("gmail_connect")
        import os

        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
        flow = flow_for(request)
        flow.code_verifier = request.session.get("gmail_code_verifier")
        try:
            flow.fetch_token(authorization_response=request.build_absolute_uri())
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Google login did not finish ({exc}).")
            return redirect("gmail_connect")
        creds = flow.credentials
        sheet_id = request.session.get("spreadsheet_id") or getattr(settings, "GOOGLE_SHEET_ID", "")
        GmailAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "token_json": credentials_to_json(creds),
                "email": request.user.email,
                "spreadsheet_id": sheet_id,
            },
        )
        messages.success(request, "Gmail connected. Syncing recruiter mail…")
        return redirect("gmail_sync")


class GmailDisconnectView(LoginRequiredMixin, View):
    def post(self, request):
        GmailAccount.objects.filter(user=request.user).delete()
        messages.success(request, "Gmail disconnected.")
        return redirect("gmail_connect")


def _done_message_ids(user):
    return set(
        GmailProcessedMessage.objects.filter(
            user=user,
            parser_version__gte=PARSER_VERSION,
            parse_status__in=["applied", "ignored"],
        ).values_list("message_id", flat=True)
    )


def _stale_message_ids(user, limit: int = 30) -> list[str]:
    from django.db.models import Q

    return list(
        GmailProcessedMessage.objects.filter(user=user)
        .filter(Q(parser_version__lt=PARSER_VERSION) | Q(parse_status__in=["", "failed", "review"]))
        .order_by("id")
        .values_list("message_id", flat=True)[:limit]
    )


def _save_gmail_log(user, message_id: str, **fields):
    record, _created = GmailProcessedMessage.objects.get_or_create(user=user, message_id=message_id)
    for key, value in fields.items():
        setattr(record, key, value)
    record.synced_at = timezone.now()
    record.save()
    return record


def _process_gmail_items(user, creds, items, sheet_id: str) -> dict:
    counts = {"created": 0, "updated": 0, "skipped": 0, "review": 0, "failed": 0}
    hints = []
    for item in sorted(items, key=lambda entry: _mail_timestamp(entry.get("date") or "")):
        try:
            hint = parse_message(
                item["from"],
                item["subject"],
                item["body"],
                item["id"],
                item.get("threadId") or "",
                _mail_date(item.get("date") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += 1
            _save_gmail_log(
                user,
                item.get("id") or "",
                thread_id=item.get("threadId") or "",
                subject=item.get("subject") or "",
                parser_version=PARSER_VERSION,
                parse_status="failed",
                last_error=str(exc),
            )
            continue
        if not hint:
            counts["skipped"] += 1
            _save_gmail_log(
                user,
                item["id"],
                thread_id=item.get("threadId") or "",
                subject=item.get("subject") or "",
                parser_version=PARSER_VERSION,
                parse_status="ignored",
                last_error="",
            )
            continue
        hints.append(hint)
    local = apply_mail_hints(user, hints) if hints else {"created": 0, "updated": 0, "skipped": 0, "review": 0}
    for key in ("created", "updated", "skipped", "review"):
        counts[key] += local.get(key, 0)
    sheet_result = None
    if sheet_id and hints:
        sheet_hints = [to_sheet_hint(hint) for hint in hints]
        try:
            sheet_result = push_hints(creds, sheet_id, sheet_hints)
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += len(hints)
            for hint in hints:
                _save_gmail_log(
                    user,
                    hint.source_id,
                    thread_id=hint.thread_id,
                    subject="",
                    parser_version=PARSER_VERSION,
                    parse_status="failed",
                    application_key=hint.application_key,
                    tab=hint.tab,
                    last_error=str(exc),
                )
            return counts
    for hint in hints:
        status = "review" if local.get("review") and False else "applied"
        _save_gmail_log(
            user,
            hint.source_id,
            thread_id=hint.thread_id,
            subject="",
            parser_version=PARSER_VERSION,
            parse_status=status,
            application_key=hint.application_key,
            tab=hint.tab,
            last_error="",
        )
    if sheet_result:
        counts["sheet"] = sheet_result
    return counts


class GmailSyncView(LoginRequiredMixin, View):
    def get(self, request):
        return self.post(request)

    def post(self, request):
        account = GmailAccount.objects.filter(user=request.user).first()
        if not account:
            messages.info(request, "Connect Gmail first.")
            return redirect("gmail_connect")
        try:
            creds = refresh_if_needed(credentials_from_json(account.token_json))
            account.token_json = credentials_to_json(creds)
            raw_messages = fetch_job_messages(creds, skip_ids=_done_message_ids(request.user), limit=25)
            stale_ids = _stale_message_ids(request.user, limit=20)
            if stale_ids:
                raw_messages.extend(fetch_messages_by_ids(creds, stale_ids))
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Gmail sync failed ({exc}).")
            return redirect("gmail_connect")
        sheet_id = account.spreadsheet_id or request.session.get("spreadsheet_id") or getattr(settings, "GOOGLE_SHEET_ID", "")
        counts = _process_gmail_items(request.user, creds, raw_messages, sheet_id)
        if sheet_id:
            account.spreadsheet_id = sheet_id
        account.last_synced_at = timezone.now()
        account.save(update_fields=["token_json", "last_synced_at", "spreadsheet_id"])
        extra = ""
        if counts.get("sheet"):
            extra = f" Google Sheet: added {counts['sheet']['created']}, updated {counts['sheet']['updated']}."
        messages.success(
            request,
            f"Gmail sync complete. Read {len(raw_messages)} messages. "
            f"Added {counts['created']}, updated {counts['updated']}, skipped {counts['skipped']}, "
            f"review {counts['review']}, failed {counts['failed']}.{extra}",
        )
        return redirect("home")


class GmailRecheckView(LoginRequiredMixin, View):
    def get(self, request):
        return self.post(request)

    def post(self, request):
        account = GmailAccount.objects.filter(user=request.user).first()
        if not account:
            messages.info(request, "Connect Gmail first.")
            return redirect("gmail_connect")
        try:
            creds = refresh_if_needed(credentials_from_json(account.token_json))
            account.token_json = credentials_to_json(creds)
            remaining = _stale_message_ids(request.user, limit=30)
            if not remaining:
                messages.success(request, "All scraped emails have already been rechecked with the current parser.")
                return redirect("gmail_connect")
            raw_messages = fetch_messages_by_ids(creds, remaining, limit=30)
            fetched_ids = {item["id"] for item in raw_messages}
            for message_id in remaining:
                if message_id not in fetched_ids:
                    _save_gmail_log(
                        request.user,
                        message_id,
                        parser_version=PARSER_VERSION,
                        parse_status="failed",
                        last_error="Gmail could not fetch this message.",
                    )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Gmail recheck failed ({exc}).")
            return redirect("gmail_connect")
        sheet_id = account.spreadsheet_id or request.session.get("spreadsheet_id") or getattr(settings, "GOOGLE_SHEET_ID", "")
        counts = _process_gmail_items(request.user, creds, raw_messages, sheet_id)
        if sheet_id:
            account.spreadsheet_id = sheet_id
        account.last_synced_at = timezone.now()
        account.save(update_fields=["token_json", "last_synced_at", "spreadsheet_id"])
        extra = ""
        if counts.get("sheet"):
            extra = f" Google Sheet: added {counts['sheet']['created']}, updated {counts['sheet']['updated']}."
        leftover = len(_stale_message_ids(request.user, limit=1000))
        more = f" {leftover} older emails still queued — click Recheck again." if leftover else " All scraped emails have been rechecked."
        messages.success(
            request,
            f"Rechecked {len(raw_messages)} scraped emails. Added {counts['created']}, updated {counts['updated']}, "
            f"review {counts['review']}, failed {counts['failed']}.{extra}{more}",
        )
        return redirect("home")


def _local_opportunity_hints(user):
    from tracker.services.gsheet import format_applied_date, hint_from_mail

    hints = []
    for opp in Opportunity.objects.filter(user=user, is_archived=False).select_related("application"):
        applied = ""
        if getattr(opp, "application", None) and opp.application.applied_at:
            applied = format_applied_date(timezone.localdate(opp.application.applied_at).isoformat())
        hints.append(
            hint_from_mail(
                opp.company,
                opp.title,
                opp.status,
                (opp.notes or "")[:180],
                date_applied=applied,
            )
        )
    return hints


def _mail_timestamp(raw: str) -> float:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _mail_date(raw: str) -> str:
    from email.utils import parsedate_to_datetime

    from tracker.services.gsheet import format_applied_date

    if not raw:
        return format_applied_date(timezone.localdate().isoformat())
    try:
        return format_applied_date(parsedate_to_datetime(raw).date().isoformat())
    except (TypeError, ValueError, OverflowError):
        return format_applied_date(timezone.localdate().isoformat())


def _push_mail_hints(request, hints):
    account = GmailAccount.objects.filter(user=request.user).first()
    sheet_id = ""
    if account and account.spreadsheet_id:
        sheet_id = account.spreadsheet_id
    else:
        sheet_id = request.session.get("spreadsheet_id") or getattr(settings, "GOOGLE_SHEET_ID", "")
    if not sheet_id or not hints or not account:
        return None
    try:
        creds = refresh_if_needed(credentials_from_json(account.token_json))
        sheet_hints = [hint_from_mail(hint.company, hint.title, hint.status, hint.note) for hint in hints]
        return push_hints(creds, sheet_id, sheet_hints)
    except Exception:  # noqa: BLE001
        return None

