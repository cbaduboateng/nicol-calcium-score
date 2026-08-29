import test from 'node:test';
import assert from 'node:assert/strict';

import { parseHandle, findAdapter, cheapHash } from '../extension/src/content/adapters/base.js';
import { BUILTIN_SPECS, threadKeyFor } from '../extension/src/content/adapters/builtin.js';

test('handles are parsed out of noisy author elements', () => {
  assert.equal(parseHandle('Jane Doe\n@janedoe\n·\n2h'), 'janedoe');
  assert.equal(parseHandle('@simple'), 'simple');
  assert.equal(parseHandle('  plainuser  '), 'plainuser');
  assert.equal(parseHandle(''), null);
  assert.equal(parseHandle(null), null);
});

test('adapters match hosts and subdomains but not lookalikes', () => {
  assert.equal(findAdapter(BUILTIN_SPECS, 'x.com')?.id, 'x');
  assert.equal(findAdapter(BUILTIN_SPECS, 'mobile.twitter.com')?.id, 'x');
  assert.equal(findAdapter(BUILTIN_SPECS, 'www.youtube.com')?.id, 'youtube');
  assert.equal(findAdapter(BUILTIN_SPECS, 'old.reddit.com')?.id, 'reddit');
  // A domain that merely ends in the same letters must not match.
  assert.equal(findAdapter(BUILTIN_SPECS, 'notx.com'), null);
  assert.equal(findAdapter(BUILTIN_SPECS, 'example.org'), null);
});

test('thread keys ignore tracking parameters', () => {
  const x = BUILTIN_SPECS.find((s) => s.id === 'x');
  const a = threadKeyFor(x, 'https://x.com/someone/status/1234567890');
  const b = threadKeyFor(x, 'https://x.com/someone/status/1234567890?s=20&t=abcdef');
  assert.equal(a, b);
  assert.equal(a, 'x:1234567890');

  const yt = BUILTIN_SPECS.find((s) => s.id === 'youtube');
  assert.equal(
    threadKeyFor(yt, 'https://www.youtube.com/watch?v=abc123&t=45s'),
    threadKeyFor(yt, 'https://www.youtube.com/watch?v=abc123')
  );
});

test('different threads get different keys', () => {
  const x = BUILTIN_SPECS.find((s) => s.id === 'x');
  assert.notEqual(
    threadKeyFor(x, 'https://x.com/a/status/111'),
    threadKeyFor(x, 'https://x.com/a/status/222')
  );
});

test('comment ids are stable for identical content and distinct otherwise', () => {
  assert.equal(cheapHash('same text'), cheapHash('same text'));
  assert.notEqual(cheapHash('some text'), cheapHash('other text'));
});

test('every built-in spec has the fields the extractor requires', () => {
  for (const spec of BUILTIN_SPECS) {
    assert.ok(spec.id, 'missing id');
    assert.ok(Array.isArray(spec.hosts) && spec.hosts.length, `${spec.id}: missing hosts`);
    for (const key of ['item', 'text', 'author']) {
      assert.equal(typeof spec.selectors[key], 'string', `${spec.id}: missing selectors.${key}`);
    }
    assert.match(spec.confirmed, /^\d{4}-\d{2}$/, `${spec.id}: missing confirmed date`);
  }
});
