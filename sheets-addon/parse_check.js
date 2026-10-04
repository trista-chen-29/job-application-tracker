// Runs the real sheets-addon/Code.gs parser and auto-sync trigger setup with stubbed Google services.
// Usage: node sheets-addon/parse_check.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const code = fs.readFileSync(path.join(__dirname, 'Code.gs'), 'utf8');
const props = {};
const triggers = [];
const searches = [];
const sheets = [];

function makeSheet(name) {
  const data = [['Date Applied', 'Company', 'Role', 'Location', 'Season', 'Result', 'Notes']];
  return {
    getName: () => name,
    getLastRow: () => data.length,
    getLastColumn: () => data[0].length,
    getMaxRows: () => Math.max(data.length, 20),
    getMaxColumns: () => Math.max(data[0].length, 9),
    hideSheet() {},
    appendRow(values) {
      data.push(values.map(String));
    },
    insertRowBefore() {},
    insertColumnAfter() {},
    deleteColumn() {},
    getRange: () => ({
      getDisplayValues: () => data.map((row) => row.slice()),
      getValues: () => data.map((row) => row.slice()),
      setValue() {},
      setValues() {},
      setBackground() {},
      getDataValidation() {
        return null;
      },
      setDataValidation() {},
      clearDataValidations() {},
    }),
  };
}

sheets.push(makeSheet('internships'), makeSheet('newgrad'));
const book = {
  getSheets: () => sheets,
  getSheetByName: (name) => sheets.find((sheet) => sheet.getName() === name) || null,
  insertSheet: (name) => {
    const sheet = makeSheet(name);
    sheets.push(sheet);
    return sheet;
  },
  toast() {},
  getUi: () => ({
    createMenu: () => {
      const menu = { addItem() { return menu; }, addSeparator() { return menu; }, addToUi() {} };
      return menu;
    },
  }),
};

function triggerBuilder(handler) {
  const spec = { handler };
  const builder = {
    timeBased: () => builder,
    everyMinutes: (minutes) => {
      spec.minutes = minutes;
      return builder;
    },
    forSpreadsheet: () => builder,
    onOpen: () => {
      spec.event = 'onOpen';
      return builder;
    },
    create: () => {
      const trigger = { getHandlerFunction: () => handler, spec };
      triggers.push(trigger);
      return trigger;
    },
  };
  return builder;
}

const ctx = {
  console,
  SpreadsheetApp: { getActive: () => book, getUi: book.getUi, CopyPasteType: {}, flush() {} },
  PropertiesService: {
    getDocumentProperties: () => ({
      getProperty: (key) => (key in props ? props[key] : null),
      setProperty: (key, value) => {
        props[key] = String(value);
      },
      deleteProperty: (key) => {
        delete props[key];
      },
    }),
  },
  Session: { getScriptTimeZone: () => 'America/Los_Angeles' },
  Utilities: {
    formatDate: (date) => {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Los_Angeles',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).formatToParts(date);
      const get = (type) => parts.find((part) => part.type === type).value;
      return get('month') + '/' + get('day') + '/' + get('year');
    },
  },
  GmailApp: {
    search: (query) => {
      searches.push(query);
      return [];
    },
    getMessagesForThreads: () => [],
  },
  ScriptApp: {
    getProjectTriggers: () => triggers.slice(),
    deleteTrigger: (trigger) => {
      const index = triggers.indexOf(trigger);
      if (index >= 0) triggers.splice(index, 1);
    },
    newTrigger: (handler) => triggerBuilder(handler),
  },
  LockService: {
    getDocumentLock: () => ({
      tryLock: () => true,
      releaseLock() {},
    }),
  },
};
vm.createContext(ctx);
vm.runInContext(code, ctx);

function message(from, subject, plain, html) {
  return {
    getFrom: () => from,
    getSubject: () => subject,
    getPlainBody: () => plain,
    getBody: () => html || '',
    getDate: () => new Date('2026-09-24T18:00:00Z'),
    getId: () => 'msg-databricks',
    getThread: () => ({ getId: () => 'thread-databricks' }),
  };
}

