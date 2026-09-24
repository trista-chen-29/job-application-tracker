from __future__ import annotations

import re
from dataclasses import dataclass

from tracker.constants import OpportunityStatus, SHEET_STATUS_RANK

INTERNSHIPS_TAB = "internships"
NEWGRAD_TAB = "newgrad"
DEFAULT_SEASON = "Summer 2027"

RESULT_LABEL = {
    OpportunityStatus.APPLIED: "Applied",
    OpportunityStatus.ONLINE_ASSESSMENT: "OA",
    OpportunityStatus.INTERVIEWING: "Interview",
    OpportunityStatus.OFFER: "Offer",
    OpportunityStatus.REJECTED: "Rejected",
}

RESULT_RANK = {
    "Applied": SHEET_STATUS_RANK[OpportunityStatus.APPLIED],
    "OA": SHEET_STATUS_RANK[OpportunityStatus.ONLINE_ASSESSMENT],
    "Interview": SHEET_STATUS_RANK[OpportunityStatus.INTERVIEWING],
    "Offer": SHEET_STATUS_RANK[OpportunityStatus.OFFER],
    "Rejected": SHEET_STATUS_RANK[OpportunityStatus.REJECTED],
}

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def spreadsheet_id_from_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    match = SHEET_ID_RE.search(text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", text):
        return text
    return ""


def result_label(status: str) -> str:
    return RESULT_LABEL.get(status, "Applied")


INTERNSHIP_ROLE_RE = re.compile(r"\b(?:intern(?:ship)?s?|co-?ops?)\b", re.I)
NEWGRAD_ROLE_RE = re.compile(
    r"\b(?:new[\s-]?grads?(?:uate)?s?|university[\s-]?grads?(?:uate)?s?|early[\s-]?career|full[\s-]?time)\b",
    re.I,
)


GENERIC_INTERN_TITLES = {"intern", "internship", "internships", "co-op", "coop", "co op"}


def choose_tab(title: str, body: str = "") -> str:
    title_text = title or ""
    if INTERNSHIP_ROLE_RE.search(title_text) and title_text.strip().lower() not in GENERIC_INTERN_TITLES:
        return INTERNSHIPS_TAB
    if NEWGRAD_ROLE_RE.search(title_text):
        return NEWGRAD_TAB
    blob = f"{title_text}\n{(body or '')[:2500]}"
    if INTERNSHIP_ROLE_RE.search(blob) and not NEWGRAD_ROLE_RE.search(blob):
        return INTERNSHIPS_TAB
    if NEWGRAD_ROLE_RE.search(blob) and not INTERNSHIP_ROLE_RE.search(blob):
        return NEWGRAD_TAB
    if INTERNSHIP_ROLE_RE.search(blob):
        return INTERNSHIPS_TAB
    if NEWGRAD_ROLE_RE.search(blob):
        return NEWGRAD_TAB
    return INTERNSHIPS_TAB


def other_tab(tab: str) -> str:
    return NEWGRAD_TAB if tab == INTERNSHIPS_TAB else INTERNSHIPS_TAB


def infer_location(body: str) -> str:
    match = re.search(r"(?:location|based in|office(?:s)? in)\s*[:\-]\s*([A-Za-z0-9 .,\-/]+)", body or "", flags=re.I)
    if not match:
        return ""
    return match.group(1).split("\n")[0].strip()[:80]


def normalize_company(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and "))
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (" inc", " llc", " ltd", " corp", " co", " recruiting"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def should_advance(current: str, nxt: str) -> bool:
    if current == "Offer" and nxt == "Rejected":
        return False
    if nxt == "Offer" and current == "Rejected":
        return True
    current_rank = RESULT_RANK.get(current, 0)
    next_rank = RESULT_RANK.get(nxt, 0)
    if next_rank > current_rank:
        return True
    if nxt == "Rejected" and current != "Offer":
        return True
    return False


@dataclass
class SheetHint:
    company: str
    role: str
    location: str
    tab: str
    result: str
    notes: str
    date_applied: str
    season: str = DEFAULT_SEASON


def header_index(headers: list[str], names: tuple[str, ...]) -> int:
    lowered = [str(item or "").strip().lower() for item in headers]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return -1


def first_empty_company_row(rows: list[list[str]], company_col: int) -> int:
    for index, row in enumerate(rows[1:], start=2):
        value = row[company_col] if company_col < len(row) else ""
        if not str(value).strip():
            return index
    return len(rows) + 1


def _role_tokens(role: str) -> set[str]:
    stop = {"the", "a", "an", "of", "and", "for", "role", "position"}
    return {part for part in normalize_company(role).split() if part and part not in stop}


def find_company_row(rows: list[list[str]], company_col: int, company: str, role: str = "", role_col: int = -1) -> int:
    target = normalize_company(company)
    if not target:
        return 0
    hits: list[int] = []
    for index, row in enumerate(rows[1:], start=2):
        value = row[company_col] if company_col < len(row) else ""
        if normalize_company(str(value)) != target:
            continue
        hits.append(index)
        if role and role_col >= 0:
            current_role = row[role_col] if role_col < len(row) else ""
            tokens = _role_tokens(role) & _role_tokens(str(current_role))
            if current_role and (normalize_company(str(current_role)) == normalize_company(role) or len(tokens) >= 2):
                return index
    if len(hits) == 1:
        return hits[0]
    return 0


def role_should_replace(current: str, nxt: str) -> bool:
    now = (current or "").strip()
    new = (nxt or "").strip()
    if not new:
        return False
    if now.lower() in {"", "intern", "internship", "role"} and new.lower() not in {"intern", "internship"}:
        return True
    return len(new) > len(now) + 6


def hint_from_mail(company: str, title: str, status: str, note: str, body: str = "", date_applied: str = "") -> SheetHint:
    return SheetHint(
        company=company,
        role=title or "Internship",
        location=infer_location(body),
        tab=choose_tab(title, body),
        result=result_label(status),
        notes=note,
        date_applied=date_applied,
    )


def upsert_plan(rows: list[list[str]], hint: SheetHint) -> dict:
    headers = rows[0] if rows else []
    company_col = header_index(headers, ("company",))
    result_col = header_index(headers, ("result", "status"))
    role_col = header_index(headers, ("role", "title", "position"))
    if company_col < 0 or result_col < 0:
        return {"action": "skipped", "reason": "missing headers"}
    match_row = find_company_row(rows, company_col, hint.company, hint.role, role_col)
    if match_row:
        row = rows[match_row - 1]
        current = row[result_col] if result_col < len(row) else ""
        current_role = row[role_col] if role_col >= 0 and role_col < len(row) else ""
        if should_advance(str(current), hint.result) or role_should_replace(str(current_role), hint.role):
            return {"action": "update", "row": match_row, "hint": hint}
        return {"action": "skipped", "row": match_row}
    return {
        "action": "create",
        "row": 2,
        "hint": hint,
    }


def _col_letter(index: int) -> str:
    return chr(ord("A") + index)


def _merged_row(headers: list[str], hint: SheetHint, existing: list[str] | None, tab: str) -> list[str]:
    existing = list(existing or [])
    while len(existing) < len(headers):
        existing.append("")
    mapping = {
        "date applied": hint.date_applied,
        "applied": hint.date_applied,
        "date": hint.date_applied,
        "company": hint.company,
        "role": hint.role,
        "title": hint.role,
        "position": hint.role,
        "location": hint.location,
        "season": hint.season if tab == INTERNSHIPS_TAB else "",
        "result": hint.result,
        "status": hint.result,
        "notes": hint.notes,
        "note": hint.notes,
    }
    row = list(existing)
    for index, header in enumerate(headers):
        key = str(header or "").strip().lower()
        value = mapping.get(key, "")
        current = str(row[index] or "")
        if key in {"notes", "note"} and value:
            if value not in current:
                row[index] = f"{value}\n{current}".strip() if current else value
            continue
        if key in {"result", "status"}:
            if should_advance(current, str(value)) or not current:
                row[index] = value or current
            continue
        if key in {"role", "title", "position"}:
            if role_should_replace(current, str(value)):
                row[index] = value
            elif not current and value:
                row[index] = value
            continue
        if value and not current:
            row[index] = value
        elif key == "company" and value:
            row[index] = value
        elif key in {"date applied", "applied", "date"} and value and not current:
            row[index] = value
    return row


def sort_filled_latest_first(rows: list[list[str]]) -> list[list[str]]:
    if len(rows) < 2:
        return rows
    headers = rows[0]
    company_col = header_index(headers, ("company",))
    date_col = header_index(headers, ("date applied", "applied", "date"))
    filled: list[list[str]] = []
    empty: list[list[str]] = []
    for row in rows[1:]:
        company = row[company_col] if company_col >= 0 and company_col < len(row) else ""
        if str(company).strip():
            filled.append(row)
        else:
            empty.append(row)

    def date_key(row: list[str]) -> str:
        if date_col < 0 or date_col >= len(row):
            return ""
        return str(row[date_col] or "")

    filled.sort(key=date_key, reverse=True)
    return [headers] + filled + empty


def _blank_identity_row(headers: list[str], existing: list[str]) -> list[str]:
    row = list(existing)
    while len(row) < len(headers):
        row.append("")
    for names in (("company",), ("role", "title", "position"), ("date applied", "applied", "date"), ("location",), ("notes", "note")):
        col = header_index(headers, names)
        if col >= 0:
            row[col] = ""
    return row


def _sheets_execute(request):
    import time

    from googleapiclient.errors import HttpError

    last_error = None
    for attempt in range(6):
        try:
            return request.execute()
        except HttpError as exc:
            last_error = exc
            status = getattr(exc.resp, "status", None)
            if status not in {429, 403}:
                raise
            if "RATE_LIMIT" not in str(exc) and "quota" not in str(exc).lower() and status != 429:
                raise
            time.sleep(20 + attempt * 15)
    raise last_error


def push_hints(creds, spreadsheet_id: str, hints: list[SheetHint]) -> dict:
    from googleapiclient.discovery import build

    created = 0
    updated = 0
    skipped = 0
    if not spreadsheet_id or not hints:
        return {"created": created, "updated": updated, "skipped": skipped}
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    tabs = {INTERNSHIPS_TAB, NEWGRAD_TAB} | {hint.tab for hint in hints}
    grids: dict[str, list[list[str]]] = {}
    for tab in tabs:
        payload = _sheets_execute(
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1:G200")
        )
        grids[tab] = payload.get("values") or [["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]]
    writes: list[dict] = []
    dirty_tabs: set[str] = set()
    for hint in hints:
        plan = upsert_plan(grids.get(hint.tab) or grids[INTERNSHIPS_TAB], hint)
        if plan["action"] == "create":
            alt = other_tab(hint.tab)
            if alt in grids:
                other_plan = upsert_plan(grids[alt], hint)
                if other_plan.get("row") and other_plan["action"] != "create":
                    from_row = other_plan["row"]
                    headers_from = grids[alt][0]
                    existing = list(grids[alt][from_row - 1]) if from_row < len(grids[alt]) else []
                    merged = _merged_row(headers_from, hint, existing, hint.tab)
                    grids[hint.tab].insert(1, merged)
                    grids[alt][from_row - 1] = _blank_identity_row(headers_from, existing)
                    dirty_tabs.add(hint.tab)
                    dirty_tabs.add(alt)
                    updated += 1
                    continue
        action = plan["action"]
        if action == "skipped":
            skipped += 1
            continue
        headers = grids[hint.tab][0]
        width = max(len(headers), 7)
        if action == "create":
            merged = _merged_row(headers, hint, [""] * width, hint.tab)
            grids[hint.tab].insert(1, merged)
            created += 1
        else:
            row_number = plan["row"]
            while len(grids[hint.tab]) < row_number:
                grids[hint.tab].append([""] * width)
            existing = list(grids[hint.tab][row_number - 1])
            grids[hint.tab][row_number - 1] = _merged_row(headers, hint, existing, hint.tab)
            updated += 1
        dirty_tabs.add(hint.tab)
    for tab in dirty_tabs:
        grid = sort_filled_latest_first(grids[tab])
        last_col = _col_letter(max(len(grid[0]) - 1, 0))
        writes.append({"range": f"'{tab}'!A1:{last_col}{len(grid)}", "values": grid})
    if writes:
        _sheets_execute(
            service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": writes},
            )
        )
    return {"created": created, "updated": updated, "skipped": skipped}
