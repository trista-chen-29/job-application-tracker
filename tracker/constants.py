from __future__ import annotations

from django.db import models


class OpportunityStatus(models.TextChoices):
    SAVED = "saved", "Saved"
    RESEARCHING = "researching", "Researching"
    PREPARING = "preparing", "Preparing"
    APPLIED = "applied", "Applied"
    RECRUITER_CONTACTED = "recruiter_contacted", "Recruiter Contacted"
    RECRUITER_SCREEN = "recruiter_screen", "Recruiter Screen"
    ONLINE_ASSESSMENT = "online_assessment", "Online Assessment"
    INTERVIEWING = "interviewing", "Interviewing"
    OFFER = "offer", "Offer"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"
    CLOSED = "closed", "Closed/Expired"


ACTIVE_STATUSES = {
    OpportunityStatus.SAVED,
    OpportunityStatus.RESEARCHING,
    OpportunityStatus.PREPARING,
    OpportunityStatus.APPLIED,
    OpportunityStatus.RECRUITER_CONTACTED,
    OpportunityStatus.RECRUITER_SCREEN,
    OpportunityStatus.ONLINE_ASSESSMENT,
    OpportunityStatus.INTERVIEWING,
    OpportunityStatus.OFFER,
}

SHEET_STATUSES = (
    (OpportunityStatus.SAVED, "Saved"),
    (OpportunityStatus.APPLIED, "Applied"),
    (OpportunityStatus.ONLINE_ASSESSMENT, "OA"),
    (OpportunityStatus.INTERVIEWING, "Interview"),
    (OpportunityStatus.OFFER, "Offer"),
    (OpportunityStatus.REJECTED, "Rejected"),
)

SHEET_STATUS_VALUES = {value for value, _label in SHEET_STATUSES}

SHEET_STATUS_FROM_FULL = {
    OpportunityStatus.SAVED: OpportunityStatus.SAVED,
    OpportunityStatus.RESEARCHING: OpportunityStatus.SAVED,
    OpportunityStatus.PREPARING: OpportunityStatus.SAVED,
    OpportunityStatus.APPLIED: OpportunityStatus.APPLIED,
    OpportunityStatus.RECRUITER_CONTACTED: OpportunityStatus.APPLIED,
    OpportunityStatus.RECRUITER_SCREEN: OpportunityStatus.INTERVIEWING,
    OpportunityStatus.ONLINE_ASSESSMENT: OpportunityStatus.ONLINE_ASSESSMENT,
    OpportunityStatus.INTERVIEWING: OpportunityStatus.INTERVIEWING,
    OpportunityStatus.OFFER: OpportunityStatus.OFFER,
    OpportunityStatus.ACCEPTED: OpportunityStatus.OFFER,
    OpportunityStatus.REJECTED: OpportunityStatus.REJECTED,
    OpportunityStatus.WITHDRAWN: OpportunityStatus.REJECTED,
    OpportunityStatus.CLOSED: OpportunityStatus.REJECTED,
}

SHEET_STATUS_RANK = {
    OpportunityStatus.SAVED: 0,
    OpportunityStatus.APPLIED: 1,
    OpportunityStatus.ONLINE_ASSESSMENT: 2,
    OpportunityStatus.INTERVIEWING: 3,
    OpportunityStatus.OFFER: 4,
    OpportunityStatus.REJECTED: 4,
}

TERMINAL_STATUSES = {
    OpportunityStatus.ACCEPTED,
    OpportunityStatus.REJECTED,
    OpportunityStatus.WITHDRAWN,
    OpportunityStatus.CLOSED,
}

APPLIED_OR_LATER = {
    OpportunityStatus.APPLIED,
    OpportunityStatus.RECRUITER_CONTACTED,
    OpportunityStatus.RECRUITER_SCREEN,
    OpportunityStatus.ONLINE_ASSESSMENT,
    OpportunityStatus.INTERVIEWING,
    OpportunityStatus.OFFER,
    OpportunityStatus.ACCEPTED,
    OpportunityStatus.REJECTED,
    OpportunityStatus.WITHDRAWN,
}

SCREEN_OR_LATER = {
    OpportunityStatus.RECRUITER_SCREEN,
    OpportunityStatus.ONLINE_ASSESSMENT,
    OpportunityStatus.INTERVIEWING,
    OpportunityStatus.OFFER,
    OpportunityStatus.ACCEPTED,
}

INTERVIEW_OR_LATER = {
    OpportunityStatus.INTERVIEWING,
    OpportunityStatus.OFFER,
    OpportunityStatus.ACCEPTED,
}

OFFER_OR_LATER = {
    OpportunityStatus.OFFER,
    OpportunityStatus.ACCEPTED,
}


class MatchCategory(models.TextChoices):
    STRONG = "strong", "Strong"
    POSSIBLE = "possible", "Possible"
    WEAK = "weak", "Weak"
    UNKNOWN = "unknown", "Not yet scored"


