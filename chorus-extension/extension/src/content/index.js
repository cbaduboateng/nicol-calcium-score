/**
 * Content-script orchestrator.
 *
 * Loop: watch the comment container, and whenever it settles, extract every
 * comment currently rendered, score the thread as a whole, and paint the
 * results. Scoring is thread-wide rather than per-comment because the evidence
 * this tool relies on only exists in relation to other comments.
 */

import { analyzeThread } from '../core/analyze.js';
import { extractComments, findAdapter, validateSpec } from './adapters/base.js';
import { BUILTIN_SPECS, threadKeyFor } from './adapters/builtin.js';
import {
  BLUESKY_SPEC,
  BLUESKY_API,
  loadThread,
  findRenderedPosts,
} from './adapters/bluesky.js';

/**
 * Public-API requests go through the service worker rather than being issued
 * from the page.
 *
 * A content script's fetch runs with the host page's origin, so it is subject
 * to that page's CSP connect-src and to CORS. Neither is under our control and
 * either can silently kill the adapter. The worker fetches under the
 * extension's own host permissions, where neither applies.
 *
 * Shaped like a fetch Response so the adapter stays testable with a plain fake.
 */
async function backgroundFetch(url, init = {}) {
  const response = await chrome.runtime.sendMessage({
    type: 'chorus:fetch',
    url,
    credentials: init.credentials ?? 'omit',
  });
  if (!response) throw new Error('no response from background worker');
  if (response.error) throw new Error(response.error);
  return {
    ok: response.ok,
    status: response.status,
    json: async () => JSON.parse(response.body),
  };
}
import { Overlay } from './ui/overlay.js';

/**
 * Memory lives in the service worker, not here.
 *
 * A content script's IndexedDB belongs to the *host page's* origin, so storing
 * sightings locally would give x.com one silo and youtube.com another, defeat
 * the entire point of cross-thread memory, and leave the data unreachable from
 * the options page. Routing through the worker keeps one store on the
 * extension's own origin.
 */
async function memoryLookup(comments, threadKey) {
  try {
    const response = await chrome.runtime.sendMessage({
      type: 'chorus:memory-lookup',
      comments: comments.map(({ id, author, text }) => ({ id, author, text })),
      threadKey,
    });
    return new Map(response?.hits ?? []);
  } catch {
    return new Map();
  }
}

function memoryRecord(comments, threadKey) {
  try {
    chrome.runtime
      .sendMessage({
        type: 'chorus:memory-record',
        comments: comments.map(({ id, author, text }) => ({ id, author, text })),
        threadKey,
      })
      .catch(() => {});
  } catch {
    /* worker asleep; the next thread will record instead */
  }
}

const DEBOUNCE_MS = 450;
const MIN_COMMENTS = 6;

const state = {
  spec: null,
  overlay: null,
  observer: null,
  timer: null,
  running: false,
  rerunQueued: false,
  threadKey: null,
  focusClusterId: null,
  dismissed: new Set(),
  settings: {
    enabled: true,
    showWeak: false,
    memoryEnabled: true,
    hidePanel: false,
    disabledHosts: [],
  },
  lastReport: null,
};

async function loadSettings() {
  try {
    const stored = await chrome.storage.sync.get('settings');
    if (stored?.settings) Object.assign(state.settings, stored.settings);
  } catch {
    /* keep defaults */
  }
}

/**
 * Prefer a refreshed selector pack when one has been fetched and validates;
 * otherwise fall back to the built-in. A pack that fails validation is
 * discarded loudly in the console rather than silently disabling detection.
 */
const ALL_SPECS = [...BUILTIN_SPECS, BLUESKY_SPEC];

async function resolveSpec(hostname) {
  let specs = ALL_SPECS;
  try {
    const stored = await chrome.storage.local.get('selectorPack');
    const pack = stored?.selectorPack;
    if (Array.isArray(pack?.specs)) {
      const valid = [];
      for (const spec of pack.specs) {
        const error = validateSpec(spec);
        if (error) console.warn('[chorus] ignoring selector pack entry:', spec?.id, error);
        else valid.push(spec);
      }
      if (valid.length) {
        const byId = new Map(ALL_SPECS.map((s) => [s.id, s]));
        for (const spec of valid) byId.set(spec.id, { ...byId.get(spec.id), ...spec });
        specs = [...byId.values()];
      }
    }
  } catch {
    /* fall back to built-ins */
  }
  return findAdapter(specs, hostname);
}


/**
 * Fetched threads are cached per URL. Analysis re-runs on every DOM mutation,
 * but the reply set only changes when someone actually posts, so refetching on
 * each scroll tick would hammer a public API for no benefit.
 */
const threadCache = { url: null, at: 0, data: null };
const THREAD_TTL_MS = 45_000;

async function loadThreadCached(url, { force = false } = {}) {
  const fresh = threadCache.url === url && Date.now() - threadCache.at < THREAD_TTL_MS;
  if (fresh && !force) return threadCache.data;

  const data = await loadThread(url);
  threadCache.url = url;
  threadCache.at = Date.now();
  threadCache.data = data;
  return data;
}

