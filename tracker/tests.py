from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tracker.constants import MatchCategory, OpportunityStatus, SponsorshipPreference, SponsorshipStatus
from tracker.models import Opportunity, ProfileTrack, StatusHistory, Task
from tracker.services import ensure_profile
from tracker.services.analytics import conversion, dashboard_metrics
from tracker.services.duplicates import find_duplicates
from tracker.services.matching import score_opportunity
from tracker.services.skills import replace_opportunity_skills, replace_track_skills
from tracker.services.workflow import change_status, initialize_opportunity, snapshot_materials


class AuthTests(TestCase):
    def test_register_login_logout_and_delete(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "sam",
                "email": "sam@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="sam").exists())
        self.client.logout()
        logged = self.client.post(reverse("login"), {"username": "sam", "password": "StrongPass123!"})
        self.assertEqual(logged.status_code, 302)
        deleted = self.client.post(reverse("account"), {"confirm": "DELETE"})
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(User.objects.filter(username="sam").exists())

    def test_private_pages_require_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


class OwnershipTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user("a", "a@example.com", "pass12345")
        self.b = User.objects.create_user("b", "b@example.com", "pass12345")
        self.opp = Opportunity.objects.create(user=self.a, title="Intern", company="Acme")

    def test_user_cannot_view_or_mutate_another_users_opportunity(self):
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse("opportunity_detail", args=[self.opp.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("opportunity_status", args=[self.opp.pk]), {"status": "applied"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("opportunity_brief", args=[self.opp.pk])).status_code, 404)


class MatchingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("m", "m@example.com", "pass12345")
        self.profile = ensure_profile(self.user)
        self.profile.sponsorship_preference = SponsorshipPreference.REQUIRED
        self.profile.preferred_role_categories = "Software"
        self.profile.save()
        self.track = ProfileTrack.objects.create(profile=self.profile, name="Software", keywords="python intern")
        replace_track_skills(self.track, "Python\nDjango\nSQL")

    def test_required_skill_overlap_and_explainable_payload(self):
        opp = Opportunity.objects.create(
            user=self.user,
            title="Python intern",
            company="Globex",
            selected_track=self.track,
            sponsorship_status=SponsorshipStatus.USER_VERIFIED,
        )
        replace_opportunity_skills(opp, "Python\nDjango\nFPGA", "SQL")
        result = score_opportunity(opp, self.profile, self.track)
        self.assertIn("Python", " ".join(result.strengths))
        self.assertTrue(any("FPGA" in item for item in result.missing))
        self.assertIsNotNone(result.score)
        self.assertIn(result.category, {MatchCategory.STRONG, MatchCategory.POSSIBLE, MatchCategory.WEAK})
        self.assertTrue(result.why)

    def test_unknown_sponsorship_is_omitted(self):
        opp = Opportunity.objects.create(
            user=self.user,
            title="Python intern",
            company="Initech",
            selected_track=self.track,
            sponsorship_status=SponsorshipStatus.UNKNOWN,
        )
        replace_opportunity_skills(opp, "Python", "")
        result = score_opportunity(opp, self.profile, self.track)
        spons = next(item for item in result.components if item.key == "sponsorship")
        self.assertFalse(spons.included)
        self.assertIsNone(spons.score)
        self.assertTrue(any("unknown" in item.lower() for item in result.uncertain))


class StatusTests(TestCase):
    def test_status_change_writes_history_and_application(self):
        user = User.objects.create_user("s", "s@example.com", "pass12345")
        opp = Opportunity.objects.create(user=user, title="Role", company="Co")
        change_status(opp, OpportunityStatus.APPLIED, "portal")
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.APPLIED)
        self.assertEqual(StatusHistory.objects.filter(opportunity=opp, to_status=OpportunityStatus.APPLIED).count(), 1)
        self.assertIsNotNone(opp.application.applied_at)


class DuplicateTests(TestCase):
    def test_same_url_is_duplicate(self):
        user = User.objects.create_user("d", "d@example.com", "pass12345")
        Opportunity.objects.create(user=user, title="A", company="Co", url="https://jobs.example/1")
        found = find_duplicates(user, title="Other", company="Else", url="https://jobs.example/1", description="")
        self.assertEqual(len(found), 1)

    def test_same_company_and_title_is_duplicate(self):
        user = User.objects.create_user("d2", "d2@example.com", "pass12345")
        Opportunity.objects.create(user=user, title="Firmware Intern", company="Northwind")
        found = find_duplicates(user, title="Firmware Intern", company="Northwind", url="", description="")
        self.assertEqual(len(found), 1)


class AnalyticsTests(TestCase):
    def test_not_enough_data_below_sample_size(self):
        result = conversion(1, 2)
        self.assertEqual(result["label"], "Not enough data")
        self.assertIsNone(result["value"])

    def test_rate_when_sample_is_large_enough(self):
        result = conversion(2, 5)
        self.assertEqual(result["value"], 40.0)

    def test_dashboard_counts_are_user_scoped(self):
        a = User.objects.create_user("aa", "aa@example.com", "pass12345")
        b = User.objects.create_user("bb", "bb@example.com", "pass12345")
        Opportunity.objects.create(user=a, title="One", company="A")
        Opportunity.objects.create(user=b, title="Two", company="B")
        metrics = dashboard_metrics(a)
        self.assertEqual(sum(metrics["by_status"].values()), 1)


class WorkflowPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("w", "w@example.com", "pass12345")
        self.client.force_login(self.user)
        ensure_profile(self.user)

    def test_create_opportunity_and_task_and_export(self):
        response = self.client.post(
            reverse("opportunity_create"),
            {
                "title": "Intern",
                "company": "Acme",
                "url": "https://example.com/job",
                "description": "Requirements:\n- Python\n",
                "source": "other",
                "work_arrangement": "unknown",
                "role_type": "internship",
                "sponsorship_status": "unknown",
                "priority": "medium",
            },
        )
        self.assertEqual(response.status_code, 302)
        opp = Opportunity.objects.get(user=self.user)
        self.assertTrue(opp.checklist_items.exists())
        self.client.post(reverse("tasks"), {"title": "Follow up", "priority": "high", "task_type": "follow_up", "opportunity": opp.pk})
        self.assertTrue(Task.objects.filter(user=self.user, title="Follow up").exists())
        export = self.client.get(reverse("export_download", args=["opportunities"]))
        self.assertEqual(export.status_code, 200)
        self.assertIn(b"Acme", export.content)
        brief = self.client.get(reverse("opportunity_brief", args=[opp.pk]))
        self.assertEqual(brief.status_code, 200)
        self.assertIn(b"Acme", brief.content)
