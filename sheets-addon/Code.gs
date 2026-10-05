/**
 * Gmail → Trista Internship Tracker
 *
 * Canonical Gmail extraction and row-merge implementation.
 * Install: Extensions → Apps Script, paste this file + appsscript.json, Save, reload the sheet.
 */

const CONFIG = {
  internshipsTab: 'internships',
  internshipsAliases: ['internships', 'internship'],
  newgradTab: 'newgrad',
  newgradAliases: ['newgrad', 'newgrads', 'new grades', 'new grade', 'new grad', 'new-grad'],
  logTab: '_gmail_log',
  lookbackDays: 730,
  parserVersion: 12,
  recheckBatch: 30,
  maxThreads: 2000,
  // Apps Script stops a run at 6 minutes; leave time to write the log and toast.
  runBudgetMs: 270000,
  // Time triggers only accept 1, 5, 10, 15, or 30 minutes.
  syncEveryMinutes: 10,
  // Each run reads this window before the older backlog. After a full pass, runs stay inside this window.
  priorityDays: 14,
  // review/failed mail is parked after this many tries so it stops consuming the run.
  parkAfter: 3,
  // Must match the Season dropdown on the internships tab.
  seasonOptions: ['Winter 2027', 'Spring 2027', 'Summer 2027'],
  // Mail from these senders is never added (for example on-campus student jobs).
  ignoreCompanies: ['SJSU Student Union'],
  locationMissingColor: '#ffd000',
  roleMissingColor: '#9fc5e8',
};

const LOG_HEADERS = [
  'message_id',
  'thread_id',
  'synced_at',
  'subject',
  'parser_version',
  'parse_status',
  'application_key',
  'tab',
  'last_error',
  'fetch_attempts',
];

const RESULT_RANK = {
  Applied: 1,
  OA: 2,
  Interview: 3,
  Offer: 4,
  Rejected: 4,
};

const GENERIC_ROLES = {
  '': true,
  role: true,
  intern: true,
  internship: true,
  internships: true,
  position: true,
  'new grad': true,
};

const PLATFORM_COMPANIES = {
  greenhouse: true,
  'greenhouse mail': true,
  lever: true,
  workday: true,
  ashby: true,
  icims: true,
  smartrecruiters: true,
  taleo: true,
  successfactors: true,
  linkedin: true,
  indeed: true,
  simplify: true,
  workable: true,
  codesignal: true,
  hackerrank: true,
  myworkday: true,
  'myworkday.com': true,
  ultipro: true,
  sapsf: true,
  oraclecloud: true,
  ashbyhq: true,
  'greenhouse-mail': true,
};

function onOpen() {
  addTrackerMenu();
}

function addTrackerMenu() {
  SpreadsheetApp.getUi()
    .createMenu('Tracker')
    .addItem('Sync Gmail now', 'syncGmail')
    .addItem('Recheck scraped mail', 'recheckScraped')
    .addItem('Reprocess all stale mail', 'reprocessAllStale')
    .addItem('Sort by Date Applied', 'sortByDateApplied')
    .addSeparator()
    .addItem('Turn on auto-sync', 'installAutoSync')
    .addItem('Turn off auto-sync', 'stopAutoSync')
    .addToUi();
}

// Run once from the Apps Script editor if the Tracker menu does not show up on reload.
function installTracker() {
  deleteTriggers('addTrackerMenu');
  ScriptApp.newTrigger('addTrackerMenu').forSpreadsheet(SpreadsheetApp.getActive()).onOpen().create();
  installAutoSync();
}

function deleteTriggers(handler) {
  ScriptApp.getProjectTriggers().forEach((trigger) => {
    if (trigger.getHandlerFunction() === handler) ScriptApp.deleteTrigger(trigger);
  });
}

function installAutoSync() {
  deleteTriggers('syncGmail');
  deleteTriggers('syncOnOpen');
  const book = SpreadsheetApp.getActive();
  ScriptApp.newTrigger('syncGmail').timeBased().everyMinutes(CONFIG.syncEveryMinutes).create();
  // A simple onOpen cannot read Gmail. This installable trigger can, after installTracker is authorized.
  ScriptApp.newTrigger('syncOnOpen').forSpreadsheet(book).onOpen().create();
  PropertiesService.getDocumentProperties().deleteProperty('autoSyncOff');
  notify(
    'Auto-sync is on. Opening the sheet syncs Gmail, and it is checked every ' + CONFIG.syncEveryMinutes + ' minutes with the sheet closed.',
    'Tracker'
  );
}

// Installable on-open handler. Do not call Gmail from the simple onOpen above.
function syncOnOpen() {
  addTrackerMenu();
  if (PropertiesService.getDocumentProperties().getProperty('autoSyncOff') === '1') return;
  syncGmail();
}

function stopAutoSync() {
  deleteTriggers('syncGmail');
  deleteTriggers('syncOnOpen');
  PropertiesService.getDocumentProperties().setProperty('autoSyncOff', '1');
  notify('Auto-sync is off. Use Sync Gmail now, or Turn on auto-sync to resume.', 'Tracker');
}

// Keeps the old menu item working for sheets that still call it.
function installHourlySync() {
  installAutoSync();
}

function ensureAutoSync() {
  const props = PropertiesService.getDocumentProperties();
  if (props.getProperty('autoSyncOff') === '1') return;
  const triggers = ScriptApp.getProjectTriggers();
  const timed = triggers.filter((trigger) => trigger.getHandlerFunction() === 'syncGmail');
  const opened = triggers.filter((trigger) => trigger.getHandlerFunction() === 'syncOnOpen');
  timed.slice(1).forEach((trigger) => ScriptApp.deleteTrigger(trigger));
  opened.slice(1).forEach((trigger) => ScriptApp.deleteTrigger(trigger));
  if (!timed.length) ScriptApp.newTrigger('syncGmail').timeBased().everyMinutes(CONFIG.syncEveryMinutes).create();
  if (!opened.length) {
    const book = SpreadsheetApp.getActive();
    if (book) ScriptApp.newTrigger('syncOnOpen').forSpreadsheet(book).onOpen().create();
  }
}

function notify(text, title) {
  try {
    SpreadsheetApp.getActive().toast(text, title, 12);
  } catch (err) {
    // Timed runs have no open sheet to show a toast in.
  }
}

function reprocessAllStale() {
  PropertiesService.getDocumentProperties().deleteProperty('recheckOffset');
  recheckScraped();
}

function recheckScraped() {
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(1000)) {
    notify('A Gmail sync is running. Try Recheck again in a minute.', 'Tracker');
    return;
  }
  try {
    runRecheck();
  } finally {
    lock.releaseLock();
  }
}

function runRecheck() {
  const log = loadLogRows();
  const stale = [];
  log.records.forEach((record) => {
    if (shouldReprocess(record)) stale.push(record);
  });
  if (!stale.length) {
    notify('Nothing stale to recheck. Sync Gmail first, or all mail is current.', 'Tracker');
    return;
  }
  const props = PropertiesService.getDocumentProperties();
  let start = parseInt(props.getProperty('recheckOffset') || '0', 10);
  if (start >= stale.length) start = 0;
  const batch = stale.slice(start, start + CONFIG.recheckBatch);
  const counts = processMessageRecords(batch, log, Date.now() + CONFIG.runBudgetMs);
  sortTrackerTabs();
  const attempted = batch.slice(0, batch.length - counts.remaining);
  const stillStale = attempted.filter((record) => shouldReprocess(log.byId[record.message_id])).length;
  // Messages that are now current drop out of the stale list, so only step past the ones still stale.
  props.setProperty('recheckOffset', String(start + stillStale));
  const left = stale.length - start - attempted.length;
  finishToast(
    'Tracker',
    counts,
    left > 0 ? '. Run Recheck again for ' + left + ' more stale messages.' : '. Stale mail caught up.'
  );
}

const GMAIL_QUERY_TERMS =
  '(subject:"thank you for applying" OR subject:"thanks for applying" OR subject:"application received" OR ' +
  'subject:"we have received your application" OR subject:"thank you for your application" OR ' +
  'subject:"your application" OR subject:"application confirmation" OR subject:"application to" OR ' +
  'subject:"application for" OR subject:"applying to" OR subject:"thank you for your interest" OR ' +
  'subject:"online assessment" OR subject:hackerrank OR subject:codesignal OR subject:"interview invitation" OR ' +
  'subject:"phone screen" OR subject:"offer of employment" OR subject:unfortunately OR ' +
  'from:recruiting OR from:careers OR from:university OR from:talent OR from:hiring OR ' +
  'from:myworkday.com OR from:greenhouse-mail.io OR from:ashbyhq.com OR from:icims.com OR ' +
  'from:lever.co OR from:smartrecruiters.com)';

function syncGmail() {
  const lock = LockService.getDocumentLock();
  // A timed run and a menu click can overlap; two writers would add the same row twice.
  if (!lock.tryLock(1000)) {
    notify('A Gmail sync is already running. Try again in a minute.', 'Gmail sync');
    return;
  }
  try {
    ensureAutoSync();
    runGmailSync();
  } finally {
    lock.releaseLock();
  }
}