/**
 * Gather the thread to score, plus a map from comment id to the element that
 * should carry its mark.
 *
 * The two source kinds differ in an important way. A scraped adapter can only
 * ever see rendered comments, so analysed and paintable are the same set. An
 * API adapter sees the whole thread, so a cluster may include replies that are
 * not on screen — which is more accurate, and worth telling the reader.
 */
async function collect() {
  if (state.spec.kind === 'api') {
    const loaded = await loadThreadCached(location.href);
    if (!loaded) return null;

    state.threadKey = loaded.threadKey;
    const comments = loaded.comments.filter((c) => !state.dismissed.has(c.id));
    const rendered = findRenderedPosts(document, state.spec);

    const elementsById = new Map();
    for (const comment of comments) {
      const element = rendered.get(comment.rkey);
      if (element) elementsById.set(comment.id, element);
    }
    return { comments, elementsById, offScreen: comments.length - elementsById.size };
  }

  const scraped = extractComments(document, state.spec).filter(
    (c) => !state.dismissed.has(c.id)
  );
  return {
    comments: scraped.map(({ element, ...rest }) => rest),
    elementsById: new Map(scraped.map((c) => [c.id, c.element])),
    offScreen: 0,
  };
}

function schedule() {
  clearTimeout(state.timer);
  state.timer = setTimeout(run, DEBOUNCE_MS);
}

async function run() {
  if (!state.settings.enabled || !state.spec) return;
  if (state.running) {
    state.rerunQueued = true;
    return;
  }
  state.running = true;

  try {
    const collected = await collect();

    if (!collected || collected.comments.length < MIN_COMMENTS) {
      state.overlay.clear();
      state.lastReport = null;
      report(null);
      return;
    }

    const { comments: plain, elementsById, offScreen } = collected;

    const memory = state.settings.memoryEnabled
      ? await memoryLookup(plain, state.threadKey)
      : new Map();

    const analysis = analyzeThread({ comments: plain, memory });
    analysis.summary.offScreen = offScreen;

    // No clear() here: render() reconciles against what is already painted so
    // scrolling does not tear down and rebuild every mark.
    state.overlay.render(analysis, elementsById, {
      showWeak: state.settings.showWeak,
      hidePanel: state.settings.hidePanel,
      focusClusterId: state.focusClusterId,
      offScreen,
    });

    state.lastReport = analysis;
    report(analysis);

    if (state.settings.memoryEnabled) {
      // Recorded after scoring so this thread never counts as its own history.
      memoryRecord(plain, state.threadKey);
    }
  } catch (error) {
    console.error('[chorus] analysis failed', error);
  } finally {
    state.running = false;
    if (state.rerunQueued) {
      state.rerunQueued = false;
      schedule();
    }
  }
}

function report(analysis) {
  const summary = analysis?.summary ?? null;
  try {
    chrome.runtime.sendMessage({ type: 'chorus:summary', summary }).catch(() => {});
  } catch {
    /* service worker asleep; the popup re-requests on open */
  }
}

function observe() {
  state.observer?.disconnect();
  const root =
    (state.spec.selectors.root && document.querySelector(state.spec.selectors.root)) ||
    document.body;
  if (!root) return;
  state.observer = new MutationObserver((mutations) => {
    // Ignore mutations we caused ourselves, or the loop never settles.
    const external = mutations.some((m) => {
      if (m.target instanceof Element && m.target.closest('.chorus-popover, .chorus-panel')) {
        return false;
      }
      return [...m.addedNodes].every(
        (n) => !(n instanceof Element) || !n.classList.contains('chorus-chip')
      );
    });
    if (external) schedule();
  });
  state.observer.observe(root, { childList: true, subtree: true });
}

function watchNavigation() {
  let lastUrl = location.href;
  const check = () => {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    state.threadKey = threadKeyFor(state.spec, location.href);
    threadCache.url = null;
    state.focusClusterId = null;
    state.dismissed.clear();
    state.overlay.clear();
    observe();
    schedule();
  };
  // SPA routers do not fire a usable event on every view change, so poll the
  // URL cheaply alongside the History API hooks.
  setInterval(check, 800);
  window.addEventListener('popstate', check);
}

async function init() {
  await loadSettings();

  const host = location.hostname.toLowerCase();
  if (state.settings.disabledHosts?.some((h) => host.endsWith(h))) return;

  state.spec = await resolveSpec(host);
  if (!state.spec) return;

  state.threadKey = threadKeyFor(state.spec, location.href);
  state.overlay = new Overlay(document);

  state.overlay.onFocusCluster = (clusterId) => {
    state.focusClusterId = clusterId;
    if (state.lastReport) schedule();
  };
  state.overlay.onDismiss = (result) => {
    state.dismissed.add(result.id);
    schedule();
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'chorus:request-summary') {
      sendResponse({ summary: state.lastReport?.summary ?? null, platform: state.spec.label });
      return true;
    }
    if (message?.type === 'chorus:settings-changed') {
      loadSettings().then(() => {
        state.overlay.clear();
        schedule();
      });
    }
    if (message?.type === 'chorus:rescan') {
      threadCache.url = null;
      schedule();
    }
    return false;
  });

  observe();
  watchNavigation();
  schedule();
}

init();
