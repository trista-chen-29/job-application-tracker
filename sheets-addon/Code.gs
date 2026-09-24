/**
 * Gmail → Trista Internship Tracker
 *
 * Install: in the spreadsheet, Extensions → Apps Script, paste this file + appsscript.json,
 * Save, then reload the sheet. Use Tracker → Sync Gmail now, then Install hourly sync.
 */

const CONFIG = {
  internshipsTab: 'internships',
  newgradTab: 'newgrad',
  logTab: '_gmail_log',
  defaultSeason: 'Summer 2027',
  lookbackDays: 730,
};

const RESULT_RANK = {
  Applied: 1,
  OA: 2,
  Interview: 3,
  Offer: 4,
  Rejected: 4,
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Tracker')
    .addItem('Sync Gmail now', 'syncGmail')
    .addItem('Recheck scraped mail', 'recheckScraped')
    .addItem('Install hourly sync', 'installHourlySync')
    .addToUi();
}

function installHourlySync() {
  ScriptApp.getProjectTriggers().forEach((trigger) => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('syncGmail').timeBased().everyHours(1).create();
  SpreadsheetApp.getActive().toast('Hourly Gmail sync is on.', 'Tracker', 8);
}

function recheckScraped() {
  const ids = Object.keys(loadProcessedIds());
  if (!ids.length) {
    SpreadsheetApp.getActive().toast('Nothing scraped yet. Use Sync Gmail now first.', 'Tracker', 8);
    return;
  }
  const props = PropertiesService.getDocumentProperties();
  let start = parseInt(props.getProperty('recheckOffset') || '0', 10);
  if (start >= ids.length) start = 0;
  const batch = ids.slice(start, start + 30);
  let created = 0;
  let updated = 0;
  let skipped = 0;
  batch.forEach((id) => {
    let message;
    try {
      message = GmailApp.getMessageById(id);
    } catch (err) {
      skipped += 1;
      return;
    }
    const hint = parseMessage(message.getFrom(), message.getSubject(), fullMessageBody(message), message.getDate());
    if (!hint) {
      skipped += 1;
      return;
    }
    const result = applyHint(hint);
    if (result === 'created') created += 1;
    else if (result === 'updated') updated += 1;
    else skipped += 1;
  });
  props.setProperty('recheckOffset', String(start + batch.length));
  const left = ids.length - (start + batch.length);
  SpreadsheetApp.getActive().toast(
    'Rechecked ' + batch.length + ': added ' + created + ', updated ' + updated + ', skipped ' + skipped +
      (left > 0 ? '. Run Recheck again for ' + left + ' more.' : '. Done with scraped mail.'),
    'Tracker',
    10
  );
}

function syncGmail() {
  const query =
    'newer_than:' +
    CONFIG.lookbackDays +
    'd (subject:"thank you for applying" OR subject:"application received" OR ' +
    'subject:"we have received your application" OR subject:"online assessment" OR ' +
    'subject:hackerrank OR subject:codesignal OR subject:"interview invitation" OR ' +
    'subject:"phone screen" OR subject:"offer of employment" OR subject:unfortunately OR ' +
    'from:recruiting OR from:careers OR from:university)';
  const threads = GmailApp.search(query, 0, 50);
  const seen = loadProcessedIds();
  let created = 0;
  let updated = 0;
  let skipped = 0;

  threads.forEach((thread) => {
    thread.getMessages().forEach((message) => {
      const id = message.getId();
      if (seen[id]) {
        skipped += 1;
        return;
      }
      const hint = parseMessage(
        message.getFrom(),
        message.getSubject(),
        fullMessageBody(message),
        message.getDate()
      );
      markProcessed(id, message.getSubject());
      seen[id] = true;
      if (!hint) {
        skipped += 1;
        return;
      }
      const result = applyHint(hint);
      if (result === 'created') created += 1;
      else if (result === 'updated') updated += 1;
      else skipped += 1;
    });
  });

  SpreadsheetApp.getActive().toast(
    'Added ' + created + ', updated ' + updated + ', skipped ' + skipped,
    'Gmail sync',
    8
  );
}

function fullMessageBody(message) {
  const plain = message.getPlainBody() || '';
  const html = htmlToText(message.getBody() || '');
  if (plain.indexOf('position of') >= 0 || plain.length >= html.length) {
    return (plain + '\n' + html).trim();
  }
  return (html + '\n' + plain).trim();
}

function htmlToText(html) {
  return String(html || '')
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|tr|h1|h2|h3|li)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseMessage(fromHeader, subject, body, date) {
  const text = (subject + '\n' + body).toLowerCase();
  const status = inferStatus(text);
  const company = inferCompany(fromHeader, subject, body);
  if (!status || !company) return null;
  return {
    company: company.slice(0, 200),
    role: inferTitle(subject, body),
    location: inferLocation(body),
    tab: chooseTab(subject + '\n' + body),
    result: status,
    notes: 'From email: ' + String(subject || '').slice(0, 180),
    dateApplied: formatDate(date),
    season: CONFIG.defaultSeason,
  };
}

function inferStatus(blob) {
  if (containsAny(blob, ['offer of employment', 'we are pleased to offer', 'congratulations on your offer'])) {
    return 'Offer';
  }
  if (
    containsAny(blob, [
      'unfortunately',
      'not moving forward',
      'moving forward with other',
      'will not be moving',
      'position has been filled',
      'not selected',
    ])
  ) {
    return 'Rejected';
  }
  if (
    containsAny(blob, [
      'online assessment',
      'hackerrank',
      'codesignal',
      'codility',
      'oa invitation',
      'complete the assessment',
    ])
  ) {
    return 'OA';
  }
  if (
    containsAny(blob, [
      'interview invitation',
      'invite you to interview',
      'schedule your interview',
      'book your interview',
      'phone screen',
      'recruiter screen',
    ])
  ) {
    return 'Interview';
  }
  if (
    containsAny(blob, [
      'thank you for applying',
      'application received',
      'we have received your application',
      'application was submitted',
      'thanks for your application',
    ])
  ) {
    return 'Applied';
  }
  return '';
}

function inferCompany(fromHeader, subject, body) {
  const blob = subject + '\n' + body;
  const patterns = [
    /thank you for applying to ([^.\n]+)/i,
    /thank you for your interest in ([^.\n]+)/i,
    /your application to ([^.\n]+)/i,
    /application to ([^.\n]+)/i,
  ];
  for (let i = 0; i < patterns.length; i += 1) {
    const match = blob.match(patterns[i]);
    if (match) {
      const company = cleanCompany(match[1]);
      if (company) return company.slice(0, 120);
    }
  }
  const display = String(fromHeader || '').replace(/<.*?>/g, '').trim();
  return cleanCompany(display);
}

function cleanCompany(name) {
  const text = String(name || '')
    .replace(/(recruiting|careers|talent acquisition team|talent acquisition|university|noreply|no-reply|do not reply)/gi, '')
    .replace(/[-|]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const junk = ['jobs', 'careers', 'recruiting', 'talent', 'no reply', 'noreply', ''];
  if (!text || text.length > 80 || text.indexOf('@') >= 0 || junk.indexOf(text.toLowerCase()) >= 0) return '';
  return text;
}

function inferTitle(subject, body) {
  const blob = subject + '\n' + String(body || '').slice(0, 4000);
  const patterns = [
    /(?:the\s+)?(?:position|role)\s+of\s+([^.\n]+)/i,
    /application for(?: the)?(?: position of| role of)?\s+([^.\n]+)/i,
    /for the\s+([^.\n]*?(?:intern(?:ship)?|co-?op|new grad)[^.\n]*)/i,
  ];
  for (let i = 0; i < patterns.length; i += 1) {
    const match = blob.match(patterns[i]);
    if (!match) continue;
    let title = match[1].replace(/\s+/g, ' ').replace(/^(?:the|a|an)\s+/i, '').replace(/\s+role$/i, '').trim();
    if (title.length >= 4) return title.slice(0, 200);
  }
  return 'Internship';
}

function inferLocation(body) {
  const match = String(body || '').match(
    /(?:location|based in|office(?:s)? in)\s*[:\-]\s*([A-Za-z0-9 .,\-/]+)/i
  );
  if (!match) return '';
  return match[1].split('\n')[0].trim().slice(0, 80);
}

function chooseTab(text) {
  const blob = String(text || '').toLowerCase();
  if (/(new[\s-]?grad|university grad|full[\s-]?time)/.test(blob) && !/intern/.test(blob)) {
    return CONFIG.newgradTab;
  }
  return CONFIG.internshipsTab;
}

function applyHint(hint) {
  const sheet = SpreadsheetApp.getActive().getSheetByName(hint.tab);
  if (!sheet) return 'skipped';
  const cols = headerMap(sheet);
  if (cols.company < 0 || cols.result < 0) return 'skipped';
  const last = Math.max(sheet.getLastRow(), 2);
  const width = sheet.getLastColumn();
  const values = sheet.getRange(1, 1, last, width).getDisplayValues();
  const matchRow = findCompanyRow(values, cols.company, hint.company);
  if (matchRow > 0) {
    const current = String(values[matchRow - 1][cols.result] || '');
    const currentRole = cols.role >= 0 ? String(values[matchRow - 1][cols.role] || '') : '';
    let changed = false;
    if (shouldAdvance(current, hint.result)) {
      writeCell(sheet, matchRow, cols.result, hint.result);
      changed = true;
    }
    if (cols.role >= 0 && roleShouldReplace(currentRole, hint.role)) {
      writeCell(sheet, matchRow, cols.role, hint.role);
      changed = true;
    }
    if (cols.notes >= 0 && hint.notes) {
      const existing = String(values[matchRow - 1][cols.notes] || '');
      if (existing.indexOf(hint.notes) === -1) {
        writeCell(sheet, matchRow, cols.notes, (hint.notes + (existing ? '\n' + existing : '')).trim());
        changed = true;
      }
    }
    return changed ? 'updated' : 'skipped';
  }
  const emptyRow = firstEmptyCompanyRow(values, cols.company);
  writeCell(sheet, emptyRow, cols.date, hint.dateApplied);
  writeCell(sheet, emptyRow, cols.company, hint.company);
  writeCell(sheet, emptyRow, cols.role, hint.role);
  if (cols.location >= 0 && hint.location) writeCell(sheet, emptyRow, cols.location, hint.location);
  if (cols.season >= 0) writeCell(sheet, emptyRow, cols.season, hint.season);
  writeCell(sheet, emptyRow, cols.result, hint.result);
  if (cols.notes >= 0) writeCell(sheet, emptyRow, cols.notes, hint.notes);
  return 'created';
}

function headerMap(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const indexOf = (names) => {
    for (let i = 0; i < headers.length; i += 1) {
      const value = String(headers[i] || '').trim().toLowerCase();
      if (names.indexOf(value) >= 0) return i;
    }
    return -1;
  };
  return {
    date: indexOf(['date applied', 'applied', 'date']),
    company: indexOf(['company']),
    role: indexOf(['role', 'title', 'position']),
    location: indexOf(['location']),
    season: indexOf(['season']),
    result: indexOf(['result', 'status']),
    notes: indexOf(['notes', 'note']),
  };
}

function findCompanyRow(values, companyCol, company) {
  const target = normalizeCompany(company);
  let found = 0;
  for (let i = 1; i < values.length; i += 1) {
    const cell = normalizeCompany(values[i][companyCol] || '');
    if (cell && cell === target) {
      if (found) return 0;
      found = i + 1;
    }
  }
  return found;
}

function firstEmptyCompanyRow(values, companyCol) {
  for (let i = 1; i < values.length; i += 1) {
    if (!String(values[i][companyCol] || '').trim()) return i + 1;
  }
  return values.length + 1;
}

function shouldAdvance(current, next) {
  if (current === 'Offer' && next === 'Rejected') return false;
  if (next === 'Offer' && current === 'Rejected') return true;
  const currentRank = RESULT_RANK[current] || 0;
  const nextRank = RESULT_RANK[next] || 0;
  if (nextRank > currentRank) return true;
  if (next === 'Rejected' && current !== 'Offer') return true;
  return false;
}

function roleShouldReplace(current, next) {
  const now = String(current || '').trim().toLowerCase();
  const nxt = String(next || '').trim();
  if (!nxt) return false;
  if ((now === '' || now === 'intern' || now === 'internship' || now === 'role') && nxt.toLowerCase() !== 'intern') return true;
  return nxt.length > String(current || '').length + 6;
}

function writeCell(sheet, row, colIndex, value) {
  if (colIndex < 0 || !value) return;
  sheet.getRange(row, colIndex + 1).setValue(value);
}

function normalizeCompany(name) {
  let text = String(name || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  [' inc', ' llc', ' ltd', ' corp', ' co', ' recruiting'].forEach((suffix) => {
    if (text.endsWith(suffix)) text = text.slice(0, -suffix.length).trim();
  });
  return text;
}

function containsAny(blob, phrases) {
  return phrases.some((phrase) => blob.indexOf(phrase) >= 0);
}

function formatDate(date) {
  if (!date) return '';
  return Utilities.formatDate(date, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}

function loadProcessedIds() {
  const sheet = ensureLogSheet();
  const last = sheet.getLastRow();
  const seen = {};
  if (last < 2) return seen;
  sheet
    .getRange(2, 1, last - 1, 1)
    .getValues()
    .forEach((row) => {
      if (row[0]) seen[String(row[0])] = true;
    });
  return seen;
}

function markProcessed(id, subject) {
  const sheet = ensureLogSheet();
  sheet.appendRow([id, new Date(), subject || '']);
}

function ensureLogSheet() {
  const book = SpreadsheetApp.getActive();
  let sheet = book.getSheetByName(CONFIG.logTab);
  if (!sheet) {
    sheet = book.insertSheet(CONFIG.logTab);
    sheet.appendRow(['message_id', 'synced_at', 'subject']);
    sheet.hideSheet();
  }
  return sheet;
}
