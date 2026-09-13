from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from tracker.constants import (
    MaterialType,
    OpportunityStatus,
    Relationship,
    RoleType,
    Source,
    SponsorshipPreference,
    SponsorshipStatus,
    WorkArrangement,
    WorkAuthorization,
)
from tracker.models import (
    ApplicationMaterial,
    Contact,
    ContactInteraction,
    Experience,
    InterviewNote,
    InterviewStage,
    Opportunity,
    ProfileTrack,
    Project,
    SavedTemplate,
    Task,
)
from tracker.services import ensure_profile
from tracker.services.skills import replace_opportunity_skills, replace_track_skills
from tracker.services.workflow import change_status, initialize_opportunity, snapshot_materials


class Command(BaseCommand):
    help = "Create a demo student account with two tracks and sample applications."

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.com"},
        )
        user.set_password("DemoPass123!")
        user.save()
        profile = ensure_profile(user)
        profile.full_name = "Avery Chen"
        profile.school = "State University"
        profile.degree = "B.S."
        profile.major = "Computer Engineering"
        profile.graduation_date = timezone.localdate().replace(year=timezone.localdate().year + 1)
        profile.preferred_role_categories = "Software, Embedded/Systems, Test/Validation"
        profile.preferred_locations = "San Jose, Austin, Remote"
        profile.work_arrangement_preference = WorkArrangement.HYBRID
        profile.work_authorization = WorkAuthorization.NEEDS_SPONSORSHIP
        profile.sponsorship_preference = SponsorshipPreference.REQUIRED
        profile.professional_pitch = (
            "Computer engineering student targeting internships in firmware, test, and backend systems."
        )
        profile.save()

        software, _ = ProfileTrack.objects.update_or_create(
            profile=profile,
            name="Software",
            defaults={"keywords": "python, django, backend, api, intern", "pitch": "I build reliable backend services.", "is_default": True},
        )
        embedded, _ = ProfileTrack.objects.update_or_create(
            profile=profile,
            name="Embedded/Systems",
            defaults={"keywords": "c, firmware, rtos, embedded, linux", "pitch": "I debug hardware/software boundaries.", "is_default": False},
        )
        replace_track_skills(software, "Python\nDjango\nSQL\nGit\nREST APIs")
        replace_track_skills(embedded, "C\nPython\nRTOS\nLinux\nOscilloscope")

        Experience.objects.update_or_create(
            profile=profile,
            title="Firmware intern",
            defaults={"organization": "Campus Robotics Club", "experience_type": "work", "description": "Wrote C drivers for sensors."},
        )
        Project.objects.update_or_create(
            profile=profile,
            name="Battery telemetry logger",
            defaults={"technologies": "python c mqtt", "description": "Logged pack data over UART and MQTT."},
        )

        resume, _ = ApplicationMaterial.objects.update_or_create(
            user=user,
            name="Software intern resume",
            defaults={"material_type": MaterialType.RESUME, "track": software, "notes": "General SWE version"},
        )
        ApplicationMaterial.objects.update_or_create(
            user=user,
            name="Embedded resume",
            defaults={"material_type": MaterialType.RESUME, "track": embedded, "notes": "Career fair systems version"},
        )

        SavedTemplate.objects.update_or_create(
            user=user,
            name="Recruiter follow-up",
            defaults={
                "template_type": "message",
                "body": "Hi {name}, thank you for speaking with me at the career fair about the intern role. I attached my resume and would welcome a referral if appropriate.",
            },
        )

        today = timezone.localdate()
        job = Opportunity.objects.filter(user=user, company="Northwind Semiconductors").first()
        if not job:
            job = Opportunity.objects.create(
                user=user,
                title="Embedded Software Intern",
                company="Northwind Semiconductors",
                url="https://example.com/jobs/embedded-intern",
                source=Source.CAREER_FAIR,
                location="Austin, TX",
                work_arrangement=WorkArrangement.HYBRID,
                role_type=RoleType.INTERNSHIP,
                deadline=today + timedelta(days=12),
                description=(
                    "Requirements:\n- C\n- Python\n- Linux\nPreferred:\n- RTOS\n- Git\n"
                    "Internship for students graduating next year. Visa sponsorship appears available."
                ),
                selected_track=embedded,
                sponsorship_status=SponsorshipStatus.APPEARS_AVAILABLE,
            )
            initialize_opportunity(job, "C\nPython\nLinux", "RTOS\nGit")
        snapshot_materials(job, [resume.pk])
        change_status(job, OpportunityStatus.APPLIED, "Submitted via company portal")

        contact, _ = Contact.objects.update_or_create(
            user=user,
            name="Jordan Blake",
            defaults={
                "organization": "Northwind Semiconductors",
                "role_title": "University recruiter",
                "relationship": Relationship.RECRUITER,
                "opportunity": job,
                "next_follow_up": today + timedelta(days=3),
                "channel": "email",
            },
        )
        ContactInteraction.objects.get_or_create(
            contact=contact,
            notes="Met at career fair. Asked about lab courses.",
            defaults={"channel": "in person"},
        )
        Task.objects.get_or_create(
            user=user,
            title="Follow up with Jordan",
            defaults={"opportunity": job, "contact": contact, "due_date": today - timedelta(days=1), "task_type": "follow_up"},
        )
        stage, _ = InterviewStage.objects.get_or_create(
            opportunity=job,
            stage_name="Recruiter screen",
            defaults={"format": "Video", "next_step": "Wait for OA"},
        )
        InterviewNote.objects.get_or_create(
            stage=stage,
            note_type="behavioral",
            defaults={"content": "Prepare a STAR story about debugging a flaky sensor."},
        )

        second = Opportunity.objects.filter(user=user, company="Harbor Apps").first()
        if not second:
            second = Opportunity.objects.create(
                user=user,
                title="Backend Intern",
                company="Harbor Apps",
                url="https://example.com/jobs/backend-intern",
                source=Source.LINKEDIN,
                location="Remote",
                work_arrangement=WorkArrangement.REMOTE,
                role_type=RoleType.INTERNSHIP,
                description="Requirements:\n- Python\n- Django\n- SQL\nDoes not sponsor visas.",
                selected_track=software,
                sponsorship_status=SponsorshipStatus.NOT_AVAILABLE,
            )
            initialize_opportunity(second, "Python\nDjango\nSQL", "Docker")

        self.stdout.write(self.style.SUCCESS("Demo user: demo / DemoPass123!"))
        if not created:
            self.stdout.write("Existing demo user was updated.")
