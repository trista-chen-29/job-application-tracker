from __future__ import annotations

from datetime import datetime

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
from tracker.models import (
    ApplicationMaterial,
    ChecklistItem,
    Contact,
    Experience,
    InterviewStage,
    Opportunity,
    ProfileTrack,
    Project,
    SavedTemplate,
    Task,
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
from tracker.services.workflow import (
    change_status,
    duplicate_opportunity,
    initialize_opportunity,
    snapshot_materials,
)


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return render(request, "registration/register.html", {"form": RegisterForm()})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            user.email = form.cleaned_data["email"]
            user.save(update_fields=["email"])
            ensure_profile(user)
            login(request, user)
            messages.success(request, "Welcome. Start with your profile, then add a role.")
            return redirect("profile")
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
        form = OpportunityFilterForm(request.GET, user=request.user)
        qs = Opportunity.objects.filter(user=request.user)
        if request.GET.get("archived") != "1":
            qs = qs.filter(is_archived=False)
        if form.is_valid():
            data = form.cleaned_data
            if data.get("q"):
                qs = qs.filter(Q(title__icontains=data["q"]) | Q(company__icontains=data["q"]) | Q(location__icontains=data["q"]))
            for field in ("status", "match_category", "priority", "source", "work_arrangement", "sponsorship_status"):
                if data.get(field):
                    qs = qs.filter(**{field: data[field]})
            if data.get("track"):
                qs = qs.filter(selected_track_id=data["track"])
        if request.GET.get("deadline"):
            qs = qs.filter(deadline=request.GET["deadline"])
        return render(
            request,
            "opportunities/list.html",
            {"opportunities": qs.select_related("selected_track"), "form": form},
        )


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
            messages.success(request, "Status updated.")
        return redirect(request.POST.get("next") or reverse("opportunity_detail", args=[pk]))


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
