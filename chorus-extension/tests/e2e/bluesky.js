/**
 * End-to-end check for the Bluesky (API-backed) adapter.
 *
 * Loads the real extension into Chromium, serves a bsky.app-shaped page, and
 * intercepts the public API so the fixture controls the thread. The point it
 * proves is the one that scraping cannot do: the API returns ten replies while
 * the page renders only seven, so the cluster must be reported at its true
 * size and the panel must say the rest are off screen.
 *
 * Run: node tests/e2e/bluesky.js
 */

import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import assert from 'node:assert/strict';

const here = path.dirname(fileURLToPath(import.meta.url));
const extensionPath = path.resolve(here, '../../extension');
const outDir = path.resolve(here, '../../.e2e-output');

const T0 = Date.parse('2026-08-29T12:00:00Z');
const RING_LINE = 'This policy is a disaster and the press refuses to cover it properly';

const ORGANIC = [
  ['mary', 'I read the whole document and it is more nuanced than that'],
  ['tom', 'Where are you getting these figures from, genuinely curious'],
  ['sam', 'Saving this thread to read properly on the train tomorrow'],
  ['nia', 'My council already tried this and it went reasonably well'],
  ['ade', 'The third paragraph contradicts the summary at the top'],
];
const RING = ['ring1', 'ring2', 'ring3', 'ring4', 'ring5'];

/** Only these are rendered — two ring members are deliberately left off screen. */
const RENDERED = [...ORGANIC.map(([h]) => h), 'ring1', 'ring2', 'ring3'];

function apiPost(rkey, handle, text, { offsetSec = 0, avatar = true, ageDays = 400 } = {}) {
  return {
    post: {
      uri: `at://did:plc:${handle}/app.bsky.feed.post/${rkey}`,
      cid: `cid-${rkey}`,
      author: {
        did: `did:plc:${handle}`,
        handle: `${handle}.bsky.social`,
        displayName: handle,
        ...(avatar ? { avatar: `https://cdn.invalid/${handle}.jpg` } : {}),
        createdAt: new Date(T0 - ageDays * 86_400_000).toISOString(),
      },
      record: { $type: 'app.bsky.feed.post', text, createdAt: new Date(T0).toISOString() },
      indexedAt: new Date(T0 + offsetSec * 1000).toISOString(),
      replyCount: 0,
    },
    replies: [],
  };
}

function buildThreadPayload() {
  const root = apiPost('root', 'op', 'Sharing my thoughts on the policy announced today');
  root.replies = [
    ...ORGANIC.map(([handle, text], i) => apiPost(handle, handle, text, { offsetSec: i * 120 })),
    ...RING.map((handle, i) =>
      apiPost(handle, handle, RING_LINE, { offsetSec: 900 + i, avatar: false, ageDays: 2 })
    ),
  ];
  return { thread: root };
}

/**
 * Markup shaped like bsky.app: no useful testids, posts identified only by a
 * permalink, wrapped in several layers of layout divs. This exercises the
 * ancestor-climbing that findRenderedPosts has to do.
 */
