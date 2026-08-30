import test from 'node:test';
import assert from 'node:assert/strict';

import {
  parsePostUrl,
  buildAtUri,
  rkeyFromUri,
  flattenThread,
  loadThread,
  resolveActor,
} from '../extension/src/content/adapters/bluesky.js';
import { analyzeThread, BANDS } from '../extension/src/core/analyze.js';

const T0 = Date.parse('2026-08-29T12:00:00Z');

function post(rkey, handle, text, { offsetSec = 0, avatar = true, accountAgeDays = 400 } = {}) {
  return {
    post: {
      uri: `at://did:plc:${handle}/app.bsky.feed.post/${rkey}`,
      cid: `cid-${rkey}`,
      author: {
        did: `did:plc:${handle}`,
        handle: `${handle}.bsky.social`,
        displayName: handle,
        avatar: avatar ? `https://cdn.bsky.app/${handle}.jpg` : undefined,
        createdAt: new Date(T0 - accountAgeDays * 86_400_000).toISOString(),
      },
      record: {
        $type: 'app.bsky.feed.post',
        text,
        // Deliberately wrong, to prove indexedAt is preferred.
        createdAt: new Date(T0 - 999 * 86_400_000).toISOString(),
      },
      indexedAt: new Date(T0 + offsetSec * 1000).toISOString(),
      replyCount: 0,
    },
    replies: [],
  };
}

test('thread URLs are parsed, and non-thread URLs rejected', () => {
  assert.deepEqual(parsePostUrl('https://bsky.app/profile/alice.bsky.social/post/3kabc123'), {
    actor: 'alice.bsky.social',
    rkey: '3kabc123',
  });
  assert.deepEqual(parsePostUrl('https://bsky.app/profile/did:plc:xyz/post/3kabc123'), {
    actor: 'did:plc:xyz',
    rkey: '3kabc123',
  });
  assert.equal(parsePostUrl('https://bsky.app/profile/alice.bsky.social'), null);
  assert.equal(parsePostUrl('https://bsky.app/'), null);
  assert.equal(parsePostUrl('https://example.com/profile/a/post/b'), null);
});

test('AT-URI helpers round-trip', () => {
  const uri = buildAtUri('did:plc:abc', '3kxyz');
  assert.equal(uri, 'at://did:plc:abc/app.bsky.feed.post/3kxyz');
  assert.equal(rkeyFromUri(uri), '3kxyz');
  assert.equal(rkeyFromUri(null), null);
});

test('flattenThread walks nested replies and excludes the root post', () => {
  const root = post('root', 'op', 'What do people think of the new policy?');
  const a = post('a1', 'alice', 'I think it is broadly sensible to be honest');
  const b = post('b1', 'bob', 'Strong disagree, it ignores rural areas completely');
  const c = post('c1', 'carol', 'Replying to bob here with a nested thought of my own');
  b.replies = [c];
  root.replies = [a, b];

  const flat = flattenThread(root);
  assert.equal(flat.length, 3, 'should include nested replies, exclude root');
  assert.ok(!flat.some((x) => x.author.startsWith('op')), 'root post must be excluded');

  const alice = flat.find((x) => x.author === 'alice.bsky.social');
  assert.equal(alice.rkey, 'a1');
  assert.equal(alice.did, 'did:plc:alice');
  assert.equal(alice.defaultAvatar, false);
});

test('server-assigned indexedAt is preferred over self-reported createdAt', () => {
  // record.createdAt is set by the posting client and is trivially forged;
  // trusting it would let a ring hide a burst by backdating.
  const root = post('root', 'op', 'Root post text here for the thread');
  root.replies = [post('a1', 'alice', 'A reply with a forged creation date', { offsetSec: 60 })];

  const [reply] = flattenThread(root);
  assert.equal(reply.timestampMs, T0 + 60_000);
  assert.notEqual(reply.timestampMs, Date.parse(root.replies[0].post.record.createdAt));
});

test('blocked and not-found posts are skipped without throwing', () => {
  const root = post('root', 'op', 'Root post for a thread with gaps in it');
  root.replies = [
    { $type: 'app.bsky.feed.defs#notFoundPost', uri: 'at://x', notFound: true },
    { $type: 'app.bsky.feed.defs#blockedPost', uri: 'at://y', blocked: true, author: {} },
    post('ok', 'alice', 'A perfectly ordinary visible reply goes here'),
  ];
  const flat = flattenThread(root);
  assert.equal(flat.length, 1);
  assert.equal(flat[0].author, 'alice.bsky.social');
});

test('posts with no text are dropped', () => {
  const root = post('root', 'op', 'Root post text goes right here');
  const imageOnly = post('img', 'alice', '');
  root.replies = [imageOnly];
  assert.equal(flattenThread(root).length, 0);
});

