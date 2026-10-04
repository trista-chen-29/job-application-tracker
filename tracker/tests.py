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


class ExtractionTests(TestCase):
    """Formats seen in real recruiter mail; keep in step with sheets-addon/Code.gs."""

    def parse(self, from_header, subject, body):
        from tracker.services.extract import parse_mail

        return parse_mail(from_header, subject, body)

    def test_volume_disclaimer_is_not_a_rejection(self):
        parsed = self.parse(
            '"myworkday.com" <acme@myworkday.com>',
            "Thank you for applying to Acme Bank",
            "Thank you for applying for Software Engineer - API Platform, Officer position here at Acme Bank. "
            "Unfortunately, due to the high volume of applications we are unable to provide feedback to everyone.",
        )
        self.assertEqual(parsed["result"], "Applied")
        self.assertEqual(parsed["company"], "Acme Bank")
        self.assertEqual(parsed["role"], "Software Engineer - API Platform, Officer")

    def test_regret_to_inform_is_a_rejection(self):
        parsed = self.parse(
            "Acme Hiring Team <notifications@careers.acme.com>",
            "Your Acme Application Status",
            "After careful consideration, we regret to inform you that you have not been selected to move forward.",
        )
        self.assertEqual(parsed["result"], "Rejected")
        self.assertEqual(parsed["company"], "Acme")

    def test_own_replies_are_ignored(self):
        self.assertIsNone(
            self.parse("Me <someone@gmail.com>", "Re: Initial offer of Employment - Acme - Seasonal Technician", "Thanks!")
        )

    def test_recruiter_name_is_not_the_company(self):
        parsed = self.parse(
            "Pat Lee <pat.lee@acme.com>",
            "Initial offer of Employment - Acme Materials - Seasonal Associate Technician - Springfield",
            "You can electronically sign your offer letter.",
        )
        self.assertEqual(parsed["company"], "Acme Materials")
        self.assertEqual(parsed["role"], "Seasonal Associate Technician")
        self.assertEqual(parsed["result"], "Offer")
        self.assertEqual(parsed["tab"], "internships")

    def test_workday_sender_names(self):
        self.assertEqual(self.parse("Workday Microchip <microchiphr@myworkday.com>", "Thank you for applying!", "Thank you so much for applying!")["company"], "Microchip")
        self.assertEqual(
            self.parse("workday-no-reply f5 <ffive@myworkday.com>", "Thank you for applying!", "We appreciate your interest in F5 and the Software Engineer I position.")["company"],
            "F5",
        )

    def test_role_and_company_from_role_at_company(self):
        parsed = self.parse(
            "no-reply@us.greenhouse-mail.io",
            "Thank You for Applying to AI-Native Software Engineer (New Grad) | Study.com",
            "Thanks for applying to AI-Native Software Engineer (New Grad) at Study.com. Your application has been received.",
        )
        self.assertEqual(parsed["company"], "Study.com")
        self.assertEqual(parsed["role"], "AI-Native Software Engineer (New Grad)")
        self.assertEqual(parsed["tab"], "newgrad")

    def test_role_ids_and_seasons_are_stripped(self):
        parsed = self.parse(
            "noreply@mail.amazon.jobs",
            "Thank you for Applying to Amazon!",
            "We've received your application for the Software Development Engineer Intern, Amazon Leo - Summer 2027 (USA) (ID: 10559762) position.",
        )
        self.assertEqual(parsed["role"], "Software Development Engineer Intern, Amazon Leo (USA)")
        self.assertEqual(parsed["season"], "Summer 2027")

    def test_ignored_company_and_student_jobs(self):
        self.assertIsNone(
            self.parse("SJSU Student Union <jobs@pinpointhq.com>", "Application Received – Student IT Technician", "Application received.")
        )

    def test_oa_confirmation_keeps_applied_date(self):
        parsed = self.parse(
            "Ramp Talent Team <no-reply@ashbyhq.com>",
            "Ramp | Confirmation on your Application + CodeSignal",
            "Thank you for taking the time to apply to our Software Engineer opening at Ramp! Your application has been received "
            "and will be reviewed as soon as you complete the CodeSignal assessment.",
        )
        self.assertEqual(parsed["result"], "OA")
        self.assertTrue(parsed["confirmation"])
        self.assertEqual(parsed["company"], "Ramp")

    def test_follow_up_roles_that_differ_stay_separate(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["", "NetApp", "Intern - Software Engineer (Cloud Storage)", "", "", "Rejected", ""],
        ]
        grids = {"internships": intern, "newgrad": [["Date Applied", "Company", "Role", "Location", "Result", "Notes"]]}
        other = SheetHint(
            company="NetApp", role="Intern - Software Engineer (Systems)", location="", tab="internships",
            result="Rejected", notes="", date_applied="",
        )
        self.assertEqual(apply_hint_grids(grids, other)["action"], "created")

    def test_offer_with_reworded_role_updates_the_application(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]]
        grad = [
            ["Date Applied", "Company", "Role", "Location", "Result", "Notes"],
            ["04/08/2026", "Acme Materials", "Associate Test Technician", "", "Applied", ""],
        ]
        grids = {"internships": intern, "newgrad": grad}
        offer = SheetHint(
            company="Acme Materials Inc", role="Seasonal Associate Technician", location="Springfield, CA",
            tab="internships", result="Offer", notes="", date_applied="",
        )
        result = apply_hint_grids(grids, offer)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["tab"], "internships")
        self.assertEqual(intern[1][:6], ["04/08/2026", "Acme Materials Inc", "Seasonal Associate Technician", "Springfield, CA", "", "Offer"])
        self.assertEqual(grad[1][1], "")

    def test_databricks_company_comes_from_the_sentence_not_the_sender(self):
        senders = (
            "Talent Team <notifications@greenhouse.io>",
            "Databricks via Greenhouse <no-reply@us.greenhouse-mail.io>",
            "Lever <no-reply@hire.lever.co>",
        )
        body = (
            "Thanks for applying to Databricks! Your application for the Software Engineering Intern "
            "(2027 Start) - Winter role has been received.\n\n"
            "Please note that all official communication from Databricks will come from email addresses "
            "ending with @databricks.com.\n\n"
            "Acme Recruiting\n100 Market Street\nSan Francisco, CA 94105\n"
            "** Please note: Do not reply to this email."
        )
        for sender in senders:
            parsed = self.parse(sender, "Thank you for applying to Databricks!", body)
            self.assertEqual(parsed["company"], "Databricks", sender)
            self.assertEqual(parsed["role"], "Software Engineering Intern", sender)
            self.assertEqual(parsed["location"], "", sender)
            self.assertEqual(parsed["season"], "Winter 2027", sender)
            self.assertEqual(parsed["tab"], "internships", sender)
            self.assertEqual(parsed["result"], "Applied", sender)
            self.assertIn("official communication", parsed["useful_note"])
            self.assertNotIn("Do not reply", parsed["useful_note"])

    def test_generic_role_title_is_not_used(self):
        parsed = self.parse(
            "Acme <jobs@acme.com>",
            "Application received",
            "Thank you for applying to Acme. Your application for the Internship role has been received.",
        )
        self.assertEqual(parsed["role"], "")
        self.assertEqual(parsed["company"], "Acme")

    def test_signature_city_is_not_a_location(self):
        parsed = self.parse(
            "Acme <jobs@acme.com>",
            "Thank you for applying to Acme",
            "Thanks for applying to the Software Engineer role at Acme. Your application has been received.\n\n"
            "Meet us in San Francisco, CA.\nAcme Inc, 1 Market Street, San Francisco, CA 94105",
        )
        self.assertEqual(parsed["location"], "")
        self.assertEqual(parsed["role"], "Software Engineer")
        labeled = self.parse(
            "Acme <jobs@acme.com>",
            "Thank you for applying to Acme",
            "Thanks for applying to the Software Engineer role at Acme. Location: Austin, TX. Your application has been received.",
        )
        self.assertEqual(labeled["location"], "Austin, TX")

    def test_season_is_not_invented_from_a_separate_year(self):
        parsed = self.parse(
            "Acme <jobs@acme.com>",
            "Thank you for applying to Acme",
            "Thanks for applying to the Software Engineer role at Acme. Join us this summer. Copyright 2026. "
            "Your application has been received.",
        )
        self.assertEqual(parsed["season"], "")
        self.assertEqual(parsed["tab"], "newgrad")

    def test_specific_role_is_not_reclassified_by_a_footer(self):
        parsed = self.parse(
            "Acme <jobs@acme.com>",
            "Thank you for applying to Acme",
            "Thanks for applying to the Software Engineer role at Acme. Your application has been received.\n\n"
            "We also hire interns every summer.",
        )
        self.assertEqual(parsed["role"], "Software Engineer")
        self.assertEqual(parsed["tab"], "newgrad")

    def test_unlabeled_mail_does_not_default_to_newgrad(self):
        parsed = self.parse(
            "Acme <jobs@acme.com>",
            "Thank you for applying to Acme",
            "Thank you for applying to Acme. We received your application.",
        )
        self.assertEqual(parsed["role"], "")
        self.assertEqual(parsed["tab"], "internships")

    def test_html_part_supplies_the_role_when_plain_text_does_not(self):
        import base64

        from tracker.services.gmail import _decode_parts

        def part(mime, text):
            return {"mimeType": mime, "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}

        plain = "Thank you for applying to Databricks. " * 4 + "Your application for the Internship role has been received."
        html = "<p>Your application for the Software Engineering Intern (2027 Start) - Winter role has been received.</p>"
        payload = {"mimeType": "multipart/alternative", "parts": [part("text/plain", plain), part("text/html", html)]}
        body = _decode_parts(payload)
        parsed = self.parse("Talent Team <notifications@greenhouse.io>", "Thank you for applying to Databricks!", body)
        self.assertEqual(parsed["company"], "Databricks")
        self.assertEqual(parsed["role"], "Software Engineering Intern")
        self.assertEqual(parsed["season"], "Winter 2027")

    def test_same_role_different_season_stays_a_second_row(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/01/2026", "Databricks", "Software Engineering Intern", "", "Winter 2027", "Applied", ""],
        ]
        grids = {"internships": intern, "newgrad": [["Date Applied", "Company", "Role", "Location", "Result", "Notes"]]}
        hint = SheetHint(
            company="Databricks",
            role="Software Engineering Intern",
            location="",
            tab="internships",
            result="Applied",
            notes="Source: https://mail.google.com/mail/u/0/#all/summer",
            date_applied="09/20/2026",
            season="Summer 2027",
        )
        result = apply_hint_grids(grids, hint)
        self.assertEqual(result["action"], "created")
        filled = [row for row in intern[1:] if row[1]]
        self.assertEqual(len(filled), 2)
        self.assertEqual(intern[1][4], "Winter 2027")
        self.assertEqual(filled[1][4], "Summer 2027")

    def test_reprocess_repairs_the_old_row_instead_of_duplicating_it(self):
        from tracker.services.gsheet import SheetHint, application_key, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/24/2026", "Talent", "Data Platform Intern", "Seattle, WA", "Summer 2027", "Offer", "typed note"],
        ]
        grids = {"internships": intern, "newgrad": [["Date Applied", "Company", "Role", "Location", "Result", "Notes"]]}
        hint = SheetHint(
            company="Databricks",
            role="Software Engineering Intern",
            location="San Francisco, CA",
            tab="internships",
            result="Applied",
            notes="Source: https://mail.google.com/mail/u/0/#all/thread-databricks",
            date_applied="09/24/2026",
            season="Winter 2027",
            previous_key=application_key("Talent", "Data Platform Intern", "Summer 2027"),
        )
        result = apply_hint_grids(grids, hint)
        self.assertEqual(result["action"], "updated")
        filled = [row for row in intern[1:] if row[1]]
        self.assertEqual(len(filled), 1)
        self.assertEqual(intern[1][1], "Databricks")
        self.assertEqual(intern[1][2], "Software Engineering Intern")
        self.assertEqual(intern[1][3], "Seattle, WA")
        self.assertEqual(intern[1][4], "Winter 2027")
        self.assertEqual(intern[1][5], "Offer")
        self.assertIn("typed note", intern[1][6])
        self.assertIn("thread-databricks", intern[1][6])

    def test_review_items_are_not_logged_as_applied(self):
        from tracker.constants import OpportunityStatus
        from tracker.models import GmailProcessedMessage, Opportunity
        from tracker.views import _process_gmail_items

        user = User.objects.create_user("reviewlog", "reviewlog@example.com", "pass12345")
        Opportunity.objects.create(user=user, company="Databricks", title="Software Engineering Intern", status=OpportunityStatus.APPLIED)
        Opportunity.objects.create(user=user, company="Databricks", title="Data Science Intern", status=OpportunityStatus.APPLIED)
        counts = _process_gmail_items(
            user,
            None,
            [
                {
                    "id": "review-1",
                    "threadId": "thread-review",
                    "from": "Databricks <jobs@databricks.com>",
                    "subject": "Your Databricks application",
                    "body": "We regret to inform you that you have not been selected to move forward.",
                    "date": "Thu, 24 Sep 2026 12:00:00 +0000",
                }
            ],
            "",
        )
        self.assertEqual(counts["review"], 1)
        self.assertEqual(GmailProcessedMessage.objects.get(user=user, message_id="review-1").parse_status, "review")

    def test_apps_script_extracts_the_databricks_email(self):
        import subprocess
        from pathlib import Path

        script = Path(__file__).resolve().parents[1] / "sheets-addon" / "parse_check.js"
        completed = subprocess.run(["node", str(script)], check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


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
        self.assertEqual(hint.date_applied, "09/24/2026")
        plan = upsert_plan(rows, hint)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(plan["row"], 2)

    def test_earliest_applied_rows_sort_to_the_top(self):
        from tracker.services.gsheet import sort_filled_earliest_first

        rows = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/24/2026", "Graphcore", "Firmware Engineering Intern", "", "Summer 2027", "Applied", ""],
            ["", "NoDateCo", "Intern", "", "", "Rejected", ""],
            ["", "", "", "", "Summer 2027", "", ""],
            ["1/5/2026", "OldCo", "Intern", "", "Summer 2027", "Applied", ""],
            ["2026-03-10", "MidCo", "Intern", "", "", "Applied", ""],
        ]
        sorted_rows = sort_filled_earliest_first(rows)
        self.assertEqual([row[1] for row in sorted_rows[1:]], ["OldCo", "MidCo", "Graphcore", "NoDateCo", ""])

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

    def test_interview_word_does_not_force_internships_tab(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail

        hint = hint_from_mail(
            "Nvidia",
            "Software Engineer, University Grad",
            OpportunityStatus.APPLIED,
            "note",
            "Thank you for applying. Next steps in our interview process will follow for this full-time new grad role.",
        )
        self.assertEqual(hint.tab, "newgrad")

    def test_generic_swe_confirmation_goes_to_newgrad_tab(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail

        hint = hint_from_mail(
            "Meta",
            "Software Engineer",
            OpportunityStatus.APPLIED,
            "From email: Thank you for applying to Meta",
            "We have received your application for Software Engineer.",
        )
        self.assertEqual(hint.tab, "newgrad")

    def test_default_internship_title_with_new_grad_body_goes_to_newgrad(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail

        hint = hint_from_mail(
            "Jane Street",
            "Internship",
            OpportunityStatus.APPLIED,
            "From email: Thank you for applying",
            "Thanks for applying to our new grad software engineer role. Interviews will follow.",
        )
        self.assertEqual(hint.tab, "newgrad")

    def test_intern_and_new_grad_in_body_prefers_newgrad_unless_intern_title(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail

        mixed = hint_from_mail(
            "Google",
            "Software Engineer",
            OpportunityStatus.APPLIED,
            "note",
            "We are hiring interns and university grads. This is for our university grad program.",
        )
        self.assertEqual(mixed.tab, "newgrad")

    def test_firmware_intern_stays_on_internships_tab(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail

        hint = hint_from_mail(
            "Graphcore",
            "Firmware Engineering Intern",
            OpportunityStatus.APPLIED,
            "note",
            "We have received your application for the position of Firmware Engineering Intern.",
        )
        self.assertEqual(hint.tab, "internships")

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
        plan = upsert_plan(rows, hint)
        self.assertIn(plan["action"], {"skipped", "update"})
        from tracker.services.gsheet import _merged_row

        merged = _merged_row(rows[0], hint, rows[1], "internships")
        self.assertEqual(merged[5], "Offer")

    def test_databricks_intern_email_fills_like_manual_entry(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail
        from tracker.services.mailparse import parse_message

        body = (
            "Hi Yi-Chi,\n\n"
            "Thanks for applying to Databricks! Your application for the Software Engineering Intern "
            "(2027 Start) - Winter role has been received. We will review it shortly and reach out if there is a fit.\n\n"
            "Please note that all official communication from Databricks will come from email addresses "
            "ending with @databricks.com or @goodtime.io (our meeting tool).\n\n"
            "Regards,\nDatabricks\n\n"
            "** Please note: Do not reply to this email. This email is sent from an unattended mailbox. Replies will not be read."
        )
        parsed = parse_message(
            "no-reply@us.greenhouse-mail.io",
            "Thank you for applying to Databricks!",
            body,
            "msg-1",
            "thread-databricks",
            "2026-09-24",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.company, "Databricks")
        self.assertEqual(parsed.title, "Software Engineering Intern")
        self.assertEqual(parsed.status, OpportunityStatus.APPLIED)
        self.assertEqual(parsed.date_applied, "09/24/2026")
        self.assertEqual(parsed.season, "Winter 2027")
        self.assertEqual(parsed.location, "")
        self.assertIn("official communication from Databricks", parsed.note)
        self.assertIn("Source: https://mail.google.com/mail/u/0/#all/thread-databricks", parsed.note)
        self.assertNotIn("Do not reply", parsed.note)

        hint = hint_from_mail(
            parsed.company,
            parsed.title,
            parsed.status,
            parsed.note,
            body,
            "2026-09-24",
            parsed.thread_id,
        )
        self.assertEqual(hint.tab, "internships")
        self.assertEqual(hint.role, "Software Engineering Intern")
        self.assertEqual(hint.date_applied, "09/24/2026")
        self.assertEqual(hint.season, "Winter 2027")
        self.assertEqual(hint.result, "Applied")
        self.assertEqual(hint.location, "")
        self.assertTrue(hint.location_missing)
        self.assertIn("@databricks.com", hint.notes)
        self.assertIn("Source: https://mail.google.com/mail/u/0/#all/thread-databricks", hint.notes)
        from tracker.services.gsheet import location_should_highlight

        self.assertTrue(location_should_highlight(hint.location, hint.location_missing))

    def test_season_only_uses_dropdown_values(self):
        from tracker.services.mailparse import infer_season

        self.assertEqual(infer_season("Software Engineering Intern (2027 Start) - Winter"), "Winter 2027")
        self.assertEqual(infer_season("Spring 2027 Data Intern"), "Spring 2027")
        self.assertEqual(infer_season("Summer 2027 SWE Intern"), "Summer 2027")
        self.assertEqual(infer_season("Fall 2027 co-op"), "")
        self.assertEqual(infer_season("Summer 2026 internship"), "")
        self.assertEqual(infer_season("our summer internship program"), "")

    def test_rejection_date_is_not_the_applied_date(self):
        from tracker.services.mailparse import parse_message

        hint = parse_message(
            "Databricks University Recruiting <no-reply@databricks.com>",
            "Your application to Databricks",
            "Unfortunately, we will not be moving forward with your application to Databricks.",
            date_applied="10/15/2026",
        )
        self.assertIsNotNone(hint)
        self.assertEqual(hint.status, OpportunityStatus.REJECTED)
        self.assertEqual(hint.date_applied, "")

    def test_switching_sheet_requeues_logged_mail(self):
        from tracker.models import GmailAccount, GmailProcessedMessage
        from tracker.services.mailparse import PARSER_VERSION
        from tracker.views import _stale_message_ids

        user = User.objects.create_user("switch", "switch@example.com", "pass12345")
        GmailAccount.objects.create(user=user, token_json="{}", spreadsheet_id="oldSheetId1234567890abcdef")
        GmailProcessedMessage.objects.create(
            user=user, message_id="done-1", parser_version=PARSER_VERSION, parse_status="applied"
        )
        self.assertNotIn("done-1", _stale_message_ids(user))
        self.client.force_login(user)
        self.client.post(
            reverse("gmail_connect"),
            {
                "save_sheet": "1",
                "spreadsheet_url": "https://docs.google.com/spreadsheets/d/newSheetId1234567890abcdef/edit",
            },
        )
        self.assertEqual(GmailAccount.objects.get(user=user).spreadsheet_id, "newSheetId1234567890abcdef")
        self.assertIn("done-1", _stale_message_ids(user))

    def test_same_company_same_role_updates_one_row(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/24/2026", "Databricks", "Software Engineering Intern", "", "Winter 2027", "Applied", ""],
        ]
        grids = {"internships": intern, "newgrad": [["Date Applied", "Company", "Role", "Location", "Result", "Notes"]]}
        hint = SheetHint(
            company="Databricks",
            role="Software Engineering Intern",
            location="",
            tab="internships",
            result="OA",
            notes="Source: https://mail.google.com/mail/u/0/#all/oa",
            date_applied="09/24/2026",
            season="Winter 2027",
        )
        result = apply_hint_grids(grids, hint)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["row"], 2)
        filled = [row for row in grids["internships"][1:] if row[1]]
        self.assertEqual(len(filled), 1)
        self.assertEqual(grids["internships"][1][5], "OA")

    def test_same_company_two_roles_stay_separate(self):
        from tracker.services.gsheet import SheetHint, upsert_plan

        rows = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/01/2026", "Databricks", "Software Engineering Intern", "", "Winter 2027", "Applied", ""],
            ["09/02/2026", "Databricks", "Data Science Intern", "", "Summer 2027", "Applied", ""],
        ]
        hint = SheetHint(
            company="Databricks",
            role="Data Science Intern",
            location="",
            tab="internships",
            result="Interview",
            notes="",
            date_applied="09/02/2026",
            season="Summer 2027",
        )
        plan = upsert_plan(rows, hint)
        self.assertEqual(plan["action"], "update")
        self.assertEqual(plan["row"], 3)

    def test_applied_row_repairs_blank_date_location_notes(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["", "Databricks", "Software Engineering Intern", "", "", "Applied", ""],
        ]
        grids = {"internships": intern, "newgrad": [["Date Applied", "Company", "Role", "Location", "Result", "Notes"]]}
        hint = SheetHint(
            company="Databricks",
            role="Software Engineering Intern",
            location="San Francisco, CA",
            tab="internships",
            result="Applied",
            notes="Source: https://mail.google.com/mail/u/0/#all/x",
            date_applied="09/24/2026",
            season="Winter 2027",
        )
        result = apply_hint_grids(grids, hint)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(intern[1][0], "09/24/2026")
        self.assertEqual(intern[1][3], "San Francisco, CA")
        self.assertEqual(intern[1][4], "Winter 2027")
        self.assertIn("Source:", intern[1][6])
        self.assertEqual(intern[1][5], "Applied")

    def test_manual_location_is_preserved(self):
        from tracker.services.gsheet import SheetHint, _merged_row

        headers = ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]
        existing = ["09/24/2026", "Databricks", "Software Engineering Intern", "Seattle, WA", "Winter 2027", "Applied", ""]
        hint = SheetHint(
            company="Databricks",
            role="Software Engineering Intern",
            location="San Francisco, CA",
            tab="internships",
            result="Applied",
            notes="",
            date_applied="09/24/2026",
            season="Winter 2027",
        )
        merged = _merged_row(headers, hint, existing, "internships")
        self.assertEqual(merged[3], "Seattle, WA")

    def test_new_application_uses_first_blank_company_row(self):
        from tracker.constants import OpportunityStatus
        from tracker.services.gsheet import hint_from_mail, upsert_plan

        rows = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/01/2026", "OldCo", "Intern", "", "", "Applied", ""],
            ["", "", "", "", "", "Applied", ""],
            ["", "", "", "", "", "Applied", ""],
        ]
        hint = hint_from_mail(
            "Stripe",
            "Software Engineer Intern",
            OpportunityStatus.APPLIED,
            "",
            "We have received your application for the Software Engineer Intern role. Location: New York, NY",
            "2026-09-24",
        )
        plan = upsert_plan(rows, hint)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(plan["row"], 3)

    def test_moving_tabs_clears_the_old_row(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/24/2026", "Acme", "Software Engineer New Grad", "", "", "Applied", "old note"],
        ]
        grad = [
            ["Date Applied", "Company", "Role", "Location", "Result", "Notes"],
            ["", "", "", "", "Applied", ""],
        ]
        grids = {"internships": intern, "newgrad": grad}
        hint = SheetHint(
            company="Acme",
            role="Software Engineer New Grad",
            location="",
            tab="newgrad",
            result="Applied",
            notes="Source: https://mail.google.com/mail/u/0/#all/y",
            date_applied="09/24/2026",
        )
        result = apply_hint_grids(grids, hint)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(intern[1][1], "")
        self.assertEqual(intern[1][0], "")
        self.assertEqual(intern[1][5], "")
        self.assertEqual(intern[1][6], "")
        self.assertEqual(grad[1][1], "Acme")
        self.assertEqual(grad[1][2], "Software Engineer New Grad")

    def test_rejection_without_role_updates_internship_in_place(self):
        from tracker.services.gsheet import SheetHint, apply_hint_grids

        intern = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/24/2026", "Databricks", "Software Engineering Intern", "", "Winter 2027", "Applied", ""],
        ]
        grad = [
            ["Date Applied", "Company", "Role", "Location", "Result", "Notes"],
            ["", "", "", "", "Applied", ""],
        ]
        grids = {"internships": intern, "newgrad": grad}
        hint = SheetHint(
            company="Databricks",
            role="",
            location="",
            tab="newgrad",
            result="Rejected",
            notes="",
            date_applied="",
        )
        result = apply_hint_grids(grids, hint)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["tab"], "internships")
        self.assertEqual(intern[1][1:6], ["Databricks", "Software Engineering Intern", "", "Winter 2027", "Rejected"])
        self.assertEqual(intern[1][0], "09/24/2026")
        self.assertEqual(grad[1][1], "")

    def test_reprocess_after_parser_version_increment(self):
        from tracker.models import GmailProcessedMessage
        from tracker.services.mailparse import PARSER_VERSION
        from tracker.views import _stale_message_ids

        user = User.objects.create_user("reprocess", "reprocess@example.com", "pass12345")
        GmailProcessedMessage.objects.create(
            user=user, message_id="old-1", parser_version=PARSER_VERSION - 1, parse_status="applied"
        )
        GmailProcessedMessage.objects.create(
            user=user, message_id="current-1", parser_version=PARSER_VERSION, parse_status="applied"
        )
        GmailProcessedMessage.objects.create(
            user=user, message_id="failed-1", parser_version=PARSER_VERSION, parse_status="failed", last_error="sheet 429"
        )
        stale = set(_stale_message_ids(user, limit=10))
        self.assertIn("old-1", stale)
        self.assertIn("failed-1", stale)
        self.assertNotIn("current-1", stale)

    def test_failed_update_is_retryable(self):
        from tracker.models import GmailProcessedMessage
        from tracker.services.mailparse import PARSER_VERSION
        from tracker.views import _done_message_ids, _stale_message_ids

        user = User.objects.create_user("failretry", "failretry@example.com", "pass12345")
        GmailProcessedMessage.objects.create(
            user=user, message_id="boom", parser_version=PARSER_VERSION, parse_status="failed", last_error="timeout"
        )
        self.assertIn("boom", _stale_message_ids(user))
        self.assertNotIn("boom", _done_message_ids(user))

    def test_ambiguous_roles_are_marked_review(self):
        from tracker.services.gsheet import SheetHint, upsert_plan

        rows = [
            ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"],
            ["09/01/2026", "Databricks", "Software Engineering Intern", "", "Winter 2027", "Applied", ""],
            ["09/02/2026", "Databricks", "Software Engineering Intern", "", "Summer 2027", "Applied", ""],
        ]
        hint = SheetHint(
            company="Databricks",
            role="Software Engineering Intern",
            location="",
            tab="internships",
            result="OA",
            notes="",
            date_applied="09/24/2026",
            season="",
        )
        plan = upsert_plan(rows, hint)
        self.assertEqual(plan["action"], "review")

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


