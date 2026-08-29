import test from 'node:test';
import assert from 'node:assert/strict';

import { analyzeThread, BANDS, band } from '../extension/src/core/analyze.js';
import { normalize, templateMask } from '../extension/src/core/text.js';
import { clusterNearDuplicates } from '../extension/src/core/cluster.js';

const T0 = Date.parse('2026-03-01T12:00:00Z');

function comment(i, author, text, offsetSec = i * 30, extra = {}) {
  return {
    id: `c${i}`,
    author,
    text,
    timestampMs: T0 + offsetSec * 1000,
    ...extra,
  };
}

/** A thread of ordinary, unrelated human replies. */
function organicThread() {
  const texts = [
    'Honestly this is the best thing I have read all week, thank you for posting it',
    'I disagree with the second paragraph but the rest is solid enough',
    'Where did you get these numbers? The ONS release says something different',
    'my nan has been saying this for years and nobody listened to her',
    'Lol the replies to this are going to be unhinged, popcorn ready',
    'Genuinely useful thread. Saving for later when I have more time to read',
    'This ignores the fact that rents doubled in the same period though',
    'Great write up, one small correction: the vote was in November not October',
    'Not sure I follow the logic here, can you explain the third point again?',
    'Sharing this with my colleagues tomorrow morning, really well argued',
  ];
  return texts.map((t, i) => comment(i, `user_${i}`, t));
}

test('a copypasta ring is flagged as coordinated', () => {
  const line = 'The mainstream media will never tell you the truth about this policy';
  const ring = Array.from({ length: 12 }, (_, i) =>
    comment(100 + i, `acct${i}`, line, 600 + i * 3)
  );
  const report = analyzeThread({ comments: [...organicThread(), ...ring] });

  const ringResults = report.comments.filter((c) => c.author.startsWith('acct'));
  assert.equal(ringResults.length, 12);
  for (const r of ringResults) {
    assert.equal(r.band, BANDS.COORDINATED, `${r.author} should be coordinated`);
    assert.ok(r.findings.some((f) => f.code === 'DUPLICATE_TEXT'));
  }

  const organic = report.comments.filter((c) => c.author.startsWith('user_'));
  for (const r of organic) {
    assert.equal(r.band, BANDS.NONE, `${r.author} should not be flagged`);
  }

  assert.ok(report.summary.clusters >= 1);
  assert.equal(report.summary.coordinated, 12);
});

test('an entirely organic thread produces no flags at all', () => {
  const report = analyzeThread({ comments: organicThread() });
  assert.equal(report.summary.coordinated, 0);
  assert.equal(report.summary.suspicious, 0);
  assert.equal(report.summary.weak, 0);
  assert.equal(report.clusters.length, 0);
});

test('evasion via emoji, zero-width chars and swapped mentions still clusters', () => {
  const base = 'This whole story is a fabrication and everyone knows it by now';
  const variants = [
    base,
    `@alice ${base} 🔥🔥`,
    `${base.slice(0, 20)}​${base.slice(20)}`,
    `@bob ${base}!!!`,
    `${base} 😡`,
    `@carol ${base.toUpperCase()}`,
  ];
  const ring = variants.map((t, i) => comment(200 + i, `ring${i}`, t, 60 + i * 2));
  const report = analyzeThread({ comments: [...organicThread(), ...ring] });

  const flagged = report.comments.filter((c) => c.author.startsWith('ring'));
  for (const r of flagged) {
    assert.equal(r.band, BANDS.COORDINATED, `${r.author} evaded detection`);
  }
});

test('template families are caught after entity masking', () => {
  const ring = [
    comment(300, 'p1', 'Frankly Sadiq Khan has completely destroyed London in 8 years flat'),
    comment(301, 'p2', 'Frankly Angela Rayner has completely destroyed Britain in 4 years flat'),
    comment(302, 'p3', 'Frankly Keir Starmer has completely destroyed Scotland in 3 years flat'),
    comment(303, 'p4', 'Frankly Rishi Sunak has completely destroyed Wales in 6 years flat'),
  ];
  const report = analyzeThread({ comments: [...organicThread(), ...ring] });
  const flagged = report.comments.filter((c) => c.author.startsWith('p'));
  for (const r of flagged) {
    assert.ok(
      r.findings.some((f) => f.code === 'TEMPLATE_MATCH'),
      `${r.author} missing TEMPLATE_MATCH`
    );
    assert.notEqual(r.band, BANDS.NONE);
  }
});

