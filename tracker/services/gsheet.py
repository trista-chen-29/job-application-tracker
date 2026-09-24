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


def choose_tab(title: str, body: str = "") -> str:
    blob = f"{title}\n{body}".lower()
    if re.search(r"new[\s-]?grad|university grad|full[\s-]?time", blob) and "intern" not in blob:
        return NEWGRAD_TAB
    return INTERNSHIPS_TAB


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


def find_company_row(rows: list[list[str]], company_col: int, company: str) -> int:
    target = normalize_company(company)
    found = 0
    for index, row in enumerate(rows[1:], start=2):
        value = row[company_col] if company_col < len(row) else ""
        if normalize_company(str(value)) == target and target:
            if found:
                return 0
            found = index
    return found


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
    if company_col < 0 or result_col < 0:
        return {"action": "skipped", "reason": "missing headers"}
    match_row = find_company_row(rows, company_col, hint.company)
    if match_row:
        current = rows[match_row - 1][result_col] if result_col < len(rows[match_row - 1]) else ""
        if not should_advance(str(current), hint.result):
            return {"action": "skipped", "row": match_row}
        return {"action": "update", "row": match_row, "hint": hint}
    return {
        "action": "create",
        "row": first_empty_company_row(rows, company_col),
        "hint": hint,
    }


def _col_letter(index: int) -> str:
    return chr(ord("A") + index)


def _write_row(service, spreadsheet_id: str, tab: str, row_number: int, headers: list[str], hint: SheetHint, existing: list[str] | None = None) -> None:
    existing = existing or []
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
    for index, header in enumerate(headers):
        key = str(header or "").strip().lower()
        value = mapping.get(key, "")
        if key in {"notes", "note"} and existing and index < len(existing) and value:
            previous = str(existing[index] or "")
            if value not in previous:
                value = f"{value}\n{previous}".strip()
        if not value:
            continue
        rng = f"'{tab}'!{_col_letter(index)}{row_number}"
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=rng,
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]},
        ).execute()


def push_hints(creds, spreadsheet_id: str, hints: list[SheetHint]) -> dict:
    from googleapiclient.discovery import build

    created = 0
    updated = 0
    skipped = 0
    if not spreadsheet_id or not hints:
        return {"created": created, "updated": updated, "skipped": skipped}
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    tabs = {hint.tab for hint in hints}
    grids: dict[str, list[list[str]]] = {}
    for tab in tabs:
        payload = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1:G200")
            .execute()
        )
        grids[tab] = payload.get("values") or [["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]]
    for hint in hints:
        plan = upsert_plan(grids[hint.tab], hint)
        action = plan["action"]
        if action == "skipped":
            skipped += 1
            continue
        row_number = plan["row"]
        headers = grids[hint.tab][0]
        existing = grids[hint.tab][row_number - 1] if action == "update" and row_number <= len(grids[hint.tab]) else []
        _write_row(service, spreadsheet_id, hint.tab, row_number, headers, hint, existing)
        while len(grids[hint.tab]) < row_number:
            grids[hint.tab].append([""] * max(len(headers), 7))
        row = list(grids[hint.tab][row_number - 1])
        while len(row) < len(headers):
            row.append("")
        company_col = header_index(headers, ("company",))
        result_col = header_index(headers, ("result", "status"))
        if company_col >= 0:
            row[company_col] = hint.company
        if result_col >= 0:
            row[result_col] = hint.result
        grids[hint.tab][row_number - 1] = row
        if action == "create":
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "skipped": skipped}