const body = [
  'Thanks for applying to Databricks! Your application for the Software Engineering Intern (2027 Start) - Winter role has been received.',
  '',
  'Please note that all official communication from Databricks will come from email addresses ending with @databricks.com.',
  '',
  '100 Market Street',
  'San Francisco, CA 94105',
  '** Please note: Do not reply to this email.',
].join('\n');

['Talent Team <notifications@greenhouse.io>', 'Databricks via Greenhouse <no-reply@us.greenhouse-mail.io>'].forEach((from) => {
  const hint = ctx.parseMessage(message(from, 'Thank you for applying to Databricks!', body, ''));
  assert.ok(hint, from);
  assert.strictEqual(hint.company, 'Databricks', from);
  assert.strictEqual(hint.role, 'Software Engineering Intern', from);
  assert.strictEqual(hint.location, '', from);
  assert.strictEqual(hint.season, 'Winter 2027', from);
  assert.strictEqual(hint.tab, 'internships', from);
  assert.strictEqual(hint.result, 'Applied', from);
  assert.strictEqual(hint.dateApplied, '09/24/2026', from);
  assert.ok(hint.notes.includes('official communication'), from);
  assert.ok(hint.notes.includes('https://mail.google.com/mail/u/0/#all/thread-databricks'), from);
  assert.ok(!hint.notes.includes('Do not reply'), from);
});

const plain = 'Thank you for applying to Databricks. '.repeat(4) + 'Your application for the Internship role has been received.';
const html = '<p>Your application for the Software Engineering Intern (2027 Start) - Winter role has been received.</p>';
const fromHtml = ctx.parseMessage(
  message('Greenhouse <no-reply@greenhouse.io>', 'Thank you for applying to Databricks!', plain, html)
);
assert.strictEqual(fromHtml.role, 'Software Engineering Intern');
assert.strictEqual(fromHtml.season, 'Winter 2027');
assert.strictEqual(fromHtml.company, 'Databricks');

const invented = ctx.parseMessage(
  message(
    'Acme <jobs@acme.com>',
    'Thank you for applying to Acme',
    'Thanks for applying to the Software Engineer role at Acme. Join us this summer. Copyright 2026. Your application has been received.',
    ''
  )
);
assert.strictEqual(invented.season, '');
assert.strictEqual(invented.location, '');
assert.strictEqual(invented.tab, 'newgrad');

assert.strictEqual(
  ctx.inferCompany('MIT SH Workday Support <noreply@magna.com>', 'Thanks', 'Your application has been received.').company,
  'Magna'
);
assert.strictEqual(ctx.inferCompany('Human Resources <jobs@kenect.com>', '', '').company, 'Kenect');
assert.strictEqual(
  ctx.inferCompany('the Platform Software Engineering Intern at Intuitive <jobs@intuitive.com>', '', '').company,
  'Intuitive'
);
assert.strictEqual(
  ctx.inferCompany('Notion we appreciate your interest in joining our team <jobs@notion.so>', '', '').company,
  'Notion'
);
assert.notStrictEqual(ctx.inferCompany('Us <jobs@kenect.com>', '', '').company, 'Us');
assert.strictEqual(ctx.inferCompany('join the team at Quora <jobs@quora.com>', '', '').company, 'Quora');
assert.strictEqual(
  ctx.inferCompany('the Associate Test Technician at Element Materials Technology <jobs@element.com>', '', '').company,
  'Element Materials Technology'
);
const weak = ctx.inferCompany(
  'Pat Lee <pat.lee@acme.com>',
  'Update',
  'Thank you for your interest in Acme Labs.'
);
assert.strictEqual(weak.company, 'Acme Labs');
assert.ok(weak.confidence < 0.7);
assert.strictEqual(ctx.applyHint({ confidence: 0.55, tab: 'internships' }), 'review');
const source = 'Source: https://mail.google.com/mail/u/0/#all/abc';
assert.strictEqual(ctx.mergeNotes('hello\n' + source, source), 'hello\n' + source);
const clipped = ctx.clipText(('alpha ').repeat(1200), 80);
assert.ok(clipped.length <= 80);
assert.ok(clipped.endsWith('alpha'));