test('GUARDRAIL: cosmetic account signals alone can never exceed "weak"', () => {
  // Every weak circumstantial signal stacked at once — default avatar,
  // auto-generated handle, all posting in the same instant — but each writing
  // genuinely their own words. This is what a group of ordinary new users
  // looks like, and it must stay unflagged.
  const distinctTexts = [
    'my mum worked there for thirty years and it was never like that',
    'anyone got a link to the actual report? cant find it anywhere',
    'i moved here in 2019 and honestly the buses have got worse',
    'reading this on my break, will come back to it properly later',
    'the bit about school funding is just wrong, ask any teacher',
    'why is nobody talking about the water companies in all this',
    'first time commenting on here but this needed saying',
    'shared it with my brother, he works in the sector and agrees',
  ];
  const suspiciousLooking = distinctTexts.map((text, i) =>
    comment(400 + i, `person${i}12345678`, text, 1000, { defaultAvatar: true })
  );
  const report = analyzeThread({ comments: [...organicThread(), ...suspiciousLooking] });

  for (const r of report.comments.filter((c) => c.author.startsWith('person'))) {
    assert.ok(!r.hasHardEvidence, `${r.author} should have no corroborating evidence`);
    assert.ok(
      r.band === BANDS.WEAK || r.band === BANDS.NONE,
      `${r.author} was banded ${r.band} on cosmetics alone — guardrail breached`
    );
  }
});

test('GUARDRAIL: the band function refuses promotion without hard evidence', () => {
  assert.equal(band(99, false), BANDS.WEAK);
  assert.equal(band(4, true), BANDS.COORDINATED);
  assert.equal(band(2, true), BANDS.SUSPICIOUS);
  assert.equal(band(0.1, false), BANDS.NONE);
});

test('assistant boilerplate is reported as leakage', () => {
  const leaky = [
    comment(500, 'l1', 'As an AI language model, I cannot take a political position on this.'),
    comment(501, 'l2', 'Sure! Here is a rewritten reply: the policy is broadly popular.'),
    comment(502, 'l3', 'I think [insert counterargument here] and that settles it really'),
  ];
  const report = analyzeThread({ comments: [...organicThread(), ...leaky] });
  for (const r of report.comments.filter((c) => c.author.startsWith('l'))) {
    assert.ok(r.findings.some((f) => f.code === 'LLM_LEAK'), `${r.author} missed leak`);
  }
});

test('no stylometric guessing: fluent formal prose is never flagged', () => {
  // The kind of text a naive "AI detector" flags: fluent, formal, well
  // structured. Often written by non-native speakers. Must stay clean.
  const formal = [
    comment(600, 'f1', 'In conclusion, it is important to note that the proposal delivers substantial benefits to the community as a whole.'),
    comment(601, 'f2', 'Furthermore, one must consider the broader implications of such a policy upon future generations.'),
    comment(602, 'f3', 'This is a testament to the tireless efforts of everyone who has worked on this initiative.'),
  ];
  const report = analyzeThread({ comments: [...organicThread(), ...formal] });
  for (const r of report.comments.filter((c) => c.author.startsWith('f'))) {
    assert.equal(r.band, BANDS.NONE, `${r.author} was flagged on style alone`);
  }
});

test('one account flooding a thread is reported', () => {
  const line = 'Buy my course, link in bio, changed my life completely';
  const flood = Array.from({ length: 5 }, (_, i) =>
    comment(700 + i, 'spammer', line, 100 + i * 10)
  );
  const report = analyzeThread({ comments: [...organicThread(), ...flood] });
  const results = report.comments.filter((c) => c.author === 'spammer');
  for (const r of results) {
    assert.ok(r.findings.some((f) => f.code === 'AUTHOR_FLOOD'), 'missing AUTHOR_FLOOD');
  }
});

test('cross-thread memory promotes a repeat poster', () => {
  const comments = [
    ...organicThread(),
    comment(800, 'repeat_acct', 'The same talking point I post everywhere I possibly can'),
  ];
  const memory = new Map([['c800', { authorRepeatThreads: 4, textThreads: 4, textAuthors: 6 }]]);
  const report = analyzeThread({ comments, memory });
  const r = report.comments.find((c) => c.author === 'repeat_acct');
  assert.ok(r.findings.some((f) => f.code === 'MEMORY_AUTHOR_REPEAT'));
  assert.equal(r.hasHardEvidence, true);
});

test('short replies are not clustered', () => {
  // "this", "lol", "same" are identical across thousands of real people.
  const shorts = ['lol', 'this', 'same', 'exactly', 'lol', 'this'].map((t, i) =>
    comment(900 + i, `short${i}`, t, i * 5)
  );
  const report = analyzeThread({ comments: shorts });
  assert.equal(report.clusters.length, 0);
  for (const r of report.comments) assert.equal(r.band, BANDS.NONE);
});

test('clustering scales to a large thread', () => {
  const big = [];
  for (let i = 0; i < 2000; i++) {
    big.push(comment(i, `u${i}`, `Reply number ${i} with genuinely distinct wording ${i * 7} here`, i));
  }
  const started = Date.now();
  const report = analyzeThread({ comments: big });
  const elapsed = Date.now() - started;
  assert.ok(elapsed < 8000, `analysis took ${elapsed}ms`);
  assert.equal(report.summary.coordinated, 0);
});

test('text primitives behave', () => {
  assert.equal(normalize('  HELLO   world!!  '), 'hello world');
  assert.equal(
    templateMask('I think Boris Johnson ruined Britain in 2019'),
    templateMask('I think Liz Truss ruined England in 2022')
  );
  assert.equal(clusterNearDuplicates([{ id: 'a', norm: 'only one item here' }]).length, 0);
});