class Priority(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class Source(models.TextChoices):
    COMPANY_SITE = "company_site", "Company site"
    LINKEDIN = "linkedin", "LinkedIn"
    INDEED = "indeed", "Indeed"
    REFERRAL = "referral", "Referral"
    CAREER_FAIR = "career_fair", "Career fair"
    RECRUITER = "recruiter", "Recruiter"
    PROFESSOR = "professor", "Professor"
    ALUMNI = "alumni", "Alumni"
    SIMPLIFY = "simplify", "SimplifyJobs list"
    OTHER = "other", "Other"


class WorkArrangement(models.TextChoices):
    REMOTE = "remote", "Remote"
    HYBRID = "hybrid", "Hybrid"
    ONSITE = "onsite", "On-site"
    UNKNOWN = "unknown", "Unknown"


class RoleType(models.TextChoices):
    INTERNSHIP = "internship", "Internship"
    COOP = "coop", "Co-op"
    NEW_GRAD = "new_grad", "New grad"
    CONTRACT = "contract", "Contract"
    PART_TIME = "part_time", "Part-time"
    FULL_TIME = "full_time", "Full-time"


class SponsorshipStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    APPEARS_AVAILABLE = "appears_available", "Appears available"
    NOT_AVAILABLE = "not_available", "Not available"
    USER_VERIFIED = "user_verified", "User verified"


class WorkAuthorization(models.TextChoices):
    US_CITIZEN = "us_citizen", "U.S. citizen"
    PERMANENT_RESIDENT = "permanent_resident", "Permanent resident"
    VISA_HOLDER = "visa_holder", "Current visa holder"
    NEEDS_SPONSORSHIP = "needs_sponsorship", "Will need sponsorship"
    OTHER = "other", "Other / unspecified"


class SponsorshipPreference(models.TextChoices):
    REQUIRED = "required", "I need sponsorship"
    PREFERRED = "preferred", "Sponsorship would help"
    NOT_NEEDED = "not_needed", "I do not need sponsorship"


class MaterialType(models.TextChoices):
    RESUME = "resume", "Resume"
    COVER_LETTER = "cover_letter", "Cover letter"
    PORTFOLIO = "portfolio", "Portfolio / project link"
    TRANSCRIPT = "transcript", "Transcript / supporting document"
    PITCH = "pitch", "Short pitch"
    RECRUITER_QUESTIONS = "recruiter_questions", "Recruiter questions"
    INTERVIEW_STORY = "interview_story", "Interview story / notes"


class SkillKind(models.TextChoices):
    REQUIRED = "required", "Required"
    PREFERRED = "preferred", "Preferred"


class Relationship(models.TextChoices):
    RECRUITER = "recruiter", "Recruiter"
    EMPLOYEE = "employee", "Employee"
    ALUMNI = "alumni", "Alumni"
    PROFESSOR = "professor", "Professor"
    CAREER_FAIR = "career_fair", "Career-fair contact"
    REFERRAL = "referral", "Referral"
    OTHER = "other", "Other"


class TaskType(models.TextChoices):
    APPLY = "apply", "Apply"
    TAILOR = "tailor", "Tailor materials"
    RESEARCH = "research", "Research"
    MESSAGE = "message", "Message"
    FOLLOW_UP = "follow_up", "Follow up"
    INTERVIEW_PREP = "interview_prep", "Interview preparation"
    THANK_YOU = "thank_you", "Thank-you note"
    OTHER = "other", "Other"


class TaskPriority(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class ReferralStatus(models.TextChoices):
    NONE = "none", "No referral"
    REQUESTED = "requested", "Requested"
    SUBMITTED = "submitted", "Submitted"
    CONFIRMED = "confirmed", "Confirmed"


class InterviewNoteType(models.TextChoices):
    TOPICS = "topics", "Topics to prepare"
    TECHNICAL = "technical", "Technical questions"
    BEHAVIORAL = "behavioral", "Behavioral questions"
    ASK_EMPLOYER = "ask_employer", "Questions to ask the employer"
    STAR = "star", "STAR examples"
    GENERAL = "general", "Interview notes"


DEFAULT_CHECKLIST = [
    ("read_jd", "Read and saved the job description"),
    ("eligibility", "Confirmed eligibility"),
    ("location", "Checked location and work arrangement"),
    ("sponsorship", "Checked sponsorship/work authorization information"),
    ("resume", "Selected resume version"),
    ("materials", "Selected supporting materials"),
    ("tailored", "Tailored relevant bullets or keywords"),
    ("pitch", "Prepared short pitch"),
    ("submitted", "Submitted application"),
    ("confirmation", "Recorded confirmation number"),
    ("contact", "Added networking contact"),
    ("follow_up", "Scheduled follow-up"),
]

MATCH_WEIGHTS = {
    "required_skills": 0.40,
    "role_alignment": 0.20,
    "education_experience": 0.15,
    "location": 0.10,
    "sponsorship": 0.10,
    "preferred_skills": 0.05,
}