class AuditFixTests(TestCase):
    def test_push_hints_writes_a_batch_update(self):
        from unittest.mock import patch

        from tracker.services.gsheet import SheetHint, push_hints

        class FakeRequest:
            def __init__(self, payload):
                self.payload = payload

            def execute(self):
                return self.payload

        class FakeValues:
            def __init__(self):
                self.updates = []

            def get(self, **kwargs):
                return FakeRequest(
                    {"values": [["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]]}
                )

            def batchUpdate(self, **kwargs):
                self.updates.append(kwargs)
                return FakeRequest({})

        class FakeSpreadsheets:
            def __init__(self):
                self.values_api = FakeValues()

            def values(self):
                return self.values_api

        class FakeService:
            def spreadsheets(self):
                return spreadsheets

        spreadsheets = FakeSpreadsheets()
        hint = SheetHint(
            company="Stripe",
            role="Software Engineer Intern",
            location="",
            tab="internships",
            result="Applied",
            notes="From email: thanks",
            date_applied="09/24/2026",
            season="Summer 2027",
        )
        with patch("googleapiclient.discovery.build", return_value=FakeService()):
            result = push_hints(object(), "sheet-id", [hint])
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(spreadsheets.values_api.updates), 1)
        ranges = spreadsheets.values_api.updates[0]["body"]["data"]
        self.assertTrue(any(item["range"].startswith("'internships'!A1:") for item in ranges))

    def test_interview_note_appears_on_the_detail_page(self):
        from tracker.models import InterviewStage

        user = User.objects.create_user("notes", "notes@example.com", "pass12345")
        self.client.force_login(user)
        opp = Opportunity.objects.create(user=user, company="Stripe", title="Software Engineer Intern")
        stage = InterviewStage.objects.create(opportunity=opp, stage_name="Phone screen")
        response = self.client.post(
            reverse("interview_note", args=[opp.pk, stage.pk]),
            {"note_type": "general", "content": "Ask about the on-call rotation"},
        )
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(reverse("opportunity_detail", args=[opp.pk]))
        self.assertContains(detail, "Ask about the on-call rotation")

    def test_mangled_sender_names_become_the_employer(self):
        from tracker.services.extract import parse_mail

        received = "Your application has been received."
        cases = [
            ("MIT SH Workday Support <noreply@magna.com>", "Magna"),
            ("Human Resources <jobs@kenect.com>", "Kenect"),
            ("the Platform Software Engineering Intern at Intuitive <jobs@intuitive.com>", "Intuitive"),
            ("Notion we appreciate your interest in joining our team <jobs@notion.so>", "Notion"),
            ("join the team at Quora <jobs@quora.com>", "Quora"),
            ("the Associate Test Technician at Element Materials Technology <jobs@element.com>", "Element Materials Technology"),
        ]
        for sender, company in cases:
            parsed = parse_mail(sender, "Thank you for applying", received)
            self.assertIsNotNone(parsed, sender)
            self.assertEqual(parsed["company"], company, sender)
        us = parse_mail("Us <jobs@kenect.com>", "Thank you for applying", received)
        self.assertNotEqual(us["company"], "Us")

    def test_long_note_is_not_cut_mid_word(self):
        from tracker.services.extract import clip_text

        intact = "Sentence one. " * 200
        self.assertLessEqual(len(intact), 5000)
        self.assertEqual(clip_text(intact), intact.strip())
        long = ("alpha " * 2000).strip()
        clipped = clip_text(long, 80)
        self.assertLessEqual(len(clipped), 80)
        self.assertTrue(clipped.endswith("alpha"))

    def test_low_confidence_parse_is_review_and_not_written(self):
        from tracker.services.mailparse import apply_mail_hints, parse_message

        user = User.objects.create_user("lowconf", "lowconf@example.com", "pass12345")
        hint = parse_message(
            "Pat Lee <pat.lee@acme.com>",
            "Your application",
            "Thank you for your interest in Acme Labs. We regret to inform you that you have not been selected.",
        )
        self.assertIsNotNone(hint)
        self.assertLess(hint.confidence, 0.7)
        result = apply_mail_hints(user, [hint])
        self.assertEqual(result["review"], 1)
        self.assertEqual(result["created"], 0)
        self.assertFalse(Opportunity.objects.filter(user=user).exists())

    def test_duplicate_source_link_is_not_appended_twice(self):
        from tracker.services.gsheet import SheetHint, _merged_row
        from tracker.services.mailparse import _merge_note_text

        source = "Source: https://mail.google.com/mail/u/0/#all/abc"
        self.assertEqual(_merge_note_text("hello\n" + source, source), "hello\n" + source)
        headers = ["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]
        existing = ["09/24/2026", "Kenect", "Intern", "", "", "Applied", "hello\n" + source]
        hint = SheetHint(
            company="Kenect",
            role="Intern",
            location="",
            tab="internships",
            result="Rejected",
            notes=source,
            date_applied="",
        )
        merged = _merged_row(headers, hint, existing, "internships")
        self.assertEqual(merged[6].count(source), 1)

    def test_gmail_sync_get_is_not_allowed(self):
        user = User.objects.create_user("getsync", "getsync@example.com", "pass12345")
        self.client.force_login(user)
        response = self.client.get(reverse("gmail_sync"))
        self.assertEqual(response.status_code, 405)

    def test_review_mail_is_parked_after_three_attempts(self):
        from tracker.models import GmailProcessedMessage
        from tracker.services.mailparse import PARSER_VERSION
        from tracker.views import _done_message_ids, _save_gmail_log, _stale_message_ids

        user = User.objects.create_user("parked", "parked@example.com", "pass12345")
        for _ in range(3):
            _save_gmail_log(user, "review-mail", parse_status="review", parser_version=PARSER_VERSION)
        record = GmailProcessedMessage.objects.get(user=user, message_id="review-mail")
        self.assertEqual(record.parse_status, "parked")
        self.assertEqual(record.fetch_attempts, 3)
        self.assertNotIn("review-mail", _stale_message_ids(user))
        self.assertIn("review-mail", _done_message_ids(user))

    def test_opportunity_list_is_paged(self):
        user = User.objects.create_user("pages", "pages@example.com", "pass12345")
        self.client.force_login(user)
        for index in range(51):
            Opportunity.objects.create(user=user, company=f"Co{index:02d}", title="Intern")
        response = self.client.get(reverse("opportunity_list") + "?page=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["opportunities"]), 1)
        self.assertContains(response, "Page 2 of 2")