function runGmailSync() {
  const started = Date.now();
  const deadline = started + CONFIG.runBudgetMs;
  const props = PropertiesService.getDocumentProperties();
  props.deleteProperty('logRebuiltThisRun');
  // A new parser version needs one full pass over old mail before timed runs go back to recent mail only.
  const caughtUp = props.getProperty('syncCaughtUp') === String(CONFIG.parserVersion);
  quarantineBlankCompanies();
  const log = loadLogRows();
  // This week's mail first. Inside one thread the older message still runs first, so the confirmation exists before the rejection.
  const recent = orderRecentFirst(
    collectMessages('newer_than:' + CONFIG.priorityDays + 'd ' + GMAIL_QUERY_TERMS, 200, log)
  );
  const counts = processMessageRecords(recent, log, deadline);
  if (!caughtUp && Date.now() < deadline) {
    const seen = {};
    recent.forEach((record) => {
      seen[record.message_id] = true;
    });
    const backlog = collectMessages('newer_than:' + CONFIG.lookbackDays + 'd ' + GMAIL_QUERY_TERMS, CONFIG.maxThreads, log)
      .filter((record) => !seen[record.message_id]);
    backlog.sort((a, b) => a._time - b._time);
    addCounts(counts, processMessageRecords(backlog, log, deadline));
  }
  sortTrackerTabs();
  let extra = '';
  if (counts.remaining) {
    props.deleteProperty('syncCaughtUp');
    extra = '. ' + counts.remaining + ' emails left; auto-sync continues in ' + CONFIG.syncEveryMinutes + ' minutes';
  } else if (!caughtUp) {
    props.setProperty('syncCaughtUp', String(CONFIG.parserVersion));
    extra = '. All matching mail is processed';
  } else {
    extra = '. Recent mail is processed';
  }
  if (props.getProperty('logRebuiltThisRun') === '1') {
    extra += '. Rebuilt the Gmail log (' + (props.getProperty('logRebuilds') || '1') + ').';
  }
  if (!counts.created && !counts.updated && !counts.review && !counts.failed && !counts.remaining) {
    notify('Up to date. Nothing new in Gmail.', 'Gmail sync');
    return;
  }
  finishToast('Gmail sync', counts, extra);
}

function collectMessages(query, maxThreads, log) {
  const threads = searchThreads(query, maxThreads);
  const records = [];
  for (let i = 0; i < threads.length; i += 100) {
    const chunk = threads.slice(i, i + 100);
    GmailApp.getMessagesForThreads(chunk).forEach((messages, j) => {
      messages.forEach((message) => {
        const existing = log.byId[message.getId()];
        if (existing && !shouldReprocess(existing)) return;
        records.push({
          message_id: message.getId(),
          thread_id: chunk[j].getId(),
          subject: message.getSubject() || '',
          parser_version: existing ? Number(existing.parser_version || 0) : 0,
          parse_status: existing ? existing.parse_status : '',
          application_key: existing ? existing.application_key || '' : '',
          fetch_attempts: existing ? Number(existing.fetch_attempts || 0) : 0,
          _message: message,
          _time: message.getDate().getTime(),
        });
      });
    });
  }
  return records;
}

function orderRecentFirst(records) {
  const groups = {};
  records.forEach((record) => {
    const key = record.thread_id || record.message_id;
    if (!groups[key]) groups[key] = [];
    groups[key].push(record);
  });
  return Object.keys(groups)
    .map((key) => {
      const messages = groups[key].sort((a, b) => a._time - b._time);
      return { newest: messages[messages.length - 1]._time, messages: messages };
    })
    .sort((a, b) => b.newest - a.newest)
    .reduce((all, group) => all.concat(group.messages), []);
}

function addCounts(total, extra) {
  ['created', 'updated', 'skipped', 'review', 'failed', 'remaining'].forEach((key) => {
    total[key] = (total[key] || 0) + (extra[key] || 0);
  });
  const reasons = extra.skippedReasons || {};
  Object.keys(reasons).forEach((name) => {
    total.skippedReasons[name] = (total.skippedReasons[name] || 0) + reasons[name];
  });
  if (extra.missingLocations && extra.missingLocations.length) {
    total.missingLocations = (total.missingLocations || []).concat(extra.missingLocations);
  }
}

function quarantineBlankCompanies() {
  const book = SpreadsheetApp.getActive();
  if (!book) return;
  [findNamedSheet(CONFIG.internshipsAliases), findNamedSheet(CONFIG.newgradAliases)].forEach((sheet) => {
    if (!sheet) return;
    const cols = headerMap(sheet);
    if (cols.company < 0) return;
    const last = sheet.getLastRow();
    if (last < 2) return;
    const width = Math.max(sheet.getLastColumn(), 1);
    const values = sheet.getRange(2, 1, last - 1, width).getValues();
    const moving = [];
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (String(values[i][cols.company] || '').trim()) continue;
      const filled = values[i].some((cell, index) => index !== cols.company && String(cell || '').trim());
      if (!filled) continue;
      moving.push(values[i]);
      sheet.deleteRow(i + 2);
    }
    if (!moving.length) return;
    const quarantine = ensureQuarantineSheet(book);
    moving.reverse().forEach((row) => quarantine.appendRow(row));
  });
}

function ensureQuarantineSheet(book) {
  let sheet = book.getSheetByName('_quarantine');
  if (!sheet) {
    sheet = book.insertSheet('_quarantine');
    const intern = findNamedSheet(CONFIG.internshipsAliases);
    const headers = intern
      ? intern.getRange(1, 1, 1, Math.max(intern.getLastColumn(), 1)).getDisplayValues()[0]
      : ['Date Applied', 'Company', 'Role', 'Location', 'Season', 'Result', 'Notes'];
    sheet.appendRow(headers);
  }
  return sheet;
}

function searchThreads(query, max) {
  const threads = [];
  while (threads.length < max) {
    const size = Math.min(100, max - threads.length);
    const page = GmailApp.search(query, threads.length, size);
    page.forEach((thread) => threads.push(thread));
    if (page.length < size) break;
  }
  return threads;
}

function shouldReprocess(record) {
  if (!record) return true;
  const status = String(record.parse_status || '');
  if (status === 'parked') return false;
  if ((status === 'failed' || status === 'review') && Number(record.fetch_attempts || 0) >= CONFIG.parkAfter) return false;
  if (status === 'failed' || status === 'review') return true;
  if (Number(record.parser_version || 0) < CONFIG.parserVersion) return true;
  return false;
}

function withAttempts(record, status) {
  let attempts = Number(record && record.fetch_attempts || 0);
  let parseStatus = status;
  if (status === 'review' || status === 'failed') {
    attempts += 1;
    if (attempts >= CONFIG.parkAfter) parseStatus = 'parked';
  } else {
    attempts = 0;
  }
  return { parse_status: parseStatus, fetch_attempts: attempts };
}

function processMessageRecords(records, log, deadline) {
  const counts = { created: 0, updated: 0, skipped: 0, review: 0, failed: 0, remaining: 0, skippedReasons: {} };
  const missingLocations = [];
  for (let index = 0; index < records.length; index += 1) {
    if (deadline && Date.now() > deadline) {
      counts.remaining = records.length - index;
      break;
    }
    const record = records[index];
    let message = record._message;
    try {
      if (!message) message = GmailApp.getMessageById(record.message_id);
    } catch (err) {
      counts.failed += 1;
      rememberLog(log, { getId: () => record.message_id, getSubject: () => record.subject || '' }, record, 'failed', {
        thread_id: record.thread_id || '',
        last_error: String(err),
      });
      continue;
    }
    const hint = parseMessage(message);
    if (hint && hint.ignored) {
      counts.skipped += 1;
      counts.skippedReasons[hint.ignored] = (counts.skippedReasons[hint.ignored] || 0) + 1;
      rememberLog(log, message, record, 'ignored', { last_error: hint.ignored });
      continue;
    }
    if (hint && record.application_key && record.application_key !== hint.applicationKey) {
      // Reprocessing repairs the row this message wrote last time instead of adding a second one.
      hint.previousKey = record.application_key;
    }
    if (!hint) {
      counts.skipped += 1;
      counts.skippedReasons['no company'] = (counts.skippedReasons['no company'] || 0) + 1;
      rememberLog(log, message, record, 'ignored', { last_error: 'no company' });
      continue;
    }
    let action = 'failed';
    try {
      action = applyHint(hint);
    } catch (err) {
      counts.failed += 1;
      rememberLog(log, message, record, 'failed', {
        thread_id: hint.threadId || safeThreadId(message),
        application_key: hint.applicationKey || '',
        tab: hint.tab || '',
        last_error: String(err),
      });
      continue;
    }
    if (hint.locationMissing && (action === 'created' || action === 'updated')) {
      missingLocations.push(hint.company);
    }
    if (action === 'created') counts.created += 1;
    else if (action === 'updated') counts.updated += 1;
    else if (action === 'review') counts.review += 1;
    else counts.skipped += 1;
    rememberLog(log, message, record, action === 'review' ? 'review' : 'applied', {
      thread_id: hint.threadId || safeThreadId(message),
      application_key: hint.applicationKey || '',
      tab: hint.tab || '',
    });
  }
  counts.missingLocations = missingLocations;
  return counts;
}

function rememberLog(log, message, record, status, fields) {
  const attempt = withAttempts(record, status);
  upsertLog(
    log,
    Object.assign(
      {
        message_id: message.getId(),
        thread_id: safeThreadId(message),
        subject: message.getSubject() || '',
        parser_version: CONFIG.parserVersion,
        application_key: '',
        tab: '',
        last_error: '',
      },
      fields || {},
      attempt
    )
  );
}