assert.ok(code.includes('parserVersion: 12'));

let logReady = false;
const loggedRows = [];
const previousFlush = ctx.SpreadsheetApp.flush;
ctx.SpreadsheetApp.flush = () => {
  logReady = true;
};
ctx.upsertLog(
  {
    sheet: {
      getLastRow: () => 21,
      getMaxRows: () => 100,
      getRange: () => ({
        clearDataValidations() {},
        setDataValidation() {},
        setValues(values) {
          if (!logReady) {
            throw new Error(
              'The data you entered in cell F22 violates the data validation rules set on this cell. Please enter one of the following values: Applied, Rejected, OA, Interview, Offer.'
            );
          }
          loggedRows.push(values[0]);
        },
      }),
    },
    byId: {},
    records: [],
  },
  {
    message_id: 'm1',
    thread_id: 't1',
    subject: 'Thank you for applying',
    parser_version: 12,
    parse_status: 'applied',
    application_key: 'acme|intern|',
    tab: 'internships',
    last_error: '',
  }
);
assert.strictEqual(loggedRows.length, 1);
assert.strictEqual(loggedRows[0][5], 'applied');

let resultOpen = true;
let resultBlanked = false;
let resultRestored = null;
const resultRule = { id: 'result-dropdown' };
ctx.SpreadsheetApp.flush = () => {
  resultOpen = false;
};
const resultCell = {
  getDataValidation: () => resultRule,
  setDataValidation(next) {
    if (next === resultRule) resultRestored = next;
  },
  setValue(value) {
    if (resultOpen) {
      throw new Error(
        'The data you entered in cell F22 violates the data validation rules set on this cell. Please enter one of the following values: Applied, Rejected, OA, Interview, Offer.'
      );
    }
    resultBlanked = value === '';
  },
  setBackground() {},
};
ctx.clearTrackerRow({ getRange: () => resultCell }, 22, {
  date: 0,
  company: 1,
  role: 2,
  location: 3,
  season: 4,
  result: 5,
  notes: 6,
  source: -1,
});
assert.strictEqual(resultBlanked, true);
assert.strictEqual(resultRestored, resultRule);
ctx.SpreadsheetApp.flush = previousFlush;

ctx.onOpen();
assert.strictEqual(searches.length, 0, 'simple onOpen must not read Gmail');

ctx.installAutoSync();
ctx.installAutoSync();
const handlers = triggers.map((trigger) => trigger.getHandlerFunction());
assert.deepStrictEqual(handlers.filter((name) => name === 'syncGmail').length, 1);
assert.deepStrictEqual(handlers.filter((name) => name === 'syncOnOpen').length, 1);
assert.strictEqual(triggers.find((trigger) => trigger.getHandlerFunction() === 'syncGmail').spec.minutes, 10);
assert.strictEqual(triggers.find((trigger) => trigger.getHandlerFunction() === 'syncOnOpen').spec.event, 'onOpen');

ctx.syncOnOpen();
assert.ok(searches.length > 0, 'opening the sheet syncs Gmail');

ctx.stopAutoSync();
assert.strictEqual(triggers.filter((trigger) => trigger.getHandlerFunction() === 'syncGmail').length, 0);
assert.strictEqual(triggers.filter((trigger) => trigger.getHandlerFunction() === 'syncOnOpen').length, 0);
assert.strictEqual(props.autoSyncOff, '1');
const before = searches.length;
ctx.syncGmail();
assert.ok(searches.length > before, 'Sync Gmail now still runs after auto-sync is off');
assert.strictEqual(triggers.filter((trigger) => trigger.getHandlerFunction() === 'syncGmail').length, 0);
assert.strictEqual(triggers.filter((trigger) => trigger.getHandlerFunction() === 'syncOnOpen').length, 0);

console.log('Code.gs parser and auto-sync checks passed');
