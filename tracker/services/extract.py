"""Gmail extraction rules for the Django app. Keep in step with sheets-addon/Code.gs."""

from __future__ import annotations

import re

INTERNSHIPS_TAB = "internships"
NEWGRAD_TAB = "newgrad"
# Must match the Season dropdown on the internships tab.
SEASON_OPTIONS = ("Winter 2027", "Spring 2027", "Summer 2027")
# Mail from these senders is never added (for example on-campus student jobs).
IGNORE_COMPANIES = ("SJSU Student Union",)

GENERIC_ROLES = {"", "role", "intern", "internship", "internships", "position", "new grad"}
PLATFORM_COMPANIES = {
    "greenhouse",
    "greenhouse mail",
    "lever",
    "workday",
    "ashby",
    "icims",
    "smartrecruiters",
    "taleo",
    "successfactors",
    "linkedin",
    "indeed",
    "simplify",
    "workable",
    "codesignal",
    "hackerrank",
    "myworkday",
    "myworkday.com",
    "ultipro",
    "sapsf",
    "oraclecloud",
    "ashbyhq",
    "greenhouse-mail",
}
US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|"
    "OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
PERSONAL_SENDER_RE = re.compile(
    r"@(?:gmail|googlemail|yahoo|hotmail|outlook|live|icloud|me|aol|proton(?:mail)?)\.[a-z.]+>?\s*$", re.I
)
NOISE_SUBJECT_RE = re.compile(
    r"verification code|verify your|passcode|registering|registration|webinar|workshop|welcome to .*careers", re.I
)
ROLE_WORDS_RE = re.compile(
    r"\b(?:engineer(?:ing)?|developer|intern(?:ship)?s?|co-?op|scientist|analyst|technician|architect|manager|"
    r"management|research(?:er)?|designer|specialist|associate|grad(?:uate)?|software|sde|swe|devops|firmware|"
    r"programmer|consultant|administrator|supervisor|assistant)\b",
    re.I,
)
INTERN_RE = re.compile(r"\b(?:intern(?:ship)?s?|co-?ops?|seasonal)\b", re.I)
NEWGRAD_RE = re.compile(
    r"\b(?:new[\s-]?grads?(?:uate)?s?|university[\s-]?grads?(?:uate)?s?|college[\s-]?grads?(?:uate)?s?|"
    r"recent[\s-]?grads?(?:uate)?s?|early[\s-]?career|entry[\s-]?level)\b",
    re.I,
)

OFFER_PHRASES = ("offer of employment", "we are pleased to offer", "pleased to extend", "congratulations on your offer")
# "Unfortunately" alone shows up in confirmations ("unfortunately, due to the high volume..."), so it is not enough.
REJECTED_PHRASES = (
    "not be moving forward",
    "not moving forward",
    "decided not to move forward",
    "move forward with other candidates",
    "decided to pursue other",
    "regret to inform",
    "have not been selected",
    "not selected to move forward",
    "decided not to proceed",
    "will not be proceeding",
    "unable to offer you",
    "no longer under consideration",
    "position has been filled",
)
OA_PHRASES = (
    "online assessment",
    "coding assessment",
    "technical assessment",
    "coding challenge",
    "invited you to take",
    "complete the assessment",
    "hackerrank",
    "codesignal",
    "codility",
)
INTERVIEW_PHRASES = (
    "interview invitation",
    "invite you to interview",
    "invite you to an interview",
    "schedule your interview",
    "book your interview",
    "phone screen",
    "recruiter screen",
)
APPLIED_PHRASES = (
    "thank you for applying",
    "thanks for applying",
    "thank you so much for applying",
    "application received",
    "received your application",
    "received your job application",
    "application has been received",
    "application was submitted",
    "submitted successfully",
    "successfully applied",
    "thanks for your application",
    "thank you for your application",
    "thanks for completing your application",
    "application confirmation",
    "receipt of your application",
)
COMMON_ROLE_WORDS = {
    "intern", "interns", "internship", "internships", "software", "engineer", "engineering", "developer",
    "development", "sde", "swe", "i", "ii", "new", "grad", "graduate", "university", "early", "career", "entry",
    "level", "the", "and", "of", "co", "op", "us", "usa", "bs", "ms",
}