test('loadThread resolves a handle then fetches the thread', async () => {
  const calls = [];
  const fakeFetch = async (url) => {
    calls.push(url);
    if (url.includes('resolveHandle')) {
      return { ok: true, json: async () => ({ did: 'did:plc:op' }) };
    }
    const root = post('root', 'op', 'The root post of this particular thread');
    root.replies = [
      post('a', 'alice', 'One genuine reply with its own distinct wording here'),
      post('b', 'bob', 'Another genuine reply that shares nothing with the first'),
    ];
    return { ok: true, json: async () => ({ thread: root }) };
  };

  const result = await loadThread('https://bsky.app/profile/op.bsky.social/post/root', {
    fetchImpl: fakeFetch,
  });

  assert.equal(result.threadKey, 'bluesky:did:plc:op/root');
  assert.equal(result.comments.length, 2);
  assert.ok(calls[0].includes('com.atproto.identity.resolveHandle'));
  assert.ok(calls[1].includes('app.bsky.feed.getPostThread'));
  assert.ok(calls[1].includes('parentHeight=0'), 'ancestors are not part of the reply set');
});

test('a DID in the URL skips handle resolution entirely', async () => {
  let resolveCalls = 0;
  const fakeFetch = async (url) => {
    if (url.includes('resolveHandle')) resolveCalls++;
    return { ok: true, json: async () => ({ thread: post('root', 'op', 'Root text here now') }) };
  };
  await loadThread('https://bsky.app/profile/did:plc:abc/post/root', { fetchImpl: fakeFetch });
  assert.equal(resolveCalls, 0);
});

test('loadThread returns null for a non-thread page', async () => {
  const result = await loadThread('https://bsky.app/profile/someone.bsky.social', {
    fetchImpl: async () => {
      throw new Error('should not fetch');
    },
  });
  assert.equal(result, null);
});

test('API errors surface rather than being silently swallowed', async () => {
  const fakeFetch = async () => ({ ok: false, status: 502, json: async () => ({}) });
  await assert.rejects(
    () => resolveActor('someone.bsky.social', fakeFetch),
    /resolveHandle failed: 502/
  );
});

test('end to end: a Bluesky ring is detected from API data', () => {
  const line = 'This policy is a disaster and the press refuses to cover it properly';
  const root = post('root', 'op', 'Sharing my thoughts on the policy announced today');
  root.replies = [
    post('o1', 'mary', 'I read the whole document and it is more nuanced than that'),
    post('o2', 'tom', 'Where are you getting these figures from, genuinely curious'),
    post('o3', 'sam', 'Saving this thread to read properly on the train tomorrow'),
    post('o4', 'nia', 'My council already tried this and it went reasonably well'),
    // The ring: brand new accounts, no avatars, posting in a tight window.
    ...['r1', 'r2', 'r3', 'r4', 'r5'].map((h, i) =>
      post(h, h, line, { offsetSec: 600 + i, avatar: false, accountAgeDays: 2 })
    ),
  ];

  const comments = flattenThread(root);
  const report = analyzeThread({ comments });

  const ring = report.comments.filter((c) => /^r\d/.test(c.author));
  assert.equal(ring.length, 5);
  for (const r of ring) {
    assert.equal(r.band, BANDS.COORDINATED, `${r.author} should be coordinated`);
    assert.ok(r.findings.some((f) => f.code === 'DUPLICATE_TEXT'));
    assert.ok(
      r.findings.some((f) => f.code === 'NEW_ACCOUNT'),
      'account age should be reported when the source provides it'
    );
  }

  for (const r of report.comments.filter((c) => !/^r\d/.test(c.author))) {
    assert.equal(r.band, BANDS.NONE, `${r.author} should not be flagged`);
  }
});

test('GUARDRAIL: new accounts with distinct wording are never promoted', () => {
  // A wave of genuine new users — new accounts, no avatars, all posting at
  // once — must not be flagged just for being new.
  const root = post('root', 'op', 'Welcome to everyone who just joined today');
  root.replies = [
    'first post here, still working out how this all works',
    'joined this week after leaving the other place for good',
    'hello everyone, looking forward to finding people to follow',
    'my sister told me to sign up so here I am I suppose',
    'testing this out, the interface is nicer than I expected',
    'new here too, does anyone know how to find good feeds',
  ].map((text, i) =>
    post(`n${i}`, `newbie${i}`, text, { offsetSec: 30, avatar: false, accountAgeDays: 1 })
  );

  const report = analyzeThread({ comments: flattenThread(root) });
  for (const r of report.comments) {
    assert.ok(!r.hasHardEvidence, `${r.author} should have no corroborating evidence`);
    assert.ok(
      r.band === BANDS.WEAK || r.band === BANDS.NONE,
      `${r.author} was banded ${r.band} on newness alone — guardrail breached`
    );
  }
});
