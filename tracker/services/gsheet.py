from __future__ import annotations

import re
from dataclasses import dataclass

from tracker.constants import OpportunityStatus, SHEET_STATUS_RANK
from tracker.services import extract
from tracker.services.extract import GENERIC_ROLES, INTERNSHIPS_TAB, NEWGRAD_TAB, PLATFORM_COMPANIES  # noqa: F401

DEFAULT_SEASON = ""

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


choose_tab = extract.choose_tab
tab_from_role = extract.tab_from_role
infer_location = extract.infer_location


def other_tab(tab: str) -> str:
    return NEWGRAD_TAB if tab == INTERNSHIPS_TAB else INTERNSHIPS_TAB


def location_should_highlight(location: str, location_missing: bool) -> bool:
    return bool(location_missing) and not str(location or "").strip()


def format_applied_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return f"{iso.group(2)}/{iso.group(3)}/{iso.group(1)}"
    slash = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash:
        return f"{int(slash.group(1)):02d}/{int(slash.group(2)):02d}/{slash.group(3)}"
    return text


def date_sort_key(value: str) -> str:
    text = str(value or "").strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return iso.group(0)
    slash = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash:
        return f"{slash.group(3)}-{int(slash.group(1)):02d}-{int(slash.group(2)):02d}"
    return text


