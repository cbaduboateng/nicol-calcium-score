/**
 * Cross-thread memory.
 *
 * Everything here stays in the browser's own IndexedDB. Nothing is uploaded,
 * and no comment text is stored — only a 64-bit fingerprint of the normalised
 * wording, the account handle, and which thread it was seen in. That is enough
 * to answer "have I seen this exact line somewhere else?" and not enough to
 * reconstruct anyone's browsing.
 *
 * Near-duplicate lookup across thousands of stored records cannot use Jaccard,
 * so fingerprints are indexed by four 16-bit SimHash bands (a small LSH). Any
 * shared band makes a candidate; candidates are then confirmed by Hamming
 * distance.
 */

import { normalize, shingles, simhash, hamming, toHex, fromHex, wordCount } from '../core/text.js';

const DB_NAME = 'chorus';
const DB_VERSION = 1;
const STORE = 'sightings';

export const MEMORY_DEFAULTS = {
  maxRecords: 50_000,
  maxAgeDays: 30,
  hammingThreshold: 3,
  minWords: 5,
};

let dbPromise = null;

function open() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: 'key', autoIncrement: true });
        store.createIndex('bands', 'bands', { multiEntry: true });
        store.createIndex('ts', 'ts');
        store.createIndex('thread', 'thread');
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

function tx(db, mode) {
  return db.transaction(STORE, mode).objectStore(STORE);
}

function promisify(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** Split a 64-bit fingerprint into four 16-bit bands, prefixed by position. */
function bandKeys(hash) {
  const keys = [];
  for (let b = 0; b < 4; b++) {
    const chunk = (hash >> BigInt(b * 16)) & 0xffffn;
    keys.push(`${b}:${chunk.toString(16).padStart(4, '0')}`);
  }
  return keys;
}

/** Fingerprint a comment, or null if it is too short to be distinctive. */
export function fingerprint(text, opts = MEMORY_DEFAULTS) {
  const norm = normalize(text);
  if (wordCount(norm) < opts.minWords) return null;
  const hash = simhash(shingles(norm));
  return { hash, hex: toHex(hash), bands: bandKeys(hash) };
}

/**
 * Look up prior sightings for a batch of comments.
 *
 * @returns {Map} commentId -> {authorRepeatThreads, textThreads, textAuthors}
 */
export async function lookupMemory(comments, threadKey, opts = MEMORY_DEFAULTS) {
  const results = new Map();
  let db;
  try {
    db = await open();
  } catch {
    return results; // Private mode or blocked storage: degrade to thread-local only.
  }

  const store = tx(db, 'readonly');
  const index = store.index('bands');

  for (const comment of comments) {
    const fp = fingerprint(comment.text, opts);
    if (!fp) continue;

    const candidates = new Map();
    for (const band of fp.bands) {
      let rows;
      try {
        rows = await promisify(index.getAll(band));
      } catch {
        continue;
      }
      for (const row of rows) candidates.set(row.key, row);
    }

    const threads = new Set();
    const authors = new Set();
    const authorThreads = new Set();
    for (const row of candidates.values()) {
      if (row.thread === threadKey) continue; // Current thread is scored separately.
      if (hamming(fp.hash, fromHex(row.hash)) > opts.hammingThreshold) continue;
      threads.add(row.thread);
      authors.add(row.author);
      if (row.author === comment.author) authorThreads.add(row.thread);
    }

    if (threads.size > 0) {
      results.set(comment.id, {
        authorRepeatThreads: authorThreads.size,
        textThreads: threads.size,
        textAuthors: authors.size,
      });
    }
  }
  return results;
}

/** Record this thread's comments so future threads can be compared against them. */
export async function recordSightings(comments, threadKey, opts = MEMORY_DEFAULTS) {
  let db;
  try {
    db = await open();
  } catch {
    return 0;
  }

  const store = tx(db, 'readwrite');
  const existing = new Set(
    (await promisify(store.index('thread').getAll(threadKey))).map((r) => `${r.author}|${r.hash}`)
  );

  let written = 0;
  const now = Date.now();
  for (const comment of comments) {
    const fp = fingerprint(comment.text, opts);
    if (!fp) continue;
    const dedupeKey = `${comment.author}|${fp.hex}`;
    if (existing.has(dedupeKey)) continue;
    existing.add(dedupeKey);
    store.put({
      hash: fp.hex,
      bands: fp.bands,
      thread: threadKey,
      author: comment.author,
      ts: now,
    });
    written++;
  }
  return written;
}

/** Drop records that are too old or beyond the cap. Cheap to call on a timer. */
export async function pruneMemory(opts = MEMORY_DEFAULTS) {
  let db;
  try {
    db = await open();
  } catch {
    return { removed: 0 };
  }
  const store = tx(db, 'readwrite');
  const cutoff = Date.now() - opts.maxAgeDays * 86_400_000;

  let removed = 0;
  await new Promise((resolve, reject) => {
    const request = store.index('ts').openCursor(IDBKeyRange.upperBound(cutoff));
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return resolve();
      cursor.delete();
      removed++;
      cursor.continue();
    };
    request.onerror = () => reject(request.error);
  });

  const total = await promisify(tx(db, 'readonly').count());
  if (total > opts.maxRecords) {
    const excess = total - opts.maxRecords;
    const evict = tx(db, 'readwrite');
    await new Promise((resolve, reject) => {
      const request = evict.index('ts').openCursor();
      let n = 0;
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor || n >= excess) return resolve();
        cursor.delete();
        n++;
        removed++;
        cursor.continue();
      };
      request.onerror = () => reject(request.error);
    });
  }
  return { removed };
}

export async function memoryStats() {
  try {
    const db = await open();
    const count = await promisify(tx(db, 'readonly').count());
    return { records: count };
  } catch {
    return { records: 0, unavailable: true };
  }
}

export async function clearMemory() {
  const db = await open();
  await promisify(tx(db, 'readwrite').clear());
}