function buildPage() {
  const byHandle = new Map([
    ...ORGANIC.map(([h, t]) => [h, t]),
    ...RING.map((h) => [h, RING_LINE]),
  ]);

  const cards = RENDERED.map((handle) => {
    const text = byHandle.get(handle);
    return `
      <div class="layout-outer"><div class="layout-inner">
        <div class="post-card">
          <div class="post-head">
            <a href="/profile/${handle}.bsky.social">${handle}</a>
            <a href="/profile/${handle}.bsky.social/post/${handle}"><time>2h</time></a>
          </div>
          <div class="post-body">${text}</div>
        </div>
      </div></div>`;
  });

  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Thread</title>
<style>
  body { font: 15px/1.45 system-ui, sans-serif; margin: 0; background: #fff; color: #0b0f14; }
  #root { max-width: 600px; margin: 0 auto; }
  .post-card { padding: 12px 16px; border-bottom: 1px solid #e3e8ee; }
  .post-head { font-size: 13px; color: #5c6a7a; margin-bottom: 4px; }
  .post-head a { color: #1083fe; text-decoration: none; margin-right: 8px; }
  h1 { padding: 16px; margin: 0; font-size: 17px; border-bottom: 1px solid #e3e8ee; }
</style></head>
<body><div id="root">
  <h1>Sharing my thoughts on the policy announced today</h1>
  ${cards.join('\n')}
</div></body></html>`;
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'chorus-bsky-'));

  const context = await chromium.launchPersistentContext(profile, {
    headless: true,
    channel: 'chromium',
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
      '--no-sandbox',
    ],
  });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });

  const apiCalls = [];
  await context.route('https://public.api.bsky.app/**', (route) => {
    const url = route.request().url();
    apiCalls.push(url);
    const body = url.includes('resolveHandle')
      ? { did: 'did:plc:op' }
      : buildThreadPayload();
    route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      headers: { 'access-control-allow-origin': '*' },
      body: JSON.stringify(body),
    });
  });

  await context.route('https://bsky.app/**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: buildPage() })
  );

  await page.goto('https://bsky.app/profile/op.bsky.social/post/root', {
    waitUntil: 'domcontentloaded',
  });

  await page.waitForSelector('.chorus-marked', { timeout: 20000 });
  await page.waitForTimeout(1500);

  const results = await page.evaluate(() => {
    // The mark is applied to the outermost wrapper that still contains exactly
    // one post, which is the card boundary as the adapter sees it — not
    // necessarily the element carrying the .post-card class.
    const cards = [...document.querySelectorAll('.post-card')].map((el) => {
      const marked = el.closest('.chorus-marked');
      return {
        handle: el.querySelector('.post-head a')?.textContent?.trim(),
        marked: Boolean(marked),
        band: marked
          ? ['coordinated', 'suspicious', 'weak'].find((b) =>
              marked.classList.contains(`chorus-band-${b}`)
            ) ?? null
          : null,
        chip: marked?.querySelector('.chorus-chip')?.textContent?.trim() ?? null,
      };
    });
    return { cards, panel: document.querySelector('.chorus-panel')?.innerText ?? null };
  });

  console.log('\n--- rendered posts ---');
  for (const c of results.cards) {
    console.log(
      `${c.marked ? '*' : ' '} ${String(c.handle).padEnd(8)} ${String(c.band ?? '-').padEnd(12)} ${c.chip ?? ''}`
    );
  }
  console.log('\n--- panel ---\n' + results.panel);
  console.log('\n--- API calls ---\n' + apiCalls.map((u) => u.split('?')[0]).join('\n'));

  // The API was actually used, and the handle was resolved before the fetch.
  assert.ok(
    apiCalls.some((u) => u.includes('resolveHandle')),
    'should resolve the handle'
  );
  assert.ok(
    apiCalls.some((u) => u.includes('getPostThread')),
    'should fetch the thread over the API'
  );

  const renderedRing = results.cards.filter((c) => c.handle?.startsWith('ring'));
  const organic = results.cards.filter((c) => !c.handle?.startsWith('ring'));

  assert.equal(renderedRing.length, 3, 'only three ring members should be rendered');
  for (const c of renderedRing) {
    assert.equal(c.band, 'coordinated', `${c.handle} should be coordinated`);
    // The headline claim: the count reflects the whole thread, not the page.
    assert.match(
      c.chip,
      /5 accounts/,
      `${c.handle} should report all 5 accounts, not just the 3 on screen — got "${c.chip}"`
    );
  }
  for (const c of organic) {
    assert.equal(c.marked, false, `${c.handle} should not be marked`);
  }

  assert.match(results.panel, /Accounts involved\s*5/, 'panel should count all 5 ring accounts');
  assert.match(results.panel, /not on screen/i, 'panel should disclose off-screen replies');

  // Re-analysis must not refetch: the thread is cached.
  const callsBefore = apiCalls.length;
  await page.evaluate(() => {
    const extra = document.createElement('div');
    extra.textContent = 'layout change';
    document.getElementById('root').appendChild(extra);
  });
  await page.waitForTimeout(1500);
  assert.equal(apiCalls.length, callsBefore, 'a DOM mutation must not trigger a refetch');

  await page.screenshot({ path: path.join(outDir, 'bluesky-thread.png'), fullPage: true });

  const realErrors = consoleErrors.filter((e) => !/favicon|net::ERR/i.test(e));
  assert.deepEqual(realErrors, [], `console errors: ${realErrors.join(' | ')}`);

  await context.close();
  fs.rmSync(profile, { recursive: true, force: true });
  console.log('\nBLUESKY E2E PASSED — screenshot in .e2e-output/');
}

main().catch((error) => {
  console.error('\nBLUESKY E2E FAILED:', error.message);
  process.exit(1);
});