def clean_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"&nbsp;|\u00a0", " ", value)
    value = re.sub(r"&#39;|&rsquo;|&#8217;|\u2019", "'", value)
    value = value.replace("&amp;", "&").replace("&#8226;", "•")
    value = re.sub(r"[\u200b-\u200d\ufeff]", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n[\n ]*", "\n", value)
    return value.strip()


def normalize_name(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower().replace("&", " and "))
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (" inc", " llc", " ltd", " corp", " co", " recruiting"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _blob(subject: str, body: str) -> str:
    return re.sub(r"\s+", " ", f"{subject}\n{body}".lower())


def _contains_any(blob: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in blob for phrase in phrases)


def infer_result(subject: str, body: str) -> str:
    blob = _blob(subject, body)
    if _contains_any(blob, OFFER_PHRASES):
        return "Offer"
    if _contains_any(blob, REJECTED_PHRASES):
        return "Rejected"
    if _contains_any(blob, OA_PHRASES):
        return "OA"
    if _contains_any(blob, INTERVIEW_PHRASES):
        return "Interview"
    if _contains_any(blob, APPLIED_PHRASES):
        return "Applied"
    return ""


def is_confirmation(result: str, subject: str, body: str) -> bool:
    """Some confirmations also send the OA ("Confirmation on your Application + CodeSignal"); those still date the application."""
    if result == "Applied":
        return True
    return result == "OA" and _contains_any(_blob(subject, body), APPLIED_PHRASES)


def clean_company(name: str) -> str:
    text = clean_text(name)
    text = re.sub(r"[\"“”]", "", text)
    text = re.sub(r"\s*@\s*icims\b.*$", "", text, flags=re.I)
    text = re.sub(
        r"^(?:\s*(?:workday[\s_-]*no[\s_-]*reply|workday|do[\s_-]*not[\s_-]*reply|no[\s_-]*reply|noreply)\b)+",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"[_|]+", " ", text).strip()
    previous = None
    while previous != text:
        previous = text
        text = re.sub(
            r"[\s,]+(?:university recruiting|recruiting|recruitment|talent acquisition|talent|hiring|human resources|hr|"
            r"careers?|jobs|team|inc|llc|ltd|corp|corporation)\.?\s*$",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(r"'s$", "", text, flags=re.I)
        text = re.sub(r"[!?.,:\s]+$", "", text).strip()
    if re.fullmatch(r"[a-z0-9]+", text):
        text = text.upper() if re.search(r"\d", text) else text[:1].upper() + text[1:]
    lower = text.lower()
    if not text or len(text) > 60 or len(text.split()) > 6 or "@" in text:
        return ""
    if lower in PLATFORM_COMPANIES:
        return ""
    if re.match(r"(?:the|our|a|an|one|this|joining|being|your|my|dear|hi|hello|candidate|campus)\b", text, re.I):
        return ""
    if ROLE_WORDS_RE.search(text) or re.search(r"thank|application|applying|campus", text, re.I):
        return ""
    return text


def company_from_sender(from_header: str) -> str:
    header = str(from_header or "")
    angle = re.search(r"<([^>]+)>", header)
    email = (angle.group(1) if angle else header).strip().lower()
    display = re.sub(r"<.*?>", "", header)
    display = re.sub(r"[\"“”]", "", display)
    display = re.sub(r"\s*@\s*icims\b.*$", "", display, flags=re.I).strip()
    if not display or "@" in display:
        return ""
    local = email.split("@")[0].split("+")[0]
    words = [re.sub(r"[^a-z]", "", word) for word in display.lower().split()]
    words = [word for word in words if word]
    # A recruiter's own name (Tim Farrell <tim.farrell@...>) is not the company.
    if len(words) == 2:
        personal = {".".join(words), "_".join(words), "-".join(words), words[0][:1] + words[1]}
        if local in personal:
            return ""
    return clean_company(display)


def company_from_candidate(raw: str) -> str:
    text = clean_text(raw).split("\n")[0]
    text = re.sub(r"\.(\s.*)?$", "", text, count=1)
    # "the Platform Software Engineering Intern at Intuitive" names the company after "at".
    around = re.split(r"\s(?:at|with)\s", text, flags=re.I)
    if len(around) > 1 and (re.match(r"(?:the|our|an?)\s", text, re.I) or ROLE_WORDS_RE.search(around[0])):
        text = around[-1]
    text = re.split(r"[|!?:;()\[\]]", text)[0]
    text = re.split(
        r"\s+[-–—]\s+|,(?!\s*(?:inc|llc|ltd|corp)\b)|\s+(?:and|for|we|has|is|as|to|about|in|team)\b", text, flags=re.I
    )[0]
    return clean_company(text)


def infer_company(from_header: str, subject: str, body: str) -> str:
    from_name = company_from_sender(from_header)
    if from_name:
        return from_name
    head = str(body or "")[:3000]
    patterns = [
        (subject, re.compile(r"offer of employment\s*[-–:]\s*(.+?)\s+[-–]\s", re.I)),
        (f"{subject}\n{head}", re.compile(r"^(.+?)\s+invited you to take\b", re.I | re.M)),
        (subject, re.compile(r"^(.+?)\s+[-–]\s+thank you\b", re.I)),
        (subject, re.compile(r"\b(?:applying|applied|application|apply)\s+(?:to|at|with)\s+([^\n]{2,120})", re.I)),
        (head, re.compile(r"\b(?:applying|applied|application|apply)\s+(?:to|at|with)\s+([^\n]{2,120})", re.I)),
        (head, re.compile(r"\b(?:role|position|opportunity|opening|job)\s+(?:here\s+)?(?:at|with)\s+([^\n]{2,80})", re.I)),
        (head, re.compile(r"\b(?:role|position) of\s+[^\n]+?\s+at\s+([^\n]{2,80})", re.I)),
        (head, re.compile(r"\binterest in\s+([^\n]{2,80})", re.I)),
        (head, re.compile(r"\bjoining\s+(?:the\s+)?([^\n]{2,60})", re.I)),
        (head, re.compile(r"\bcareer with\s+([^\n]{2,60})", re.I)),
        (
            head,
            re.compile(
                r"(?:^|\n)\s*([A-Z][\w&.' -]{1,40}?)\s+(?:talent acquisition|human resources|recruiting|recruitment|hiring)\b"
            ),
        ),
    ]
    for text, pattern in patterns:
        match = pattern.search(str(text or ""))
        if not match:
            continue
        company = company_from_candidate(match.group(1))
        if company:
            return company
    workday = re.search(r"([a-z0-9]+)@myworkday\.com", str(from_header or ""), re.I)
    if workday:
        return clean_company(workday.group(1))
    return company_from_domain(from_header)


PLATFORM_DOMAINS = {
    "greenhouse-mail.io", "greenhouse.io", "myworkday.com", "workday.com", "ashbyhq.com", "icims.com",
    "smartrecruiters.com", "successfactors.eu", "successfactors.com", "oraclecloud.com", "sapsf.com", "ultipro.com",
    "workablemail.com", "hackerrankforwork.com", "hackerrank.com", "codesignal.com", "lever.co", "taleo.net",
    "linkedin.com", "indeed.com",
}


def company_from_domain(from_header: str) -> str:
    header = str(from_header or "")
    angle = re.search(r"<([^>]+)>", header)
    email = (angle.group(1) if angle else header).strip().lower()
    host = re.sub(r">.*$", "", email.split("@")[1] if "@" in email else "")
    parts = [part for part in host.split(".") if part]
    if len(parts) < 2:
        return ""
    root = ".".join(parts[-2:])
    if root in PLATFORM_DOMAINS or parts[-1] == "edu":
        return ""
    return clean_company(parts[-2])


def is_ignored_company(company: str) -> bool:
    name = normalize_name(company)
    return any(normalize_name(ignored) == name for ignored in IGNORE_COMPANIES)


ROLE_TEXT = r"((?:(?!\.\s)[^\n!?])+?)"
ROLE_PATTERNS = [
    ("s", re.compile(r"offer of employment\s*[-–]\s*.+?\s[-–]\s(.+?)(?:\s[-–]\s[^-–]+)?$", re.I)),
    ("b", re.compile(r"\bapplication for\s+(?:the\s+)?" + ROLE_TEXT + r"\s*\((?:job number|job id|req)", re.I)),
    (
        "sb",
        re.compile(
            r"\b(?:applying|apply|applied|application|interest|considered|fit)\s+(?:to|for|in)\s+"
            r"(?:the\s+|our\s+|an?\s+)?(?:[A-Z][\w.&-]*'s\s+)?" + ROLE_TEXT + r"\s+(?:role|position|opening|opportunity|job)\b",
            re.I,
        ),
    ),
    ("b", re.compile(r"\brole of\s+" + ROLE_TEXT + r"\s+at\s", re.I)),
    ("sb", re.compile(r"\b(?:application|applying) to\s+(?:the\s+)?" + ROLE_TEXT + r"\s+at\s", re.I)),
    ("b", re.compile(r"\bposition of\s+" + ROLE_TEXT + r"\s*(?:\.|has been|$)", re.I | re.M)),
    ("b", re.compile(r"\bapplication for\s+(?:the\s+)?" + ROLE_TEXT + r"\s*(?:\.|has been|was|is)(?:\s|$)", re.I | re.M)),
    ("b", re.compile(r"\b(?:apply|applying) for\s+(?:the\s+)?" + ROLE_TEXT + r"\s*[!.]", re.I)),
    ("s", re.compile(r"application received\s*(?:for|[-–:])\s*(.+)$", re.I)),
    ("s", re.compile(r"applying for\s+(.+)$", re.I)),
    ("s", re.compile(r"received your application for\s+(.+)$", re.I)),
    ("s", re.compile(r"your application(?: for)?\s*:?\s+(.+)$", re.I)),
    ("s", re.compile(r"application confirmation\s*[-–:]\s*(.+)$", re.I)),
    ("s", re.compile(r"\|\s*([^|]+)$")),
]


def infer_raw_role(subject: str, body: str) -> str:
    # Plain-text mail wraps long lines, which can split a role title in two.
    texts = {"s": str(subject or ""), "b": re.sub(r"\s*\n\s*", " ", str(body or "")[:4000])}
    for where, pattern in ROLE_PATTERNS:
        for key in where:
            for match in pattern.finditer(texts[key]):
                raw = match.group(1).strip()
                if is_valid_role(raw):
                    return raw
    return ""


def is_valid_role(raw: str) -> bool:
    role = clean_role_title(raw)
    if len(role) < 3 or len(role) > 150:
        return False
    if not ROLE_WORDS_RE.search(role):
        return False
    return not re.search(r"\b(?:thank|application|applying|your|we|you)\b", role, re.I)


def clean_role_title(title: str) -> str:
    text = re.sub(r"\s+", " ", clean_text(title))
    if re.search(r"\band the\s", text, re.I):
        text = re.sub(r"^.*\band the\s+", "", text, count=1, flags=re.I)
    text = re.sub(r"^(?:the|a|an|our)\s+", "", text, count=1, flags=re.I)
    text = re.sub(r"^R\d{5,}\s+", "", text, count=1, flags=re.I)
    text = re.sub(r"\s*[\(\[](?:job number|job id|id|req)?[#:\s]*[\w-]*\d{3,}[\w-]*\s*[\)\]]", "", text, flags=re.I)
    text = re.sub(r"\s+[-–]\s+(?:[a-z]-)?\d{3,}[\d-]*$", "", text, count=1, flags=re.I)
    text = re.sub(r"\s+\d{5,}$", "", text, count=1)
    text = re.sub(r"\s*[\(\[][^)\]]*(?:20\d{2}|start|summer|winter|fall|spring)[^)\]]*[\)\]]", "", text, flags=re.I)
    text = re.sub(r"\s*[-–—,]?\s*\b(?:summer|winter|fall|autumn|spring)\s+20\d{2}\b", "", text, flags=re.I)
    text = re.sub(r"\s*[-–—,]?\s*\b20\d{2}\s+(?:summer|winter|fall|autumn|spring)\b", "", text, flags=re.I)
    text = re.sub(r"\s*[-–—,]\s*(?:summer|winter|fall|autumn|spring)\s*$", "", text, count=1, flags=re.I)
    text = re.sub(r"\s+[-–—]\s+[A-Z][A-Za-z .]+,\s*[A-Z]{2}$", "", text, count=1)
    text = re.sub(r"\s+at\s+[A-Z].*$", "", text, count=1)
    text = re.sub(r"\s*[-–]\s*20\d{2}\b(?=\s*(?:\(|$))", "", text, count=1)
    text = re.sub(r"\s+20\d{2}$", "", text, count=1)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"\s+(?:role|position|opening|opportunity|job)$", "", text, count=1, flags=re.I)
    text = re.sub(r"\s+has been received.*$", "", text, count=1, flags=re.I)
    return re.sub(r"\s+", " ", text).strip("-–—,: ")[:150]


def role_location(raw_role: str) -> str:
    match = re.search(r"\s[-–—]\s([A-Z][A-Za-z .]+,\s*[A-Z]{2})\s*$", str(raw_role or ""))
    return match.group(1).strip() if match else ""


def _season_name(value: str) -> str:
    name = (value or "").strip().lower()
    return "Fall" if name == "autumn" else name[:1].upper() + name[1:]


def find_season(text: str, loose: bool) -> str:
    blob = str(text or "")
    named = re.search(r"\b(summer|winter|fall|autumn|spring)\s+(20\d{2})\b", blob, re.I)
    if named:
        return f"{_season_name(named.group(1))} {named.group(2)}"
    reverse = re.search(r"\b(20\d{2})\s+(summer|winter|fall|autumn|spring)\b", blob, re.I)
    if reverse:
        return f"{_season_name(reverse.group(2))} {reverse.group(1)}"
    if not loose:
        return ""
    season = re.search(r"\b(summer|winter|fall|autumn|spring)\b", blob, re.I)
    year = re.search(r"\b(20\d{2})\b", blob)
    return f"{_season_name(season.group(1))} {year.group(1)}" if season and year else ""


def pick_season(raw_role: str, subject: str, body: str) -> str:
    for text, loose in ((raw_role, True), (subject, True), (str(body or "")[:1500], False)):
        found = find_season(text, loose)
        if found:
            return found if found in SEASON_OPTIONS else ""
    return ""


def infer_season(text: str, default: str = "") -> str:
    found = find_season(text, True)
    return found if found in SEASON_OPTIONS else default


def infer_location(body: str) -> str:
    text = str(body or "")
    labeled = re.search(r"\blocation\s*:\s*([A-Z][A-Za-z .]+,\s*[A-Z]{2}\b|remote|hybrid)", text, re.I)
    if labeled:
        return labeled.group(1).strip()
    placed = re.search(r"\b(?:based in|located in|office in)\s+([A-Z][A-Za-z .]+,\s*[A-Z]{2})\b", text)
    if placed:
        return placed.group(1).strip()
    city = re.search(r"\b(?:in|at)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2},\s*(?:" + US_STATES + r"))\b", text)
    return city.group(1).strip() if city else ""


def extract_please_note(body: str) -> str:
    text = str(body or "")
    match = re.search(
        r"please note(?: that)?[:\s]+(.+?)(?:\n\s*\n|\n\s*regards|\n\s*\*\*\s*please note:\s*do not reply|\Z)",
        text,
        flags=re.I | re.S,
    )
    if match:
        note = re.sub(r"\s+", " ", match.group(0)).strip()
        note = re.sub(r"\s*\*+\s*please note:.*$", "", note, flags=re.I).strip()
        if re.search(r"do not reply", note, re.I) and not re.search(r"official communication|email addresses ending", note, re.I):
            note = ""
        sentence = re.match(r".*?[.!?](?=\s|$)", note)
        if sentence:
            note = sentence.group(0)
        if note:
            return note[:300]
    official = re.search(r"[^.]*official communication[^.]*\.", text, re.I)
    return official.group(0).strip()[:500] if official else ""


def is_generic_role(role: str) -> bool:
    return normalize_name(role) in GENERIC_ROLES


def choose_tab(role: str, text: str = "") -> str:
    title = (role or "").strip()
    if INTERN_RE.search(title) and not is_generic_role(title) and not NEWGRAD_RE.search(title):
        return INTERNSHIPS_TAB
    if NEWGRAD_RE.search(title):
        return NEWGRAD_TAB
    blob = str(text or "")[:2500]
    intern = bool(INTERN_RE.search(blob))
    grad = bool(NEWGRAD_RE.search(blob) or NEWGRAD_RE.search(title))
    if intern and not grad:
        return INTERNSHIPS_TAB
    if grad:
        return NEWGRAD_TAB
    if intern:
        return INTERNSHIPS_TAB
    return NEWGRAD_TAB


def tab_from_role(role: str) -> str:
    """Tab implied by the role title alone, or "" when the title does not say."""
    text = (role or "").strip()
    if NEWGRAD_RE.search(text):
        return NEWGRAD_TAB
    if INTERN_RE.search(text) and not is_generic_role(text):
        return INTERNSHIPS_TAB
    return ""


def roles_similar(a: str, b: str) -> bool:
    """"Seasonal Associate Technician" and "Associate Test Technician" are the same job; "(Cloud Storage)" and "(Systems)" are not."""

    def words(text: str) -> list[str]:
        return [w for w in normalize_name(text).split(" ") if w and w not in COMMON_ROLE_WORDS and not w.isdigit()]

    left, right = words(a), words(b)
    if not left or not right:
        return True
    shared = len([w for w in left if w in right])
    return shared / (len(left) + len(right) - shared) >= 0.5


def companies_match(a: str, b: str) -> bool:
    left, right = normalize_name(a), normalize_name(b)
    if not left or not right:
        return False
    return left == right or left.startswith(right + " ") or right.startswith(left + " ")


def parse_mail(from_header: str, subject: str, body: str) -> dict | None:
    header = str(from_header or "")
    # Your own replies (and anything from a personal mailbox) are not recruiter mail.
    if PERSONAL_SENDER_RE.search(header):
        return None
    subject = clean_text(subject)
    if NOISE_SUBJECT_RE.search(subject):
        return None
    body = clean_text(body)
    result = infer_result(subject, body)
    if not result:
        return None
    company = infer_company(header, subject, body)
    if not company or is_ignored_company(company):
        return None
    raw_role = infer_raw_role(subject, body)
    role = clean_role_title(raw_role)
    if re.match(r"student\b", role, re.I):
        return None
    location = role_location(raw_role) or infer_location(body)
    tab = choose_tab(role, f"{raw_role}\n{subject}\n{body}")
    return {
        "company": company[:200],
        "role": role,
        "location": location,
        "tab": tab,
        "result": result,
        "season": pick_season(raw_role, subject, body) if tab == INTERNSHIPS_TAB else "",
        "useful_note": extract_please_note(body),
        "confirmation": is_confirmation(result, subject, body),
    }
