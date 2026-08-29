/**
 * End-to-end check: loads the real unpacked extension into Chromium and points
 * it at a page served under the https://x.com origin (so the manifest's content
 * script matches), then asserts the ring is marked and the organic replies are
 * not.
 *
 * Run: NODE_PATH=/opt/node22/lib/node_modules node tests/e2e/run.js
 */

import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import assert from 'node:assert/strict';

import { buildPage, RING_HANDLES } from './fixture.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const extensionPath = path.resolve(here, '../../extension');
const outDir = path.resolve(here, '../../.e2e-output');

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'chorus-profile-'));

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

  // Serve the fixture from the https://x.com origin so the content script's
  // match pattern applies exactly as it would in the wild.
  await context.route('https://x.com/**', (route) =>
    route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: buildPage() })
  );

  await page.goto('https://x.com/someone/status/1234567890', { waitUntil: 'domcontentloaded' });

  // The content script debounces at 450ms; give it room plus analysis time.
  await page.waitForSelector('.chorus-marked', { timeout: 15000 });
  await page.waitForTimeout(1200);

  const results = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('article[data-testid="tweet"]')].map((el) => ({
      handle: el.querySelector('[data-testid="User-Name"]')?.textContent.match(/@(\w+)/)?.[1],
      marked: el.classList.contains('chorus-marked'),
      band: ['coordinated', 'suspicious', 'weak'].find((b) =>
        el.classList.contains(`chorus-band-${b}`)
      ) ?? null,
      chip: el.querySelector('.chorus-chip')?.textContent?.trim() ?? null,
    }));
    return {
      rows,
      panel: document.querySelector('.chorus-panel')?.innerText ?? null,
    };
  });

  // Partition by the fixture's own handle list rather than inferring it from
  // the handle shape — several ring handles end in only two digits.
  const ringSet = new Set(RING_HANDLES);
  const ring = results.rows.filter((r) => ringSet.has(r.handle));
  const organic = results.rows.filter((r) => !ringSet.has(r.handle));

  console.log('\n--- marked replies ---');
  for (const row of results.rows) {
    console.log(
      `${row.marked ? '*' : ' '} @${row.handle.padEnd(20)} ${String(row.band ?? '-').padEnd(12)} ${row.chip ?? ''}`
    );
  }
  console.log('\n--- panel ---\n' + results.panel);

  assert.equal(ring.length, RING_HANDLES.length, 'every ring reply should be present');
  assert.ok(organic.length >= 8, 'organic replies should be present');
  for (const row of ring) {
    assert.equal(row.band, 'coordinated', `@${row.handle} should be coordinated, got ${row.band}`);
    assert.ok(row.chip, `@${row.handle} should carry an explanation chip`);
  }
  for (const row of organic) {
    assert.equal(row.marked, false, `@${row.handle} should not be marked`);
  }
  assert.ok(results.panel?.includes('Repeated-text groups'), 'panel should summarise the thread');

  // Open the evidence popover and confirm it explains itself.
  await page.click('.chorus-chip');
  await page.waitForSelector('.chorus-popover');
  const popover = await page.evaluate(
    () => document.querySelector('.chorus-popover').innerText
  );
  console.log('\n--- popover ---\n' + popover);
  assert.ok(/\d+ accounts/.test(popover), 'popover should quantify the accounts involved');
  assert.ok(/innocent explanations|campaigns/i.test(popover), 'popover should carry a caveat');

  await page.screenshot({ path: path.join(outDir, 'thread.png'), fullPage: true });
  await page.setViewportSize({ width: 700, height: 900 });
  await page.screenshot({ path: path.join(outDir, 'popover.png') });

  const realErrors = consoleErrors.filter((e) => !/favicon|net::ERR/i.test(e));
  assert.deepEqual(realErrors, [], `console errors: ${realErrors.join(' | ')}`);

  await context.close();
  fs.rmSync(profile, { recursive: true, force: true });
  console.log('\nE2E PASSED — screenshots in .e2e-output/');
}

main().catch((error) => {
  console.error('\nE2E FAILED:', error.message);
  process.exit(1);
});
