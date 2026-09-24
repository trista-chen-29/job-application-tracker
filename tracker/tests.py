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


SAMPLE_README = """
<h2>Software Engineering Internship Roles</h2>
<table>
<thead><tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th><th>Age</th></tr></thead>
<tbody>
<tr>
<td><strong><a href="https://simplify.jobs/c/Acme">Acme</a></strong></td>
<td>Software Engineer Intern</td>
<td>Austin, TX</td>
<td><a href="https://boards.greenhouse.io/acme/jobs/123?utm_source=Simplify">Apply</a></td>
<td>0d</td>
</tr>
<tr>
<td>↳</td>
<td>Firmware Intern</td>
<td>Remote</td>
<td><a href="https://boards.greenhouse.io/acme/jobs/124">Apply</a></td>
<td>1d</td>
</tr>
</tbody>
</table>
"""


class SheetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sheet", "sheet@example.com", "pass12345")
        self.client.force_login(self.user)

    def test_home_is_gmail_to_sheet(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gmail")
        self.assertContains(response, "Google Sheet")

    def test_quick_add_and_inline_status(self):
        add = self.client.post(reverse("opportunity_list"), {"company": "Globex", "title": "Intern", "url": "https://example.com/job", "status": "applied"})
        self.assertEqual(add.status_code, 302)
        opp = Opportunity.objects.get(user=self.user)
        self.assertEqual(opp.status, OpportunityStatus.APPLIED)
        changed = self.client.post(reverse("opportunity_status", args=[opp.pk]), {"status": "interviewing"})
        self.assertEqual(changed.status_code, 302)
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.INTERVIEWING)


class SimplifyFeedTests(TestCase):
    def test_parser_reads_company_role_and_nested_rows(self):
        from tracker.services.simplify import parse_listings, sync_listings

        rows = parse_listings(SAMPLE_README)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].company, "Acme")
        self.assertEqual(rows[0].title, "Software Engineer Intern")
        self.assertIn("greenhouse.io", rows[0].apply_url)
        self.assertEqual(rows[1].company, "Acme")
        self.assertEqual(rows[1].title, "Firmware Intern")
        result = sync_listings(SAMPLE_README)
        self.assertEqual(result["created"], 2)

    def test_save_opening_to_sheet(self):
        from tracker.services.simplify import sync_listings
        from tracker.models import SimplifyListing

        sync_listings(SAMPLE_README)
        listing = SimplifyListing.objects.get(title="Software Engineer Intern")
        self.client.force_login(User.objects.create_user("feed", "feed@example.com", "pass12345"))
        response = self.client.post(reverse("opening_save", args=[listing.pk]), {"applied": "1"})
        self.assertEqual(response.status_code, 302)
        opp = Opportunity.objects.get(simplify_key=listing.listing_key)
        self.assertEqual(opp.company, "Acme")
        self.assertEqual(opp.status, OpportunityStatus.APPLIED)