def normalize_company(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and "))
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (" inc", " llc", " ltd", " corp", " co", " recruiting"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def should_advance(current: str, nxt: str) -> bool:
    if not nxt:
        return False
    if current == nxt:
        return False
    if current == "Offer" and nxt == "Rejected":
        return False
    if nxt == "Applied" and current and current != "Applied":
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
    season: str = ""
    location_missing: bool = False
    source_url: str = ""
    useful_note: str = ""
    application_key: str = ""
    previous_key: str = ""


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


def is_generic_role(role: str) -> bool:
    return normalize_company(role) in GENERIC_ROLES


def is_placeholder(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if text.lower().startswith("review"):
        return True
    return is_generic_role(text)


def application_key(company: str, role: str, season: str = "") -> str:
    return "|".join([normalize_company(company), normalize_company(role), normalize_company(season)])


def seasons_compatible(row_season: str, hint_season: str) -> bool:
    row = normalize_company(row_season)
    hint = normalize_company(hint_season)
    if not row or not hint:
        return True
    return row == hint


def row_application_key(headers: list[str], row: list[str]) -> str:
    company_col = header_index(headers, ("company",))
    role_col = header_index(headers, ("role", "title", "position"))
    season_col = header_index(headers, ("season",))

    def cell(col: int) -> str:
        return str(row[col] or "") if 0 <= col < len(row) else ""

    return application_key(cell(company_col), cell(role_col), cell(season_col))


def find_company_row(rows: list[list[str]], company_col: int, company: str, role: str = "", role_col: int = -1) -> int:
    match = resolve_row_match(rows, company, role)
    if match["action"] == "update":
        return match["row"]
    return 0


def resolve_row_match(rows: list[list[str]], company: str, role: str, season: str = "", result: str = "Applied") -> dict:
    headers = rows[0] if rows else []
    company_col = header_index(headers, ("company",))
    role_col = header_index(headers, ("role", "title", "position"))
    season_col = header_index(headers, ("season",))
    if company_col < 0:
        return {"action": "skipped", "row": 0}
    if not normalize_company(company):
        return {"action": "skipped", "row": 0}
    company_hits: list[int] = []
    role_hits: list[int] = []
    key_hits: list[int] = []
    wanted_key = application_key(company, role, season)
    specific_role = bool(role) and not is_generic_role(role)
    for index, row in enumerate(rows[1:], start=2):
        value = row[company_col] if company_col < len(row) else ""
        if not extract.companies_match(str(value), company):
            continue
        company_hits.append(index)
        current_role = row[role_col] if role_col >= 0 and role_col < len(row) else ""
        current_season = row[season_col] if season_col >= 0 and season_col < len(row) else ""
        if (
            specific_role
            and normalize_company(str(current_role)) == normalize_company(role)
            and seasons_compatible(str(current_season), season)
        ):
            role_hits.append(index)
        if application_key(str(value), str(current_role), str(current_season)) == wanted_key:
            key_hits.append(index)
    if len(key_hits) == 1:
        return {"action": "update", "row": key_hits[0]}
    if len(key_hits) > 1:
        return {"action": "review", "row": 0}
    if len(role_hits) == 1:
        return {"action": "update", "row": role_hits[0]}
    if len(role_hits) > 1:
        return {"action": "review", "row": 0}
    if len(company_hits) == 1:
        row = rows[company_hits[0] - 1]
        current_role = str(row[role_col] or "") if role_col >= 0 and role_col < len(row) else ""
        current_season = str(row[season_col] or "") if season_col >= 0 and season_col < len(row) else ""
        # OA / interview / offer / rejection mail is about an application you already have, even if it words the role differently.
        if seasons_compatible(current_season, season) and (
            not specific_role
            or is_placeholder(current_role)
            or normalize_company(current_role) == normalize_company(role)
            or (result != "Applied" and extract.roles_similar(current_role, role))
        ):
            return {"action": "update", "row": company_hits[0]}
        return {"action": "create", "row": 0}
    if len(company_hits) > 1 and not specific_role:
        return {"action": "review", "row": 0}
    return {"action": "create", "row": 0}


def role_should_replace(current: str, nxt: str) -> bool:
    now = (current or "").strip()
    new = (nxt or "").strip()
    if not new:
        return False
    if is_placeholder(now) and not is_generic_role(new):
        return True
    from tracker.services.mailparse import clean_role_title

    if now and new and now != new and clean_role_title(now) == new:
        return True
    return False


def hint_from_mail(
    company: str,
    title: str,
    status: str,
    note: str,
    body: str = "",
    date_applied: str = "",
    thread_id: str = "",
) -> SheetHint:
    from tracker.services.mailparse import clean_role_title, compose_notes, extract_please_note, gmail_url_from_thread, infer_season

    blob = f"{title}\n{note}\n{body}"
    location = infer_location(body)
    source_url = gmail_url_from_thread(thread_id)
    useful_note = extract_please_note(body)
    notes = compose_notes(useful_note or "", source_url) or note
    role = clean_role_title(title) or title or ""
    season = infer_season(blob)
    return SheetHint(
        company=company,
        role=role,
        location=location,
        tab=choose_tab(role, blob),
        result=result_label(status),
        notes=notes,
        date_applied=format_applied_date(date_applied),
        season=season,
        location_missing=not bool(location),
        source_url=source_url,
        useful_note=useful_note,
        application_key=application_key(company, role, season),
    )


def row_needs_update(row: list[str], headers: list[str], hint: SheetHint) -> bool:
    date_col = header_index(headers, ("date applied", "applied", "date"))
    role_col = header_index(headers, ("role", "title", "position"))
    loc_col = header_index(headers, ("location",))
    season_col = header_index(headers, ("season",))
    result_col = header_index(headers, ("result", "status"))
    notes_col = header_index(headers, ("notes", "note"))

    def cell(col: int) -> str:
        if col < 0 or col >= len(row):
            return ""
        return str(row[col] or "")

    if date_col >= 0 and hint.date_applied and not cell(date_col):
        return True
    if role_col >= 0 and hint.role and role_should_replace(cell(role_col), hint.role):
        return True
    if loc_col >= 0 and hint.location and not cell(loc_col):
        return True
    if season_col >= 0 and hint.season and is_placeholder(cell(season_col)):
        return True
    if should_advance(cell(result_col), hint.result):
        return True
    if notes_col >= 0 and hint.notes:
        current = cell(notes_col)
        if any(part.strip() and part.strip() not in current for part in hint.notes.split("\n")):
            return True
    return False


def upsert_plan(rows: list[list[str]], hint: SheetHint) -> dict:
    headers = rows[0] if rows else []
    company_col = header_index(headers, ("company",))
    result_col = header_index(headers, ("result", "status"))
    if company_col < 0 or result_col < 0:
        return {"action": "skipped", "reason": "missing headers"}
    match = resolve_row_match(rows, hint.company, hint.role, hint.season, hint.result)
    if match["action"] == "review":
        return {"action": "review", "row": 0, "hint": hint}
    if match["action"] == "update":
        row = rows[match["row"] - 1]
        if row_needs_update(row, headers, hint):
            return {"action": "update", "row": match["row"], "hint": hint}
        return {"action": "skipped", "row": match["row"]}
    return {
        "action": "create",
        "row": first_empty_company_row(rows, company_col),
        "hint": hint,
    }


def _locate_application_key(grids: dict[str, list[list[str]]], key: str) -> dict | None:
    if not key:
        return None
    for tab, rows in grids.items():
        if not rows:
            continue
        headers = rows[0]
        company_col = header_index(headers, ("company",))
        for index, row in enumerate(rows[1:], start=2):
            company = row[company_col] if 0 <= company_col < len(row) else ""
            if not str(company).strip():
                continue
            if row_application_key(headers, row) == key:
                return {"tab": tab, "row": index}
    return None


def _clear_located_row(grids: dict[str, list[list[str]]], located: dict | None, keep_tab: str, keep_row: int) -> None:
    if not located or (located["tab"] == keep_tab and located["row"] == keep_row):
        return
    rows = grids[located["tab"]]
    rows[located["row"] - 1] = _blank_identity_row(rows[0], rows[located["row"] - 1])


def apply_hint_grids(grids: dict[str, list[list[str]]], hint: SheetHint) -> dict:
    tab = hint.tab if hint.tab in grids else INTERNSHIPS_TAB
    plan = upsert_plan(grids[tab], hint)
    located = _locate_application_key(grids, hint.previous_key)
    if plan["action"] == "create":
        alt = other_tab(tab)
        if alt in grids:
            other_plan = upsert_plan(grids[alt], hint)
            if other_plan.get("action") == "review":
                return {"action": "review", "row": 0}
            if other_plan.get("row") and other_plan["action"] in {"update", "skipped"}:
                if tab_from_role(hint.role) != tab:
                    # Follow-up mail without a role cannot say which tab is right; keep the row where it is.
                    tab, plan = alt, other_plan
                else:
                    from_row = other_plan["row"]
                    existing = list(grids[alt][from_row - 1])
                    dest_headers = grids[tab][0]
                    dest_company = header_index(dest_headers, ("company",))
                    dest_row = first_empty_company_row(grids[tab], dest_company)
                    carried = _realign_row(existing, grids[alt][0], dest_headers)
                    role_col = header_index(dest_headers, ("role", "title", "position"))
                    if hint.role and role_col >= 0:
                        carried[role_col] = ""
                    merged = _merged_row(dest_headers, hint, carried, tab)
                    width = max(len(dest_headers), 7)
                    while len(grids[tab]) < dest_row:
                        grids[tab].append([""] * width)
                    grids[tab][dest_row - 1] = merged
                    grids[alt][from_row - 1] = _blank_identity_row(grids[alt][0], existing)
                    return {"action": "updated", "row": dest_row, "tab": tab, "from_tab": alt, "from_row": from_row}
    if plan["action"] == "review":
        return {"action": "review", "row": 0, "tab": tab}
    if plan["action"] == "skipped":
        return {"action": "skipped", "row": plan.get("row") or 0, "tab": tab}
    headers = grids[tab][0]
    width = max(len(headers), 7)
    if plan["action"] == "create" and located:
        tab = located["tab"]
        plan = {"action": "update", "row": located["row"], "repair": True}
        headers = grids[tab][0]
        width = max(len(headers), 7)
    if plan["action"] == "create":
        row_number = plan["row"]
        merged = _merged_row(headers, hint, [""] * width, tab)
        while len(grids[tab]) < row_number:
            grids[tab].append([""] * width)
        grids[tab][row_number - 1] = merged
        return {"action": "created", "row": row_number, "tab": tab}
    row_number = plan["row"]
    existing = list(grids[tab][row_number - 1])
    hint.repairing = bool(plan.get("repair")) or row_application_key(headers, existing) == (hint.previous_key or "")
    try:
        grids[tab][row_number - 1] = _merged_row(headers, hint, existing, tab)
    finally:
        hint.repairing = False
    _clear_located_row(grids, located, tab, row_number)
    result = {"action": "updated", "row": row_number, "tab": tab}
    if located and located["tab"] != tab:
        result["from_tab"] = located["tab"]
    return result
    return chr(ord("A") + index)


def _realign_row(row: list[str], src_headers: list[str], dest_headers: list[str]) -> list[str]:
    src = {str(header or "").strip().lower(): index for index, header in enumerate(src_headers)}
    out = []
    for header in dest_headers:
        index = src.get(str(header or "").strip().lower(), -1)
        out.append(row[index] if 0 <= index < len(row) else "")
    return out


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
        "source email": hint.source_url,
        "source": hint.source_url,
        "gmail": hint.source_url,
        "email link": hint.source_url,
    }
    row = list(existing)
    for index, header in enumerate(headers):
        key = str(header or "").strip().lower()
        value = mapping.get(key, "")
        current = str(row[index] or "")
        if key in {"notes", "note"} and value:
            parts = [part.strip() for part in str(value).split("\n") if part.strip()]
            for part in parts:
                if part not in current:
                    current = f"{current}\n{part}".strip() if current else part
            row[index] = current
            continue
        if key in {"result", "status"}:
            if should_advance(current, str(value)) or not current:
                row[index] = value or current
            continue
        if key in {"role", "title", "position"}:
            repairing = bool(getattr(hint, "repairing", False)) and value and not is_generic_role(str(value))
            if role_should_replace(current, str(value)) or repairing:
                row[index] = value
            elif not current and value:
                row[index] = value
            continue
        if key in {"location"}:
            if value and not current:
                row[index] = value
            continue
        if key in {"season"}:
            if value and (is_placeholder(current) or getattr(hint, "repairing", False)):
                row[index] = value
            continue
        if value and not current:
            row[index] = value
        elif key == "company" and value:
            row[index] = value
        elif key in {"date applied", "applied", "date"} and value and not current:
            row[index] = value
        elif key in {"source email", "source", "gmail", "email link"} and value and not current:
            row[index] = value
    return row


def sort_filled_earliest_first(rows: list[list[str]]) -> list[list[str]]:
    """Same order as sortSheetByDate in Code.gs: dated rows oldest first, then undated rows, then blank rows."""
    if len(rows) < 2:
        return rows
    headers = rows[0]
    company_col = header_index(headers, ("company",))
    date_col = header_index(headers, ("date applied", "applied", "date"))
    if company_col < 0 or date_col < 0:
        return rows
    dated: list[tuple[str, list[str]]] = []
    undated: list[list[str]] = []
    empty: list[list[str]] = []
    for row in rows[1:]:
        company = row[company_col] if company_col < len(row) else ""
        if not str(company).strip():
            empty.append(row)
            continue
        key = date_sort_key(str(row[date_col] if date_col < len(row) else ""))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
            dated.append((key, row))
        else:
            undated.append(row)
    dated.sort(key=lambda item: item[0])
    return [headers] + [row for _, row in dated] + undated + empty


def _blank_identity_row(headers: list[str], existing: list[str]) -> list[str]:
    row = list(existing)
    while len(row) < len(headers):
        row.append("")
    for names in (("company",), ("role", "title", "position"), ("date applied", "applied", "date"), ("location",), ("season",), ("result", "status"), ("notes", "note"), ("source email", "source", "gmail", "email link")):
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
    review = 0
    if not spreadsheet_id or not hints:
        return {"created": created, "updated": updated, "skipped": skipped, "review": review}
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    tabs = {INTERNSHIPS_TAB, NEWGRAD_TAB} | {hint.tab for hint in hints}
    grids: dict[str, list[list[str]]] = {}
    for tab in tabs:
        payload = _sheets_execute(
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A1:G")
        )
        grids[tab] = payload.get("values") or [["Date Applied", "Company", "Role", "Location", "Season", "Result", "Notes"]]
    writes: list[dict] = []
    dirty_tabs: set[str] = set()
    for hint in hints:
        result = apply_hint_grids(grids, hint)
        action = result["action"]
        if action == "review":
            review += 1
            continue
        if action == "skipped":
            skipped += 1
            continue
        if action == "created":
            created += 1
        else:
            updated += 1
        dirty_tabs.add(result["tab"])
        if result.get("from_tab"):
            dirty_tabs.add(result["from_tab"])
    for tab in dirty_tabs:
        grid = sort_filled_earliest_first(grids[tab])
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
    return {"created": created, "updated": updated, "skipped": skipped, "review": review}
