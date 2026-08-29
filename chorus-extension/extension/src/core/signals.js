/**
 * Individual detection signals.
 *
 * Each function is pure and returns plain data. Nothing here decides whether
 * an account "is a bot" — they only report observable facts about a thread.
 * Aggregation and banding happen in analyze.js.
 */

/**
 * Reply bursts.
 *
 * Coordinated pushes arrive in tight clumps, typically within the first minutes
 * of a post. The difficulty is that a genuinely viral post also produces fast
 * replies, so an absolute rate threshold is useless. We compare each window
 * against the thread's own average arrival rate instead.
 *
 * Caveat, and the reason this signal is weighted low: we only ever see the
 * replies the platform chose to load, which is a biased sample of the real
 * arrival process.
 */
export function detectBursts(comments, opts = {}) {
  const { windowMs = 60_000, minAuthors = 6, rateFactor = 4 } = opts;

  const timed = comments
    .filter((c) => Number.isFinite(c.timestampMs))
    .sort((a, b) => a.timestampMs - b.timestampMs);
  if (timed.length < minAuthors) return { flagged: new Set(), windows: [] };

  const span = timed[timed.length - 1].timestampMs - timed[0].timestampMs;
  if (span <= 0) {
    // Every loaded reply carries the same timestamp: either a one-second
    // flood or, more likely, a platform that only exposes coarse times.
    return { flagged: new Set(), windows: [] };
  }
  const expectedPerWindow = (timed.length * windowMs) / span;

  const flagged = new Set();
  const windows = [];
  let start = 0;
  for (let end = 0; end < timed.length; end++) {
    while (timed[end].timestampMs - timed[start].timestampMs > windowMs) start++;
    const slice = timed.slice(start, end + 1);
    const authors = new Set(slice.map((c) => c.author));
    if (authors.size >= minAuthors && slice.length >= expectedPerWindow * rateFactor) {
      windows.push({
        from: timed[start].timestampMs,
        to: timed[end].timestampMs,
        count: slice.length,
        authors: authors.size,
        expected: Number(expectedPerWindow.toFixed(2)),
      });
      for (const c of slice) flagged.add(c.id);
    }
  }
  return { flagged, windows: mergeWindows(windows) };
}

function mergeWindows(windows) {
  const out = [];
  for (const w of windows) {
    const last = out[out.length - 1];
    if (last && w.from <= last.to) {
      last.to = Math.max(last.to, w.to);
      last.count = Math.max(last.count, w.count);
      last.authors = Math.max(last.authors, w.authors);
    } else {
      out.push({ ...w });
    }
  }
  return out;
}

/**
 * Auto-generated handle shapes.
 *
 * X hands out "name" + digits when a user signs up without choosing a handle.
 * Plenty of real people never change it, which is why this is worth a fraction
 * of a point and nothing more. On its own it must never flag anybody.
 */
const AUTO_HANDLE_PATTERNS = [
  { re: /^[A-Za-z][A-Za-z_]{2,}\d{8,}$/, label: 'name followed by 8+ digits' },
  { re: /^[A-Za-z]{4,}\d{6,}$/, label: 'name followed by 6+ digits' },
  { re: /^[a-z]{10,}$/, label: 'long unbroken lowercase string' },
];

export function inspectHandle(handle) {
  if (!handle) return null;
  const bare = handle.replace(/^@/, '');
  for (const { re, label } of AUTO_HANDLE_PATTERNS) {
    if (re.test(bare)) return label;
  }
  return null;
}

/**
 * Language-model leakage.
 *
 * This is deliberately NOT stylometry. Detectors that guess "does this read
 * like AI" have false-positive rates that make them unusable on short text and
 * are documented to misfire on non-native English writers, so we do not ship
 * one. What we do match is unambiguous leakage: the assistant preamble or
 * refusal boilerplate that a human writing a reply would never type.
 *
 * High precision, low recall, and that is the correct trade here.
 */
const LEAK_PATTERNS = [
  { re: /\bas an ai language model\b/i, label: 'assistant self-reference' },
  { re: /\bas a large language model\b/i, label: 'assistant self-reference' },
  { re: /\bas an ai\b[^.?!]{0,30}\bi (?:cannot|can't|don't)\b/i, label: 'assistant refusal' },
  { re: /\bi (?:cannot|can't) fulfill that request\b/i, label: 'assistant refusal' },
  { re: /\bi (?:cannot|can't) provide information on\b/i, label: 'assistant refusal' },
  { re: /\bas of my last knowledge update\b/i, label: 'knowledge-cutoff boilerplate' },
  { re: /\bmy (?:knowledge|training) cut ?-?off\b/i, label: 'knowledge-cutoff boilerplate' },
  { re: /\bi don'?t have personal (?:opinions|beliefs|feelings)\b/i, label: 'assistant disclaimer' },
  { re: /\[insert [^\]]{2,40}\]/i, label: 'unfilled template placeholder' },
  { re: /\{\{\s*[a-z_]{2,30}\s*\}\}/i, label: 'unfilled template placeholder' },
  { re: /\bsure[,!]? here(?:'s| is) (?:a |an |your )?(?:rewritten|revised|reply|response|comment|tweet)\b/i, label: 'assistant preamble' },
  { re: /\bhere (?:are|is) \d+ (?:alternative|different|possible) (?:replies|responses|versions|options)\b/i, label: 'assistant preamble' },
];

export function detectLlmLeak(text) {
  if (!text) return null;
  for (const { re, label } of LEAK_PATTERNS) {
    const match = text.match(re);
    if (match) return { label, excerpt: match[0].slice(0, 80) };
  }
  return null;
}

/**
 * The same destination pushed by many distinct accounts. Ordinary threads
 * share links too, so the bar is distinct authors rather than raw count.
 */
export function detectLinkRepetition(comments, opts = {}) {
  const { minAuthors = 4 } = opts;
  const byDomain = new Map();

  for (const c of comments) {
    for (const domain of extractDomains(c.text)) {
      if (!byDomain.has(domain)) byDomain.set(domain, { ids: [], authors: new Set() });
      const entry = byDomain.get(domain);
      entry.ids.push(c.id);
      entry.authors.add(c.author);
    }
  }

  const flagged = new Map();
  const domains = [];
  for (const [domain, entry] of byDomain) {
    if (entry.authors.size >= minAuthors) {
      domains.push({ domain, authors: entry.authors.size, count: entry.ids.length });
      for (const id of entry.ids) flagged.set(id, domain);
    }
  }
  return { flagged, domains };
}

function extractDomains(text) {
  const out = new Set();
  if (!text) return out;
  const matches = text.match(/https?:\/\/[^\s<>"']+/gi) || [];
  for (const raw of matches) {
    try {
      out.add(new URL(raw).hostname.replace(/^www\./, '').toLowerCase());
    } catch {
      /* malformed URL in user text; ignore */
    }
  }
  return out;
}

/** One account posting the same thing repeatedly in a single thread. */
export function detectAuthorFlood(comments, clusters, opts = {}) {
  const { minRepeats = 3 } = opts;
  const byId = new Map(comments.map((c) => [c.id, c]));
  const flagged = new Map();

  for (const cluster of clusters) {
    const counts = new Map();
    for (const id of cluster.members) {
      const author = byId.get(id)?.author;
      if (!author) continue;
      counts.set(author, (counts.get(author) || 0) + 1);
    }
    for (const [author, count] of counts) {
      if (count >= minRepeats) {
        for (const id of cluster.members) {
          if (byId.get(id)?.author === author) flagged.set(id, count);
        }
      }
    }
  }
  return flagged;
}