class MailParseTests(TestCase):
    def test_applied_email_creates_row(self):
        from tracker.services.mailparse import apply_mail_hints, parse_pasted_emails

        user = User.objects.create_user("mail", "mail@example.com", "pass12345")
        raw = (
            "From: Stripe Recruiting <university@stripe.com>\n"
            "Subject: Thank you for applying to Stripe\n\n"
            "We have received your application for the Software Engineer Intern role.\n"
        )
        hints = parse_pasted_emails(raw)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0].status, OpportunityStatus.APPLIED)
        result = apply_mail_hints(user, hints)
        self.assertEqual(result["created"], 1)
        opp = Opportunity.objects.get(user=user)
        self.assertEqual(opp.company, "Stripe")
        self.assertEqual(opp.title, "Software Engineer Intern")
        self.assertEqual(opp.status, OpportunityStatus.APPLIED)

    def test_graphcore_confirmation_uses_company_and_role_from_body(self):
        from tracker.services.mailparse import parse_message

        hint = parse_message(
            "no-reply@graphcore.ai",
            "Thank you for applying to Graphcore",
            (
                "Dear Yi-Chi,\n\nThank you for your interest in Graphcore. This email is to confirm "
                "that we have received your application for the position of  Firmware Engineering Intern . "
                "We will be reviewing your details in due course.\n\nBest wishes,\nGraphcore Talent Acquisition Team"
            ),
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.company, "Graphcore")
    def test_html_only_email_is_read_from_inside_the_message(self):
        import base64

        from tracker.services.gmail import _decode_parts
        from tracker.services.mailparse import parse_message

        html = (
            "<html><body><p>Dear Yi-Chi,</p><p>Thank you for applying to Graphcore. "
            "We have received your application for the position of Firmware Engineering Intern.</p></body></html>"
        )
        encoded = base64.urlsafe_b64encode(html.encode()).decode()
        body = _decode_parts({"mimeType": "text/html", "body": {"data": encoded}})
        self.assertIn("Firmware Engineering Intern", body)
        hint = parse_message("no-reply@graphcore.ai", "Thank you for applying to Graphcore", body)
        self.assertEqual(hint.company, "Graphcore")
        self.assertEqual(hint.title, "Firmware Engineering Intern")

    def test_later_email_updates_existing_row(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("mail2", "mail2@example.com", "pass12345")
        Opportunity.objects.create(user=user, company="Northwind", title="Intern", status=OpportunityStatus.APPLIED)
        hint = parse_message(
            "Northwind University <campus@northwind.com>",
            "Online assessment invitation",
            "Please complete the HackerRank online assessment this week.",
        )
        self.assertIsNotNone(hint)
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(Opportunity.objects.get(user=user).status, OpportunityStatus.ONLINE_ASSESSMENT)

    def test_confirmation_with_interview_word_stays_applied(self):
        from tracker.services.mailparse import parse_message

        hint = parse_message(
            "Acme Recruiting <jobs@acme.com>",
            "Thank you for applying to Acme",
            "We received your application. Next steps in our interview process will follow.",
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.status, OpportunityStatus.APPLIED)

    def test_later_status_email_updates_same_company_row(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("mail7", "mail7@example.com", "pass12345")
        Opportunity.objects.create(
            user=user, company="Graphcore", title="Firmware Engineering Intern", status=OpportunityStatus.APPLIED
        )
        hint = parse_message(
            "no-reply@graphcore.ai",
            "Graphcore online assessment",
            "Please complete the HackerRank online assessment for Firmware Engineering Intern.",
        )
        self.assertEqual(hint.status, OpportunityStatus.ONLINE_ASSESSMENT)
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(Opportunity.objects.filter(user=user).count(), 1)
        self.assertEqual(Opportunity.objects.get(user=user).status, OpportunityStatus.ONLINE_ASSESSMENT)

    def test_better_title_corrects_generic_intern_row(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("mail8", "mail8@example.com", "pass12345")
        Opportunity.objects.create(user=user, company="Graphcore", title="Intern", status=OpportunityStatus.APPLIED)
        hint = parse_message(
            "no-reply@graphcore.ai",
            "Thank you for applying to Graphcore",
            "We have received your application for the position of Firmware Engineering Intern.",
        )
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(Opportunity.objects.get(user=user).title, "Firmware Engineering Intern")

    def test_short_company_name_does_not_attach_to_unrelated_row(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("mail3", "mail3@example.com", "pass12345")
        Opportunity.objects.create(user=user, company="Google", title="SWE Intern", status=OpportunityStatus.SAVED)
        hint = parse_message(
            "Go Team <campus@go.com>",
            "Thank you for applying to Go",
            "We have received your application for the intern role.",
        )
        self.assertIsNotNone(hint)
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["created"], 1)
        self.assertEqual(Opportunity.objects.filter(user=user).count(), 2)
        self.assertEqual(Opportunity.objects.get(user=user, company="Google").status, OpportunityStatus.SAVED)

    def test_rejection_does_not_overwrite_offer(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("mail4", "mail4@example.com", "pass12345")
        Opportunity.objects.create(user=user, company="Harbor", title="Intern", status=OpportunityStatus.OFFER)
        hint = parse_message(
            "Harbor Recruiting <jobs@harbor.com>",
            "Update",
            "Unfortunately we are not moving forward.",
        )
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(Opportunity.objects.get(user=user).status, OpportunityStatus.OFFER)

    def test_offer_email_can_replace_rejection(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("mail6", "mail6@example.com", "pass12345")
        Opportunity.objects.create(user=user, company="Harbor", title="Intern", status=OpportunityStatus.REJECTED)
        hint = parse_message(
            "Harbor Recruiting <jobs@harbor.com>",
            "Offer of employment",
            "We are pleased to offer you an intern role.",
        )
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(Opportunity.objects.get(user=user).status, OpportunityStatus.OFFER)

    def test_duplicate_clears_simplify_key(self):
        from tracker.services.workflow import duplicate_opportunity

        user = User.objects.create_user("dupkey", "dupkey@example.com", "pass12345")
        opp = Opportunity.objects.create(
            user=user,
            company="Acme",
            title="Intern",
            simplify_key="abc123",
            status=OpportunityStatus.APPLIED,
        )
        clone = duplicate_opportunity(opp)
        self.assertEqual(clone.simplify_key, "")
        opp.refresh_from_db()
        self.assertEqual(opp.simplify_key, "abc123")

    def test_gmail_paste_fills_sheet(self):
        user = User.objects.create_user("mail5", "mail5@example.com", "pass12345")
        self.client.force_login(user)
        raw = (
            "From: Persona AI <university@persona.ai>\n"
            "Subject: Thank you for applying to Persona AI\n\n"
            "We have received your application for the intern role.\n"
        )
        response = self.client.post(reverse("gmail_connect"), {"pasted": raw})
        self.assertEqual(response.status_code, 302)
        opp = Opportunity.objects.get(user=user)
        self.assertEqual(opp.status, OpportunityStatus.APPLIED)


class GoogleSheetFillTests(TestCase):
    def test_spreadsheet_id_from_share_link(self):
        from tracker.services.gsheet import spreadsheet_id_from_url

        url = "https://docs.google.com/spreadsheets/d/1fm93wHklieth-pt8Uk2xDwzKkDGVGEc9JiR_3mrOh2o/edit?gid=0#gid=0"
        self.assertEqual(spreadsheet_id_from_url(url), "1fm93wHklieth-pt8Uk2xDwzKkDGVGEc9JiR_3mrOh2o")

    def test_intern_confirmation_fills_first_empty_internships_row(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail, upsert_plan

        rows = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["", "", "", "", "Summer 2027", "Applied", ""],
            ["", "", "", "", "Summer 2027", "Applied", ""],
        ]
        hint = hint_from_mail(
            "Stripe",
            "Software Engineer Intern",
            OpportunityStatus.APPLIED,
            "From email: Thank you for applying to Stripe",
            "We have received your application. Location: New York, NY",
            "2026-09-24",
        )
        self.assertEqual(hint.tab, "internships")
        self.assertEqual(hint.result, "Applied")
        self.assertEqual(hint.location, "New York, NY")
        plan = upsert_plan(rows, hint)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(plan["row"], 2)

    def test_new_grad_goes_to_newgrad_tab(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail

        hint = hint_from_mail(
            "Acme",
            "Software Engineer New Grad",
            OpportunityStatus.APPLIED,
            "note",
            "Thanks for applying to our new grad program.",
        )
        self.assertEqual(hint.tab, "newgrad")

    def test_rejection_does_not_replace_offer_on_sheet(self):
        from tracker.services.gsheet import SheetHint, upsert_plan

        rows = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["2026-09-01", "Harbor", "Intern", "", "Summer 2027", "Offer", ""],
        ]
        hint = SheetHint(
            company="Harbor",
            role="Intern",
            location="",
            tab="internships",
            result="Rejected",
            notes="Unfortunately",
            date_applied="2026-09-24",
        )
    def test_merged_row_keeps_offer_and_upgrades_title(self):
        from tracker.services.gsheet import SheetHint, _merged_row

        headers = ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]
        existing = ["2026-09-01", "Graphcore", "Intern", "", "Summer 2027", "Offer", ""]
        hint = SheetHint(
            company="Graphcore",
            role="Firmware Engineering Intern",
            location="",
            tab="internships",
            result="Applied",
            notes="From email: Thank you",
            date_applied="2026-09-24",
        )
        merged = _merged_row(headers, hint, existing, "internships")
        self.assertEqual(merged[1], "Graphcore")
        self.assertEqual(merged[2], "Firmware Engineering Intern")
        self.assertEqual(merged[5], "Offer")

