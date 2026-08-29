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
async function resolveSpec(hostname) {
  let specs = BUILTIN_SPECS;
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
        const byId = new Map(BUILTIN_SPECS.map((s) => [s.id, s]));
        for (const spec of valid) byId.set(spec.id, { ...byId.get(spec.id), ...spec });
        specs = [...byId.values()];
      }
    }
  } catch {
    /* fall back to built-ins */
  }
  return findAdapter(specs, hostname);
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
    const comments = extractComments(document, state.spec).filter(
      (c) => !state.dismissed.has(c.id)
    );

    if (comments.length < MIN_COMMENTS) {
      state.overlay.clear();
      state.lastReport = null;
      report(null);
      return;
    }

    const elementsById = new Map(comments.map((c) => [c.id, c.element]));
    const plain = comments.map(({ element, ...rest }) => rest);

    const memory = state.settings.memoryEnabled
      ? await memoryLookup(plain, state.threadKey)
      : new Map();

    const analysis = analyzeThread({ comments: plain, memory });

    state.overlay.clear();
    state.overlay.render(analysis, elementsById, {
      showWeak: state.settings.showWeak,
      hidePanel: state.settings.hidePanel,
      focusClusterId: state.focusClusterId,
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
    if (message?.type === 'chorus:rescan') schedule();
    return false;
  });

  observe();
  watchNavigation();
  schedule();
}

init();