function safeThreadId(message) {
  try {
    return message.getThread().getId();
  } catch (err) {
    return '';
  }
}

function specificRole(subject, body) {
  const role = cleanRoleTitle(inferRawRole(subject, body));
  return role && !isGenericRole(role) ? role : '';
}

function fullMessageBody(message) {
  const plain = cleanText(message.getPlainBody() || '');
  const html = htmlToText(message.getBody() || '');
  if (!html) return plain;
  if (!plain || plain.length < 80) return (plain + '\n' + html).trim();
  // A long plain part can be a flattened disclaimer while the HTML still has the job title.
  if (!specificRole('', plain) && specificRole('', html)) return html;
  return plain;
}

function htmlToText(html) {
  return cleanText(
    String(html || '')
      .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/(p|div|tr|h1|h2|h3|li)>/gi, '\n')
      .replace(/<[^>]+>/g, ' ')
  );
}

function cleanText(text) {
  return String(text || '')
    .replace(/&nbsp;|\u00a0/g, ' ')
    .replace(/&#39;|&rsquo;|&#8217;|\u2019/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&#8226;/g, '•')
    .replace(/[\u200b-\u200d\ufeff]/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/ *\n[\n ]*/g, '\n')
    .trim();
}

function parseMessage(message) {
  const fromHeader = String(message.getFrom() || '');
  // Your own replies (and anything from a personal mailbox) are not recruiter mail.
  if (PERSONAL_SENDER.test(fromHeader)) return { ignored: 'personal sender' };
  const subject = cleanText(message.getSubject());
  if (NOISE_SUBJECT.test(subject)) return { ignored: 'not an application' };
  const plain = cleanText(message.getPlainBody() || '');
  const html = htmlToText(message.getBody() || '');
  const status = inferStatus(subject, (plain + '\n' + html).slice(0, 8000));
  if (!status) return { ignored: 'no status' };
  const found = inferCompany(fromHeader, subject, plain, html);
  const company = found.company;
  if (isIgnoredCompany(company)) return { ignored: 'ignored company' };
  if (!company) return { ignored: 'no company' };
  let rawRole = inferRawRole(subject, plain);
  let roleSource = plain;
  if (!specificRole(subject, plain) && specificRole(subject, html)) {
    rawRole = inferRawRole(subject, html);
    roleSource = html;
  } else if (!rawRole && html) {
    rawRole = inferRawRole(subject, html);
    roleSource = html;
  }
  const role = cleanRoleTitle(rawRole);
  if (/^student\b/i.test(role)) return { ignored: 'student job' };
  const location = roleLocation(rawRole) || inferLocation(roleSource);
  const tab = chooseTab(role, rawRole + '\n' + subject + '\n' + String(roleSource || '').slice(0, 500));
  const season = tab === CONFIG.internshipsTab ? pickSeason(rawRole, subject, roleSource) : '';
  const noteBody = extractPleaseNote(plain) ? plain : html;
  const threadId = safeThreadId(message);
  const sourceUrl = threadId ? 'https://mail.google.com/mail/u/0/#all/' + threadId : '';
  const usefulNote = extractPleaseNote(noteBody);
  return {
    company: company.slice(0, 200),
    role: role,
    roleMissing: !role,
    location: location,
    locationMissing: !location,
    tab: tab,
    result: status,
    usefulNote: usefulNote,
    sourceUrl: sourceUrl,
    notes: composeNotes(usefulNote, sourceUrl),
    // Only the confirmation date is the applied date; OA / rejection dates are not.
    dateApplied: isConfirmation(status, subject, plain + '\n' + html) ? formatDate(message.getDate()) : '',
    season: season,
    threadId: threadId,
    applicationKey: applicationKey(company, role, season),
    confidence: found.confidence,
  };
}

function inferStatus(subject, body) {
  const blob = (subject + '\n' + body).toLowerCase().replace(/\s+/g, ' ');
  if (containsAny(blob, ['offer of employment', 'we are pleased to offer', 'pleased to extend', 'congratulations on your offer'])) {
    return 'Offer';
  }
  // "Unfortunately" alone shows up in confirmations ("unfortunately, due to the high volume..."), so it is not enough.
  if (
    containsAny(blob, [
      'not be moving forward',
      'not moving forward',
      'decided not to move forward',
      'move forward with other candidates',
      'decided to pursue other',
      'regret to inform',
      'have not been selected',
      'not selected to move forward',
      'decided not to proceed',
      'will not be proceeding',
      'unable to offer you',
      'no longer under consideration',
      'position has been filled',
    ])
  ) {
    return 'Rejected';
  }
  if (
    containsAny(blob, [
      'online assessment',
      'coding assessment',
      'technical assessment',
      'coding challenge',
      'invited you to take',
      'complete the assessment',
      'hackerrank',
      'codesignal',
      'codility',
    ])
  ) {
    return 'OA';
  }
  if (
    containsAny(blob, [
      'interview invitation',
      'invite you to interview',
      'invite you to an interview',
      'schedule your interview',
      'book your interview',
      'phone screen',
      'recruiter screen',
    ])
  ) {
    return 'Interview';
  }
  if (containsAny(blob, APPLIED_PHRASES)) return 'Applied';
  return '';
}

const APPLIED_PHRASES = [
  'thank you for applying',
  'thanks for applying',
  'thank you so much for applying',
  'application received',
  'received your application',
  'received your job application',
  'application has been received',
  'application was submitted',
  'submitted successfully',
  'successfully applied',
  'thanks for your application',
  'thank you for your application',
  'thanks for completing your application',
  'application confirmation',
  'receipt of your application',
];

// Some confirmations also send the OA ("Confirmation on your Application + CodeSignal"); those still date the application.
function isConfirmation(status, subject, body) {
  if (status === 'Applied') return true;
  const blob = (subject + '\n' + body).toLowerCase().replace(/\s+/g, ' ');
  return status === 'OA' && containsAny(blob, APPLIED_PHRASES);
}

const PERSONAL_SENDER = /@(?:gmail|googlemail|yahoo|hotmail|outlook|live|icloud|me|aol|proton(?:mail)?)\.[a-z.]+>?\s*$/i;
const NOISE_SUBJECT = /verification code|verify your|passcode|registering|registration|webinar|workshop|welcome to .*careers/i;
const ROLE_WORDS =
  /\b(?:engineer(?:ing)?|developer|intern(?:ship)?s?|co-?op|scientist|analyst|technician|architect|manager|management|research(?:er)?|designer|specialist|associate|grad(?:uate)?|software|sde|swe|devops|firmware|programmer|consultant|administrator|supervisor|assistant)\b/i;

function companyFromPatterns(subject, body, patterns) {
  const head = String(body || '').slice(0, 3000);
  for (let i = 0; i < patterns.length; i += 1) {
    const source = patterns[i][0] === 'subject' ? subject : patterns[i][0] === 'both' ? subject + '\n' + head : head;
    const match = String(source || '').match(patterns[i][1]);
    if (!match) continue;
    const company = companyFromCandidate(match[1]);
    if (company) return company;
  }
  return '';
}

const EXPLICIT_COMPANY_PATTERNS = [
  ['subject', /offer of employment\s*[-–:]\s*(.+?)\s+[-–]\s/i],
  ['both', /^(.+?)\s+invited you to take\b/im],
  ['subject', /^(.+?)\s+[-–]\s+thank you\b/i],
  ['subject', /\b(?:applying|applied|application|apply)\s+(?:to|at|with)\s+([^\n]{2,120})/i],
  ['body', /\b(?:applying|applied|application|apply)\s+(?:to|at|with)\s+([^\n]{2,120})/i],
  ['body', /\b(?:role|position|opportunity|opening|job)\s+(?:here\s+)?(?:at|with)\s+([^\n]{2,80})/i],
  ['body', /\b(?:role|position) of\s+[^\n]+?\s+at\s+([^\n]{2,80})/i],
];

const WEAK_COMPANY_PATTERNS = [
  ['body', /\binterest in\s+([^\n]{2,80})/i],
  ['body', /\bjoining\s+(?:the\s+)?([^\n]{2,60})/i],
  ['body', /\bcareer with\s+([^\n]{2,60})/i],
  ['body', /(?:^|\n)\s*([A-Z][\w&.' -]{1,40}?)\s+(?:talent acquisition|human resources|recruiting|recruitment|hiring)\b/],
];

function companyResult(company, confidence) {
  return { company: company || '', confidence: company ? confidence : 0 };
}

function inferCompany(fromHeader, subject, body, altBody) {
  // "Thank you for applying to Databricks" beats a Greenhouse or "Talent Team" sender.
  const explicit =
    companyFromPatterns(subject, body, EXPLICIT_COMPANY_PATTERNS) ||
    companyFromPatterns(subject, altBody || '', EXPLICIT_COMPANY_PATTERNS);
  if (explicit) return companyResult(explicit, 0.95);
  const fromName = companyFromSender(fromHeader);
  if (fromName) return companyResult(fromName, 0.6);
  const weak =
    companyFromPatterns(subject, body, WEAK_COMPANY_PATTERNS) ||
    companyFromPatterns(subject, altBody || '', WEAK_COMPANY_PATTERNS);
  if (weak) return companyResult(weak, 0.55);
  const workday = String(fromHeader || '').match(/([a-z0-9]+)@myworkday\.com/i);
  if (workday && cleanCompany(workday[1])) return companyResult(cleanCompany(workday[1]), 0.6);
  return companyResult(companyFromDomain(fromHeader), 0.6);
}

const PLATFORM_DOMAINS = [
  'greenhouse-mail.io', 'greenhouse.io', 'myworkday.com', 'workday.com', 'ashbyhq.com', 'icims.com',
  'smartrecruiters.com', 'successfactors.eu', 'successfactors.com', 'oraclecloud.com', 'sapsf.com', 'ultipro.com',
  'workablemail.com', 'hackerrankforwork.com', 'hackerrank.com', 'codesignal.com', 'lever.co', 'taleo.net',
  'linkedin.com', 'indeed.com',
];

function companyFromDomain(fromHeader) {
  const email = ((String(fromHeader || '').match(/<([^>]+)>/) || [])[1] || String(fromHeader || '')).trim().toLowerCase();
  const host = (email.split('@')[1] || '').replace(/>.*$/, '');
  const parts = host.split('.').filter(Boolean);
  if (parts.length < 2) return '';
  const root = parts.slice(-2).join('.');
  if (PLATFORM_DOMAINS.indexOf(root) >= 0 || parts[parts.length - 1] === 'edu') return '';
  return cleanCompany(parts[parts.length - 2]);
}

function companyFromSender(fromHeader) {
  const header = String(fromHeader || '');
  const email = ((header.match(/<([^>]+)>/) || [])[1] || header).trim().toLowerCase();
  const display = header
    .replace(/<.*?>/g, '')
    .replace(/["“”]/g, '')
    .replace(/\s*@\s*icims\b.*$/i, '')
    .trim();
  if (!display || display.indexOf('@') >= 0) return '';
  const local = email.split('@')[0].split('+')[0];
  const words = display.toLowerCase().split(/\s+/).map((word) => word.replace(/[^a-z]/g, '')).filter(Boolean);
  // A recruiter's own name (Tim Farrell <tim.farrell@...>) is not the company.
  if (words.length === 2) {
    const personal = [words.join('.'), words.join('_'), words.join('-'), words[0].charAt(0) + words[1]];
    if (personal.indexOf(local) >= 0) return '';
  }
  if (/\bworkday support\b/i.test(display)) return '';
  return companyFromCandidate(display);
}

function companyFromCandidate(raw) {
  let text = cleanText(raw).split('\n')[0].replace(/\.(\s.*)?$/, '');
  // "the Platform Software Engineering Intern at Intuitive" names the company after "at".
  const around = text.split(/\s(?:at|with)\s/i);
  if (around.length > 1 && (/^(?:the|our|an?|join(?:ing)?)\s/i.test(text) || ROLE_WORDS.test(around[0]))) {
    text = around[around.length - 1];
  }
  text = text.split(/[|!?:;()\[\]]/)[0];
  text = text.split(/\s+[-–—]\s+|,(?!\s*(?:inc|llc|ltd|corp)\b)|\s+(?:and|for|we|has|is|as|to|about|in|team)\b/i)[0];
  return cleanCompany(text);
}

const GENERIC_SENDER_NAMES = {
  talent: true,
  recruiting: true,
  recruitment: true,
  notifications: true,
  notification: true,
  careers: true,
  career: true,
  hiring: true,
  jobs: true,
  hr: true,
  noreply: true,
  'no reply': true,
  'do not reply': true,
  mail: true,
  email: true,
};

function cleanCompany(name) {
  let text = cleanText(name)
    .replace(/["“”]/g, '')
    .replace(/\s*@\s*icims\b.*$/i, '')
    .replace(/\s+via\s+(?:greenhouse(?:\s+mail)?|lever|workday|ashby|icims|smartrecruiters|taleo|workable|linkedin|indeed)\b.*$/i, '')
    .replace(/^(?:\s*(?:workday[\s_-]*no[\s_-]*reply|workday|do[\s_-]*not[\s_-]*reply|no[\s_-]*reply|noreply)\b)+/i, '')
    .replace(/[_|]+/g, ' ')
    .trim();
  let previous = '';
  while (previous !== text) {
    previous = text;
    text = text
      .replace(
        /[\s,]+(?:university recruiting|recruiting|recruitment|talent acquisition|talent|hiring|human resources|hr|careers?|jobs|team|inc|llc|ltd|corp|corporation)\.?\s*$/i,
        ''
      )
      .replace(/'s$/i, '')
      .replace(/[!?.,:\s]+$/g, '')
      .trim();
  }
  if (/^[a-z0-9]+$/.test(text)) text = /\d/.test(text) ? text.toUpperCase() : text.charAt(0).toUpperCase() + text.slice(1);
  const lower = text.toLowerCase();
  if (!text || text.length > 60 || text.split(/\s+/).length > 6 || text.indexOf('@') >= 0) return '';
  if (PLATFORM_COMPANIES[lower] || GENERIC_SENDER_NAMES[lower]) return '';
  if (lower === 'us' || lower === 'our' || lower === 'team' || lower === 'human resources' || lower === 'talent acquisition' || lower === 'workday support' || lower === 'legal') return '';
  if (/^(?:the|our|a|an|one|this|joining|being|your|my|dear|hi|hello|candidate|campus|join|any|team)\b/i.test(text)) return '';
  if (/\blogging\b/i.test(text)) return '';
  if (ROLE_WORDS.test(text) || /thank|application|applying|campus/i.test(text)) return '';
  return text;
}

function isIgnoredCompany(company) {
  const name = normalizeCompany(company);
  return CONFIG.ignoreCompanies.some((ignored) => normalizeCompany(ignored) === name);
}

const ROLE_TEXT = "((?:(?!\\.\\s)[^\\n!?])+?)";
const ROLE_PATTERNS = [
  ['s', /offer of employment\s*[-–]\s*.+?\s[-–]\s(.+?)(?:\s[-–]\s[^-–]+)?$/gi],
  ['b', new RegExp('\\bapplication for\\s+(?:the\\s+)?' + ROLE_TEXT + '\\s*\\((?:job number|job id|req)', 'gi')],
  [
    'sb',
    new RegExp(
      "\\b(?:applying|apply|applied|application|interest|considered|fit)\\s+(?:to|for|in)\\s+(?:the\\s+|our\\s+|an?\\s+)?(?:[A-Z][\\w.&-]*'s\\s+)?" +
        ROLE_TEXT +
        '\\s+(?:role|position|opening|opportunity|job)\\b',
      'gi'
    ),
  ],
  ['b', new RegExp('\\brole of\\s+' + ROLE_TEXT + '\\s+at\\s', 'gi')],
  ['sb', new RegExp('\\b(?:application|applying) to\\s+(?:the\\s+)?' + ROLE_TEXT + '\\s+at\\s', 'gi')],
  ['b', new RegExp('\\bposition of\\s+' + ROLE_TEXT + '\\s*(?:\\.|has been|$)', 'gim')],
  ['b', new RegExp('\\bapplication for\\s+(?:the\\s+)?' + ROLE_TEXT + '\\s*(?:\\.|has been|was|is)(?:\\s|$)', 'gim')],
  ['b', new RegExp('\\b(?:apply|applying) for\\s+(?:the\\s+)?' + ROLE_TEXT + '\\s*[!.]', 'gi')],
  ['s', /application received\s*(?:for|[-–:])\s*(.+)$/gi],
  ['s', /applying for\s+(.+)$/gi],
  ['s', /received your application for\s+(.+)$/gi],
  ['s', /your application(?: for)?\s*:?\s+(.+)$/gi],
  ['s', /application confirmation\s*[-–:]\s*(.+)$/gi],
  ['s', /\|\s*([^|]+)$/g],
];

function inferRawRole(subject, body) {
  // Try the original line breaks first. Flatten only if a wrapped title was split in two.
  const rawBody = String(body || '').slice(0, 4000);
  const flatBody = rawBody.replace(/\s*\n\s*/g, ' ');
  const texts = { s: [String(subject || '')], b: rawBody === flatBody ? [rawBody] : [rawBody, flatBody] };
  for (let i = 0; i < ROLE_PATTERNS.length; i += 1) {
    const where = ROLE_PATTERNS[i][0];
    const pattern = ROLE_PATTERNS[i][1];
    for (let j = 0; j < where.length; j += 1) {
      const options = texts[where[j]] || [];
      for (let k = 0; k < options.length; k += 1) {
        pattern.lastIndex = 0;
        let match;
        while ((match = pattern.exec(options[k])) !== null) {
          const raw = match[1].trim();
          if (isValidRole(raw)) return raw;
          if (!pattern.global) break;
        }
      }
    }
  }
  return '';
}

function isValidRole(raw) {
  const role = cleanRoleTitle(raw);
  if (role.length < 3 || role.length > 150) return false;
  if (!ROLE_WORDS.test(role)) return false;
  // "Role" or "Internship" is not the job title. Keep looking.
  if (isGenericRole(role)) return false;
  if (/https?:|awstrack\.me|@/i.test(role)) return false;
  return !/\b(?:thank|application|applying|your|we|you)\b/i.test(role);
}

function cleanRoleTitle(title) {
  let text = cleanText(title).replace(/\s+/g, ' ');
  if (/\band the\s/i.test(text)) text = text.replace(/^.*\band the\s+/i, '');
  text = text.replace(/^(?:the|a|an|our)\s+/i, '');
  text = text.replace(/^R\d{5,}\s+/i, '');
  text = text.replace(/\s*[\(\[](?:job number|job id|id|req)?[#:\s]*[\w-]*\d{3,}[\w-]*\s*[\)\]]/gi, '');
  text = text.replace(/\s+[-–]\s+(?:[a-z]-)?\d{3,}[\d-]*$/i, '');
  text = text.replace(/\s+\d{5,}$/, '');
  text = text.replace(/\s*[\(\[][^)\]]*(?:20\d{2}|start|summer|winter|fall|spring)[^)\]]*[\)\]]/gi, '');
  text = text.replace(/\s*[-–—,]?\s*\b(?:summer|winter|fall|autumn|spring)\s+20\d{2}\b/gi, '');
  text = text.replace(/\s*[-–—,]?\s*\b20\d{2}\s+(?:summer|winter|fall|autumn|spring)\b/gi, '');
  text = text.replace(/\s*[-–—,]\s*(?:summer|winter|fall|autumn|spring)\s*$/i, '');
  text = text.replace(/\s+[-–—]\s+[A-Z][A-Za-z .]+,\s*[A-Z]{2}$/, '');
  text = text.replace(/\s+at\s+[A-Z].*$/, '');
  text = text.replace(/\s*[-–]\s*20\d{2}\b(?=\s*(?:\(|$))/, '');
  text = text.replace(/\s+20\d{2}$/, '');
  text = text.replace(/\s+,/g, ',');
  text = text.replace(/https?:\S+/gi, '').replace(/\bawstrack\.me\S*/gi, '');
  text = text.replace(/\s+(?:role|position|opening|opportunity|job)$/i, '');
  text = text.replace(/\s+has been received.*$/i, '');
  return text.replace(/\s+/g, ' ').replace(/^[-–—,: ]+|[-–—,: ]+$/g, '').slice(0, 150);
}

function roleLocation(rawRole) {
  const match = String(rawRole || '').match(/\s[-–—]\s([A-Z][A-Za-z .]+,\s*[A-Z]{2})\s*$/);
  return match ? match[1].trim() : '';
}

function pickSeason(rawRole, subject, body) {
  const sources = [
    [rawRole, true],
    [subject, true],
    [String(body || '').slice(0, 1500), false],
  ];
  for (let i = 0; i < sources.length; i += 1) {
    const found = findSeason(sources[i][0], sources[i][1]);
    if (found) return CONFIG.seasonOptions.indexOf(found) >= 0 ? found : '';
  }
  return '';
}

function inferSeason(text) {
  const found = findSeason(text, true);
  return CONFIG.seasonOptions.indexOf(found) >= 0 ? found : '';
}

function findSeason(text, loose) {
  const blob = String(text || '');
  const named = blob.match(/\b(summer|winter|fall|autumn|spring)\s+(20\d{2})\b/i);
  if (named) return seasonName(named[1]) + ' ' + named[2];
  const reversed = blob.match(/\b(20\d{2})\s+(summer|winter|fall|autumn|spring)\b/i);
  if (reversed) return seasonName(reversed[2]) + ' ' + reversed[1];
  if (!loose) return '';
  // "(2027 Start) - Winter" states both pieces. A season word plus an unrelated year does not.
  const start = blob.match(/\((20\d{2})\s*start\)/i);
  const seasonWord = blob.match(/\b(summer|winter|fall|autumn|spring)\b/i);
  return start && seasonWord ? seasonName(seasonWord[1]) + ' ' + start[1] : '';
}

function seasonName(name) {
  const text = String(name || '').toLowerCase();
  if (text === 'autumn') return 'Fall';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function composeNotes(usefulNote, sourceUrl) {
  const parts = [];
  if (usefulNote) parts.push(usefulNote);
  if (sourceUrl) parts.push('Source: ' + sourceUrl);
  return parts.join('\n');
}

function extractPleaseNote(body) {
  const text = String(body || '');
  const match = text.match(
    /please note(?: that)?[:\s]+([\s\S]+?)(?:\n\s*\n|\n\s*regards|\n\s*\*\*\s*please note:\s*do not reply|$)/i
  );
  if (match) {
    let note = String(match[0] || '')
      .replace(/\s+/g, ' ')
      .replace(/\s*\*+\s*please note:.*$/i, '')
      .trim();
    if (/do not reply/i.test(note) && !/official communication|email addresses ending/i.test(note)) {
      note = '';
    }
    const sentence = note.match(/^.*?[.!?](?=\s|$)/);
    if (sentence) note = sentence[0];
    if (note) return clipText(note);
  }
  const official = text.match(/[^.]*official communication[^.]*\./i);
  return official ? clipText(official[0].trim()) : '';
}

function clipText(text, limit) {
  const value = String(text || '').trim();
  const max = limit || 5000;
  if (value.length <= max) return value;
  const window = value.slice(0, max);
  const marks = ['. ', '! ', '? ', ' '];
  for (let i = 0; i < marks.length; i += 1) {
    const end = window.lastIndexOf(marks[i]);
    if (end >= 40) return window.slice(0, marks[i] === ' ' ? end : end + 1).trim();
  }
  return window.trim();
}

function inferLocation(body) {
  const text = String(body || '');
  const labeled = text.match(/\blocation\s*:\s*([A-Z][A-Za-z .]+,\s*[A-Z]{2}\b|remote|hybrid)/i);
  if (labeled) return cleanLocation(labeled[1]);
  const placed = text.match(/\b(?:based in|located in|office in)\s+([A-Z][A-Za-z .]+,\s*[A-Z]{2})\b/);
  return placed ? cleanLocation(placed[1]) : '';
}

function cleanLocation(value) {
  const text = String(value || '').trim();
  if (/^\d+\s/.test(text) || /\b(?:court|street|avenue|road|drive|lane|blvd|boulevard)\b/i.test(text)) return '';
  return text;
}

function chooseTab(title, body) {
  const role = String(title || '').trim();
  if (isInternRole(role) && !isGenericRole(role) && !isNewGradRole(role)) return CONFIG.internshipsTab;
  if (isNewGradRole(role)) return CONFIG.newgradTab;
  // A real title such as "Software Engineer" is new-grad. A footer that mentions interns does not move it.
  if (role && !isGenericRole(role)) return CONFIG.newgradTab;
  const blob = String(body || '').slice(0, 500);
  const intern = isInternRole(blob);
  const grad = isNewGradRole(blob);
  if (intern && !grad) return CONFIG.internshipsTab;
  if (grad) return CONFIG.newgradTab;
  // No role and no intern/new-grad words: do not assume new-grad.
  return CONFIG.internshipsTab;
}

function tabFromRole(role) {
  const text = String(role || '').trim();
  if (isNewGradRole(text)) return CONFIG.newgradTab;
  if (isInternRole(text) && !isGenericRole(text)) return CONFIG.internshipsTab;
  return '';
}

function isInternRole(text) {
  return /\b(?:intern(?:ship)?s?|co-?ops?|seasonal)\b/i.test(String(text || ''));
}

function isNewGradRole(text) {
  return /\b(?:new[\s-]?grads?(?:uate)?s?|university[\s-]?grads?(?:uate)?s?|college[\s-]?grads?(?:uate)?s?|recent[\s-]?grads?(?:uate)?s?|early[\s-]?career|entry[\s-]?level)\b/i.test(
    String(text || '')
  );
}

function isGenericRole(role) {
  return !!GENERIC_ROLES[normalizeCompany(role)];
}

function isPlaceholder(value) {
  const text = String(value || '').trim();
  if (!text) return true;
  if (/^review\b/i.test(text)) return true;
  return isGenericRole(text);
}

function applicationKey(company, role, season) {
  return [normalizeCompany(company), normalizeCompany(role), normalizeCompany(season)].join('|');
}

function sheetForTab(tab) {
  const compact = String(tab || '').toLowerCase().replace(/\s+/g, '');
  const internWanted = CONFIG.internshipsAliases.map((name) => name.toLowerCase().replace(/\s+/g, ''));
  if (internWanted.indexOf(compact) >= 0) return findNamedSheet(CONFIG.internshipsAliases);
  return findNamedSheet(CONFIG.newgradAliases);
}

function findNamedSheet(aliases) {
  const sheets = SpreadsheetApp.getActive().getSheets();
  const wanted = aliases.map((name) => String(name).toLowerCase().replace(/\s+/g, ''));
  for (let i = 0; i < sheets.length; i += 1) {
    const compact = sheets[i].getName().toLowerCase().replace(/\s+/g, '');
    if (wanted.indexOf(compact) >= 0) return sheets[i];
  }
  return SpreadsheetApp.getActive().getSheetByName(aliases[0]);
}

function otherTab(tab) {
  const internSheet = findNamedSheet(CONFIG.internshipsAliases);
  const gradSheet = findNamedSheet(CONFIG.newgradAliases);
  const compact = String(tab || '').toLowerCase().replace(/\s+/g, '');
  const internWanted = CONFIG.internshipsAliases.map((name) => name.toLowerCase().replace(/\s+/g, ''));
  if (internWanted.indexOf(compact) >= 0) return gradSheet ? gradSheet.getName() : CONFIG.newgradTab;
  return internSheet ? internSheet.getName() : CONFIG.internshipsTab;
}

function applyHint(hint) {
  // Missing confidence is not a pass. Only an explicit "applying to X" parse is trusted enough to write a row.
  if (!(Number(hint.confidence) >= 0.9)) return 'review';
  const intended = sheetForTab(hint.tab);
  if (!intended) return 'skipped';
  const match = findApplicationMatch(hint);
  if (match.status === 'review') return 'review';
  if (match.repair) hint.repair = true;
  let action = 'created';
  if (match.status === 'move') {
    const destCols = headerMap(intended);
    const destRow = placeNewRow(intended, destCols);
    copyMergedRow(intended, destRow, destCols, hint, match.values, match.cols);
    clearTrackerRow(match.sheet, match.row, match.cols);
    action = 'updated';
  } else if (match.status === 'update') {
    action = mergeIntoRow(match.sheet, match.row, match.cols, match.values, hint);
  } else {
    const cols = headerMap(intended);
    if (cols.company < 0 || cols.result < 0) return 'skipped';
    const destRow = placeNewRow(intended, cols);
    copyMergedRow(intended, destRow, cols, hint, null, cols);
  }
  if (match.clearStale) clearTrackerRow(match.clearStale.sheet, match.clearStale.row, match.clearStale.cols);
  return action;
}

function findApplicationMatch(hint) {
  const tabs = [hint.tab, otherTab(hint.tab)];
  const seen = {};
  const companyHits = [];
  const roleHits = [];
  const keyHits = [];
  const repairHits = [];
  tabs.forEach((tabName) => {
    if (!tabName || seen[tabName]) return;
    seen[tabName] = true;
    const sheet = sheetForTab(tabName);
    if (!sheet) return;
    const cols = headerMap(sheet);
    if (cols.company < 0) return;
    const last = Math.max(sheet.getLastRow(), 1);
    const width = Math.max(sheet.getLastColumn(), 1);
    const values = sheet.getRange(1, 1, last, width).getDisplayValues();
    for (let i = 1; i < values.length; i += 1) {
      const role = cols.role >= 0 ? String(values[i][cols.role] || '') : '';
      const season = cols.season >= 0 ? String(values[i][cols.season] || '') : '';
      const hit = { sheet, row: i + 1, cols, values: values[i], tab: tabName };
      if (hint.previousKey && applicationKey(values[i][cols.company], role, season) === hint.previousKey) {
        repairHits.push(hit);
      }
      if (!companiesMatch(values[i][cols.company], hint.company)) continue;
      companyHits.push(hit);
      if (
        hint.role &&
        !isGenericRole(hint.role) &&
        normalizeCompany(role) === normalizeCompany(hint.role) &&
        seasonsCompatible(season, hint.season)
      ) {
        roleHits.push(hit);
      }
      if (applicationKey(hint.company, hint.role, hint.season) === applicationKey(values[i][cols.company], role, season)) {
        keyHits.push(hit);
      }
    }
  });
  // Follow-up mail without a role cannot say which tab is right, so it never moves a row.
  const place = (hit) =>
    Object.assign({ status: hit.tab === hint.tab || tabFromRole(hint.role) !== hint.tab ? 'update' : 'move' }, hit);
  let chosen;
  if (keyHits.length === 1) chosen = place(keyHits[0]);
  else if (keyHits.length > 1) chosen = { status: 'review' };
  else if (roleHits.length === 1) chosen = place(roleHits[0]);
  else if (roleHits.length > 1) chosen = { status: 'review' };
  else if (companyHits.length === 1 && seasonsCompatible(seasonOfHit(companyHits[0]), hint.season)) {
    const currentRole = companyHits[0].cols.role >= 0 ? String(companyHits[0].values[companyHits[0].cols.role] || '') : '';
    // OA / interview / offer / rejection mail is about an application you already have, even if it words the role differently.
    if (
      isGenericRole(hint.role) ||
      isPlaceholder(currentRole) ||
      normalizeCompany(currentRole) === normalizeCompany(hint.role) ||
      (hint.result !== 'Applied' && rolesSimilar(currentRole, hint.role))
    ) {
      chosen = place(companyHits[0]);
    } else chosen = { status: 'create' };
  } else if (companyHits.length > 1 && isGenericRole(hint.role)) chosen = { status: 'review' };
  else chosen = { status: 'create' };
  if (hint.previousKey && repairHits.length === 1 && chosen.status !== 'review') {
    const repair = repairHits[0];
    const same = chosen.sheet === repair.sheet && chosen.row === repair.row;
    if (chosen.status === 'create') return Object.assign(place(repair), { repair: true });
    if (!same && (chosen.status === 'update' || chosen.status === 'move')) chosen.clearStale = repair;
    if (same) chosen.repair = true;
  }
  return chosen;
}

function seasonOfHit(hit) {
  return hit.cols.season >= 0 ? String(hit.values[hit.cols.season] || '') : '';
}

function seasonsCompatible(rowSeason, hintSeason) {
  const row = normalizeCompany(rowSeason);
  const hint = normalizeCompany(hintSeason);
  if (!row || !hint) return true;
  return row === hint;
}

function placeNewRow(sheet, cols) {
  // getLastRow() ignores rows that only hold dropdowns, so scan every physical row.
  const maxRows = Math.max(sheet.getMaxRows(), 1);
  const width = Math.max(sheet.getLastColumn(), 1);
  const companies = sheet.getRange(1, cols.company + 1, maxRows, 1).getDisplayValues();
  const empty = firstEmptyCompanyRow(companies, 0);
  if (empty <= maxRows) return empty;
  sheet.insertRowAfter(maxRows);
  const newRow = maxRows + 1;
  if (maxRows >= 2) {
    const source = sheet.getRange(maxRows, 1, 1, width);
    const target = sheet.getRange(newRow, 1, 1, width);
    source.copyTo(target, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
    source.copyTo(target, SpreadsheetApp.CopyPasteType.PASTE_DATA_VALIDATION, false);
  }
  return newRow;
}

function copyMergedRow(sheet, row, cols, hint, existingValues, existingCols) {
  const existing = existingValues || [];
  const src = existingCols || cols;
  const date = hint.dateApplied || cellValue(existing, src.date);
  const role = hint.role || cellValue(existing, src.role);
  const location = hint.location || cellValue(existing, src.location);
  const season = hint.season || cellValue(existing, src.season);
  const result = pickResult(cellValue(existing, src.result), hint.result);
  const notes = mergeNotes(cellValue(existing, src.notes), hint.notes);
  writeCell(sheet, row, cols.date, date);
  writeCell(sheet, row, cols.company, hint.company);
  writeFlagged(sheet, row, cols.role, role, CONFIG.roleMissingColor);
  writeFlagged(sheet, row, cols.location, location, CONFIG.locationMissingColor);
  if (cols.season >= 0) writeCell(sheet, row, cols.season, season);
  writeCell(sheet, row, cols.result, result || 'Applied');
  if (cols.notes >= 0) writeCell(sheet, row, cols.notes, notes);
  if (cols.source >= 0 && hint.sourceUrl) writeCell(sheet, row, cols.source, hint.sourceUrl);
}

function mergeIntoRow(sheet, row, cols, existing, hint) {
  let changed = false;
  const currentDate = cellValue(existing, cols.date);
  const currentCompany = cellValue(existing, cols.company);
  const currentRole = cellValue(existing, cols.role);
  const currentLoc = cellValue(existing, cols.location);
  const currentSeason = cellValue(existing, cols.season);
  const currentResult = cellValue(existing, cols.result);
  const currentNotes = cellValue(existing, cols.notes);
  if (!currentDate && hint.dateApplied) {
    writeCell(sheet, row, cols.date, hint.dateApplied);
    changed = true;
  }
  if (
    cols.company >= 0 &&
    hint.company &&
    normalizeCompany(currentCompany) !== normalizeCompany(hint.company) &&
    (hint.repair || companyShouldReplace(currentCompany, hint.company))
  ) {
    writeCell(sheet, row, cols.company, hint.company);
    changed = true;
  }
  const replaceRole =
    (hint.repair && hint.role && !isGenericRole(hint.role)) ||
    isPlaceholder(currentRole) ||
    roleShouldReplace(currentRole, hint.role);
  if (cols.role >= 0 && hint.role && replaceRole) {
    writeFlagged(sheet, row, cols.role, hint.role, CONFIG.roleMissingColor);
    changed = true;
  } else if (cols.role >= 0 && !currentRole) {
    writeFlagged(sheet, row, cols.role, '', CONFIG.roleMissingColor);
  }
  if (cols.location >= 0) {
    if (!currentLoc && hint.location) {
      writeFlagged(sheet, row, cols.location, hint.location, CONFIG.locationMissingColor);
      changed = true;
    } else if (!currentLoc) {
      writeFlagged(sheet, row, cols.location, '', CONFIG.locationMissingColor);
    }
  }
  if (cols.season >= 0 && hint.season && (hint.repair || !currentSeason || isPlaceholder(currentSeason))) {
    writeCell(sheet, row, cols.season, hint.season);
    changed = true;
  }
  if (shouldAdvance(currentResult, hint.result)) {
    writeCell(sheet, row, cols.result, hint.result);
    changed = true;
  }
  if (cols.notes >= 0 && hint.notes) {
    const merged = mergeNotes(currentNotes, hint.notes);
    if (merged !== currentNotes) {
      writeCell(sheet, row, cols.notes, merged);
      changed = true;
    }
  }
  if (cols.source >= 0 && hint.sourceUrl && cellValue(existing, cols.source) !== hint.sourceUrl) {
    writeCell(sheet, row, cols.source, hint.sourceUrl);
    changed = true;
  }
  return changed ? 'updated' : 'skipped';
}

function cellValue(row, col) {
  if (!row || col < 0 || col >= row.length) return '';
  return String(row[col] || '');
}

function pickResult(current, incoming) {
  if (shouldAdvance(current, incoming)) return incoming;
  return current || incoming;
}

function sourceThreadId(line) {
  const url = String(line || '').replace(/^source:\s*/i, '').trim();
  const match = url.match(/([0-9a-f]{10,})/i);
  return match ? match[1].toLowerCase() : '';
}

function mergeNotes(current, incoming) {
  const lines = (String(current || '') + '\n' + String(incoming || '')).split(/\n+/);
  const out = [];
  const sourceAt = {};
  lines.forEach((line) => {
    const part = line.trim();
    if (!part) return;
    if (/^source:/i.test(part)) {
      const id = sourceThreadId(part);
      const key = id || part.toLowerCase();
      const previous = sourceAt[key];
      if (previous === undefined) {
        // A short "https://mail.google.com/mail/" is the same link as the full thread URL already stored.
        const richer = id ? out.findIndex((item) => sourceThreadId(item) === id) : -1;
        if (richer >= 0) {
          if (part.length > out[richer].length) out[richer] = part;
          sourceAt[key] = richer;
          return;
        }
        const prefix = out.findIndex((item) => {
          if (!/^source:/i.test(item)) return false;
          const left = item.replace(/^source:\s*/i, '').trim();
          const right = part.replace(/^source:\s*/i, '').trim();
          return left.indexOf(right) === 0 || right.indexOf(left) === 0;
        });
        if (prefix >= 0) {
          if (part.length > out[prefix].length) out[prefix] = part;
          sourceAt[key] = prefix;
          return;
        }
        sourceAt[key] = out.length;
        out.push(part);
      } else if (part.length > out[previous].length) {
        out[previous] = part;
      }
      return;
    }
    if (out.indexOf(part) === -1) out.push(part);
  });
  return out.join('\n');
}

function clearTrackerRow(sheet, row, cols) {
  ['date', 'company', 'role', 'location', 'season', 'result', 'notes', 'source'].forEach((key) => {
    if (cols[key] < 0) return;
    const cell = sheet.getRange(row, cols[key] + 1);
    // Result and Season dropdowns reject a blank, which aborts the whole sync.
    clearCellKeepingValidation(cell);
    if (key === 'location' || key === 'role') cell.setBackground(null);
  });
}

function clearCellKeepingValidation(cell) {
  const rule = typeof cell.getDataValidation === 'function' ? cell.getDataValidation() : null;
  if (rule && typeof cell.setDataValidation === 'function') cell.setDataValidation(null);
  // The dropdown is still enforced until this flush. Writing first makes Sheets reject the blank.
  if (rule && typeof SpreadsheetApp.flush === 'function') SpreadsheetApp.flush();
  cell.setValue('');
  if (rule && typeof cell.setDataValidation === 'function') cell.setDataValidation(rule);
}

function headerMap(sheet) {
  const headers = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getDisplayValues()[0];
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
    source: indexOf(['source email', 'source', 'gmail', 'email link']),
  };
}

function firstEmptyCompanyRow(values, companyCol) {
  for (let i = 1; i < values.length; i += 1) {
    if (!String(values[i][companyCol] || '').trim()) return i + 1;
  }
  return values.length + 1;
}

function sortByDateApplied() {
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(1000)) {
    notify('A Gmail sync is running. Try again in a minute.', 'Tracker');
    return;
  }
  try {
    const moved = sortTrackerTabs();
    notify(moved ? 'Rows sorted from earliest to latest Date Applied.' : 'Rows are already in Date Applied order.', 'Tracker');
  } finally {
    lock.releaseLock();
  }
}

function sortTrackerTabs() {
  let moved = false;
  [findNamedSheet(CONFIG.internshipsAliases), findNamedSheet(CONFIG.newgradAliases)].forEach((sheet) => {
    if (!sheet) return;
    try {
      if (sortSheetByDate(sheet)) moved = true;
      paintMissingFields(sheet);
    } catch (err) {
      notify('Could not sort ' + sheet.getName() + ': ' + err, 'Tracker');
    }
  });
  return moved;
}

function reorderRows(grid, order) {
  return order.map((item) => grid[item.i]);
}

function sameColor(a, b) {
  const norm = (color) => String(color || '').replace(/#/g, '').toLowerCase();
  return norm(a) !== '' && norm(a) === norm(b);
}

function isTrackerHighlight(color) {
  return sameColor(color, CONFIG.roleMissingColor) || sameColor(color, CONFIG.locationMissingColor);
}

// Earliest Date Applied first; rows without a date follow in their current order; blank rows stay at the bottom.
// Rows are rewritten in place. A temporary column plus Range.sort was clearing fills and link colors.
function sortSheetByDate(sheet) {
  const cols = headerMap(sheet);
  const last = sheet.getLastRow();
  if (cols.company < 0 || cols.date < 0 || last < 3) return false;
  const width = sheet.getLastColumn();
  const body = sheet.getRange(2, 1, last - 1, width);
  const values = body.getValues();
  const order = values
    .map((row, i) => {
      const filled = String(row[cols.company] || '').trim() !== '';
      const time = filled ? dateSortValue(row[cols.date]) : null;
      return { i: i, tier: !filled ? 2 : time === null ? 1 : 0, time: time || 0 };
    })
    .sort((a, b) => a.tier - b.tier || a.time - b.time || a.i - b.i);
  if (order.every((item, pos) => item.i === pos)) return false;
  const rules = typeof body.getDataValidations === 'function' ? body.getDataValidations() : null;
  const backgrounds = typeof body.getBackgrounds === 'function' ? body.getBackgrounds() : null;
  const rich = typeof body.getRichTextValues === 'function' ? body.getRichTextValues() : null;
  const fontColors = !rich && typeof body.getFontColors === 'function' ? body.getFontColors() : null;
  // A Result value Sheets does not like (a blank, or a status outside the dropdown) aborts the write.
  if (rules) {
    body.setDataValidation(null);
    if (typeof SpreadsheetApp.flush === 'function') SpreadsheetApp.flush();
  }
  body.setValues(reorderRows(values, order));
  if (rich && typeof body.setRichTextValues === 'function') body.setRichTextValues(reorderRows(rich, order));
  if (fontColors && typeof body.setFontColors === 'function') body.setFontColors(reorderRows(fontColors, order));
  if (backgrounds && typeof body.setBackgrounds === 'function') body.setBackgrounds(reorderRows(backgrounds, order));
  if (rules && typeof body.setDataValidations === 'function') body.setDataValidations(reorderRows(rules, order));
  return true;
}

// Blank Role and Location get their highlight back. Filled cells keep whatever color they already have.
function paintMissingFields(sheet) {
  const cols = headerMap(sheet);
  const last = sheet.getLastRow();
  if (!sheet || cols.company < 0 || last < 2) return;
  const width = Math.max(sheet.getLastColumn(), 1);
  const range = sheet.getRange(2, 1, last - 1, width);
  if (typeof range.getBackgrounds !== 'function' || typeof range.setBackgrounds !== 'function') return;
  const values = range.getValues();
  const backgrounds = range.getBackgrounds();
  let changed = false;
  for (let i = 0; i < values.length; i += 1) {
    if (!String(values[i][cols.company] || '').trim()) continue;
    if (cols.role >= 0 && !String(values[i][cols.role] || '').trim() && !sameColor(backgrounds[i][cols.role], CONFIG.roleMissingColor)) {
      backgrounds[i][cols.role] = CONFIG.roleMissingColor;
      changed = true;
    }
    if (
      cols.location >= 0 &&
      !String(values[i][cols.location] || '').trim() &&
      !sameColor(backgrounds[i][cols.location], CONFIG.locationMissingColor)
    ) {
      backgrounds[i][cols.location] = CONFIG.locationMissingColor;
      changed = true;
    }
  }
  if (changed) range.setBackgrounds(backgrounds);
}

function dateSortValue(value) {
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return isNaN(value.getTime()) ? null : value.getTime();
  }
  const text = String(value || '').trim();
  let m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
  if (m) return new Date(m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]), Number(m[1]) - 1, Number(m[2])).getTime();
  m = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime();
  return null;
}

function shouldAdvance(current, next) {
  if (!next) return false;
  if (current === next) return false;
  if (current === 'Offer' && next === 'Rejected') return false;
  if (next === 'Applied' && current && current !== 'Applied') return false;
  if (next === 'Offer' && current === 'Rejected') return true;
  const currentRank = RESULT_RANK[current] || 0;
  const nextRank = RESULT_RANK[next] || 0;
  if (nextRank > currentRank) return true;
  if (next === 'Rejected' && current !== 'Offer') return true;
  return false;
}

function roleShouldReplace(current, next) {
  const now = String(current || '').trim();
  const nxt = String(next || '').trim();
  if (!nxt) return false;
  if (isPlaceholder(now) && !isGenericRole(nxt)) return true;
  if (now && nxt && now !== nxt && cleanRoleTitle(now) === nxt) return true;
  return false;
}

function writeCell(sheet, row, colIndex, value) {
  if (colIndex < 0 || value === '' || value === null || typeof value === 'undefined') return;
  const cell = sheet.getRange(row, colIndex + 1);
  try {
    cell.setValue(value);
  } catch (err) {
    if (!/data validation/i.test(String(err))) throw err;
    const rule = typeof cell.getDataValidation === 'function' ? cell.getDataValidation() : null;
    if (typeof cell.setDataValidation === 'function') cell.setDataValidation(null);
    if (typeof SpreadsheetApp.flush === 'function') SpreadsheetApp.flush();
    cell.setValue(value);
    if (rule && typeof cell.setDataValidation === 'function') cell.setDataValidation(rule);
  }
}

// Writes the value and clears our highlight, or highlights the cell when the value is missing.
function writeFlagged(sheet, row, colIndex, value, missingColor) {
  if (colIndex < 0) return;
  const cell = sheet.getRange(row, colIndex + 1);
  if (value) {
    cell.setValue(value);
    if (typeof cell.getBackground === 'function' && isTrackerHighlight(cell.getBackground())) cell.setBackground(null);
    return;
  }
  cell.setBackground(missingColor);
}

function finishToast(title, counts, extra) {
  let text =
    'Added ' +
    counts.created +
    ', updated ' +
    counts.updated +
    ', skipped ' +
    counts.skipped +
    ', review ' +
    (counts.review || 0);
  if (counts.failed) text += ', failed ' + counts.failed;
  const reasons = counts.skippedReasons || {};
  const reasonText = Object.keys(reasons)
    .map((name) => reasons[name] + ' ' + name)
    .join(', ');
  if (reasonText) text += '. Skipped ' + reasonText;
  if (extra) text += extra;
  if (counts.missingLocations && counts.missingLocations.length) {
    const unique = counts.missingLocations.filter((name, index) => counts.missingLocations.indexOf(name) === index);
    text += '. Location missing (yellow): ' + unique.slice(0, 6).join(', ');
    if (unique.length > 6) text += ' +' + (unique.length - 6);
  }
  notify(text, title);
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

const COMMON_ROLE_WORDS = {
  intern: true, interns: true, internship: true, internships: true, software: true, engineer: true, engineering: true,
  developer: true, development: true, sde: true, swe: true, i: true, ii: true, new: true, grad: true, graduate: true,
  university: true, early: true, career: true, entry: true, level: true, the: true, and: true, of: true, co: true,
  op: true, us: true, usa: true, bs: true, ms: true,
};

// "Seasonal Associate Technician" and "Associate Test Technician" are the same job; "(Cloud Storage)" and "(Systems)" are not.
function rolesSimilar(a, b) {
  const words = (text) =>
    normalizeCompany(text)
      .split(' ')
      .filter((word) => word && !COMMON_ROLE_WORDS[word] && !/^\d+$/.test(word));
  const left = words(a);
  const right = words(b);
  if (!left.length || !right.length) return true;
  const shared = left.filter((word) => right.indexOf(word) >= 0).length;
  const union = left.length + right.length - shared;
  return shared / union >= 0.5;
}

function companyShouldReplace(current, next) {
  const now = String(current || '').trim();
  const nxt = String(next || '').trim();
  if (!nxt || !now) return false;
  if (normalizeCompany(now) === normalizeCompany(nxt)) return false;
  // "Databricks via Greenhouse" is the platform label, not a name you typed.
  return /\bvia\b/i.test(now) && normalizeCompany(now).indexOf(normalizeCompany(nxt) + ' ') === 0;
}

function companiesMatch(a, b) {
  const left = normalizeCompany(a);
  const right = normalizeCompany(b);
  if (!left || !right) return false;
  return left === right || left.indexOf(right + ' ') === 0 || right.indexOf(left + ' ') === 0;
}

function containsAny(blob, phrases) {
  return phrases.some((phrase) => blob.indexOf(phrase) >= 0);
}

function formatDate(date) {
  if (!date) return '';
  return Utilities.formatDate(date, Session.getScriptTimeZone(), 'MM/dd/yyyy');
}

function loadLogRows() {
  const sheet = ensureLogSheet();
  const last = Math.max(sheet.getLastRow(), 1);
  const width = Math.max(sheet.getLastColumn(), LOG_HEADERS.length);
  const values = sheet.getRange(1, 1, last, width).getDisplayValues();
  const headers = values[0].map((item) => String(item || '').trim().toLowerCase());
  const idx = {};
  LOG_HEADERS.forEach((name) => {
    idx[name] = headers.indexOf(name);
  });
  const records = [];
  const byId = {};
  for (let i = 1; i < values.length; i += 1) {
    const messageId = idx.message_id >= 0 ? String(values[i][idx.message_id] || '') : String(values[i][0] || '');
    if (!messageId) continue;
    const record = {
      row: i + 1,
      message_id: messageId,
      thread_id: idx.thread_id >= 0 ? String(values[i][idx.thread_id] || '') : '',
      subject: idx.subject >= 0 ? String(values[i][idx.subject] || '') : String(values[i][2] || ''),
      parser_version: idx.parser_version >= 0 ? String(values[i][idx.parser_version] || '0') : '0',
      parse_status: idx.parse_status >= 0 ? String(values[i][idx.parse_status] || '') : '',
      application_key: idx.application_key >= 0 ? String(values[i][idx.application_key] || '') : '',
      tab: idx.tab >= 0 ? String(values[i][idx.tab] || '') : '',
      last_error: idx.last_error >= 0 ? String(values[i][idx.last_error] || '') : '',
      fetch_attempts: idx.fetch_attempts >= 0 ? Number(values[i][idx.fetch_attempts] || 0) : 0,
    };
    records.push(record);
    byId[messageId] = record;
  }
  return { sheet, headers, idx, records, byId };
}

function upsertLog(log, fields) {
  const sheet = log.sheet;
  const existing = log.byId[fields.message_id];
  const rowValues = LOG_HEADERS.map((name) => {
    if (name === 'synced_at') return new Date();
    if (name === 'fetch_attempts') return Number(fields.fetch_attempts || 0);
    return fields[name] || '';
  });
  // Column F is parse_status (applied / review / ignored / failed). A copied tracker
  // tab still has the Result dropdown there, and Sheets rejects anything else.
  const row = existing ? existing.row : Math.max(sheet.getLastRow(), 1) + 1;
  writeLogRow(sheet, row, rowValues);
  log.byId[fields.message_id] = Object.assign({}, existing || {}, fields, { row: row });
  if (!existing) log.records.push(log.byId[fields.message_id]);
}

function writeLogRow(sheet, row, rowValues) {
  if (row > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), row - sheet.getMaxRows());
  const range = sheet.getRange(row, 1, 1, rowValues.length);
  dropValidation(range);
  // Flush before the write. Sheets otherwise checks the Result dropdown that is still on column F.
  if (typeof SpreadsheetApp.flush === 'function') SpreadsheetApp.flush();
  range.setValues([rowValues]);
}

function dropValidation(range) {
  if (typeof range.clearDataValidations === 'function') range.clearDataValidations();
  if (typeof range.setDataValidation === 'function') range.setDataValidation(null);
}

function clearLogValidations(sheet) {
  const rows = Math.max(sheet.getMaxRows(), 1);
  const cols = Math.max(sheet.getMaxColumns(), LOG_HEADERS.length);
  dropValidation(sheet.getRange(1, 1, rows, cols));
  if (typeof SpreadsheetApp.flush === 'function') SpreadsheetApp.flush();
}

function columnHasValidation(sheet, col) {
  const rows = Math.min(Math.max(sheet.getMaxRows(), 1), 5);
  const range = sheet.getRange(1, col, rows, 1);
  if (typeof range.getDataValidations !== 'function') return false;
  const rules = range.getDataValidations();
  for (let i = 0; i < rules.length; i += 1) {
    if (rules[i][0]) return true;
  }
  return false;
}

function replaceSheetWithoutValidation(book, sheet) {
  const values = sheet.getDataRange().getValues();
  const name = sheet.getName();
  book.deleteSheet(sheet);
  const fresh = book.insertSheet(name);
  if (values.length && values[0].length) {
    fresh.getRange(1, 1, values.length, values[0].length).setValues(values);
  }
  fresh.hideSheet();
  return fresh;
}

function ensureLogSheet() {
  const book = SpreadsheetApp.getActive();
  let sheet = book.getSheetByName(CONFIG.logTab);
  if (!sheet) {
    sheet = book.insertSheet(CONFIG.logTab);
    clearLogValidations(sheet);
    sheet.appendRow(LOG_HEADERS);
    sheet.hideSheet();
    return sheet;
  }
  // A log copied from the tracker keeps the Result dropdown on column F, which rejects applied/review.
  if (columnHasValidation(sheet, 6)) {
    sheet = replaceSheetWithoutValidation(book, sheet);
    const props = PropertiesService.getDocumentProperties();
    const count = Number(props.getProperty('logRebuilds') || '0') + 1;
    props.setProperty('logRebuilds', String(count));
    props.setProperty('logRebuiltThisRun', '1');
  }
  clearLogValidations(sheet);
  const lastCol = Math.max(sheet.getLastColumn(), 1);
  const current = sheet.getRange(1, 1, 1, lastCol).getDisplayValues()[0];
  if (current.length < LOG_HEADERS.length || String(current[0] || '').toLowerCase() !== 'message_id') {
    sheet.insertRowBefore(1);
    sheet.getRange(1, 1, 1, LOG_HEADERS.length).setValues([LOG_HEADERS]);
    return sheet;
  }
  LOG_HEADERS.forEach((name, index) => {
    if (String(current[index] || '').toLowerCase() !== name) {
      sheet.getRange(1, index + 1).setValue(name);
    }
  });
  return sheet;
}
