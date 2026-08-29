/**
 * Background service worker.
 *
 * Two jobs: keep the toolbar badge in step with the active tab, and refresh the
 * selector pack on a slow timer. Nothing about the user's browsing leaves the
 * machine — the pack fetch is a plain GET with no query string, no identifiers
 * and no request body, so the endpoint learns nothing beyond "someone asked
 * for the current pack".
 */

import {
  pruneMemory,
  lookupMemory,
  recordSightings,
  memoryStats,
  clearMemory,
} from '../storage/db.js';

const PACK_ALARM = 'chorus:refresh-pack';
const PRUNE_ALARM = 'chorus:prune';
const PACK_REFRESH_HOURS = 12;

/**
 * Where refreshed selector packs come from. Deploy worker/ and put its URL
 * here, or leave it null to run entirely on the built-in selectors.
 */
const PACK_URL = null;

const badgeColours = {
  coordinated: '#d1344b',
  suspicious: '#d98324',
  none: '#6b7280',
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(PACK_ALARM, { periodInMinutes: PACK_REFRESH_HOURS * 60 });
  chrome.alarms.create(PRUNE_ALARM, { periodInMinutes: 24 * 60 });
  refreshPack();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === PACK_ALARM) refreshPack();
  if (alarm.name === PRUNE_ALARM) pruneMemory().catch(() => {});
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case 'chorus:summary': {
      if (!sender.tab?.id) return false;
      const summary = message.summary;
      const flagged = summary ? summary.coordinated + summary.suspicious : 0;
      chrome.action.setBadgeText({
        tabId: sender.tab.id,
        text: flagged > 0 ? String(Math.min(flagged, 999)) : '',
      });
      chrome.action.setBadgeBackgroundColor({
        tabId: sender.tab.id,
        color: summary?.coordinated ? badgeColours.coordinated : badgeColours.suspicious,
      });
      return false;
    }

    // Memory operations are served here so that every site shares one store on
    // the extension's origin. Each returns true to keep the message channel
    // open for the async reply.
    case 'chorus:memory-lookup':
      lookupMemory(message.comments ?? [], message.threadKey)
        .then((hits) => sendResponse({ hits: [...hits.entries()] }))
        .catch(() => sendResponse({ hits: [] }));
      return true;

    case 'chorus:memory-record':
      recordSightings(message.comments ?? [], message.threadKey)
        .then((written) => sendResponse({ written }))
        .catch(() => sendResponse({ written: 0 }));
      return true;

    case 'chorus:memory-stats':
      memoryStats()
        .then((stats) => sendResponse(stats))
        .catch(() => sendResponse({ records: 0, unavailable: true }));
      return true;

    case 'chorus:memory-clear':
      clearMemory()
        .then(() => sendResponse({ ok: true }))
        .catch(() => sendResponse({ ok: false }));
      return true;

    default:
      return false;
  }
});

async function refreshPack() {
  if (!PACK_URL) return;
  try {
    const response = await fetch(PACK_URL, { cache: 'no-cache', credentials: 'omit' });
    if (!response.ok) return;
    const pack = await response.json();
    if (!pack || !Array.isArray(pack.specs)) return;
    // Content scripts validate every spec before use; storing an unusable pack
    // is harmless because they fall back to the built-ins.
    await chrome.storage.local.set({
      selectorPack: { ...pack, fetchedAt: Date.now() },
    });
  } catch {
    /* offline or endpoint down: built-in selectors continue to work */
  }
}
