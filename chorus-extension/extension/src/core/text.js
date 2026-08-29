/**
 * Text normalisation and similarity primitives.
 *
 * Everything here is pure and browser-free so it can be unit tested in Node.
 * The goal is to make two comments that a human would call "the same message"
 * compare equal, while keeping genuinely different messages apart.
 */

// Written as escapes deliberately: these characters are invisible in an
// editor, and they are precisely what a ring inserts to defeat naive
// string comparison.
const ZERO_WIDTH = /[\u200B-\u200F\u202A-\u202E\u2060-\u2064\uFEFF]/g;
const VARIATION = /[\uFE00-\uFE0F]/g;
const URL_RE = /\bhttps?:\/\/\S+|\bwww\.\S+/gi;
const HANDLE_RE = /(^|\s)@[a-z0-9_]{1,30}/gi;
const HASHTAG_RE = /(^|\s)#[\p{L}0-9_]+/giu;
const EMOJI_RE = /\p{Extended_Pictographic}/gu;
const PUNCT_RE = /[^\p{L}\p{N}\s«»]/gu;

/**
 * Canonical form used for duplicate detection.
 *
 * Deliberately aggressive: copypasta rings routinely swap emoji, punctuation
 * and the handle they are replying to while leaving the payload identical.
 * Those edits should not defeat matching.
 */
export function normalize(text) {
  if (typeof text !== 'string') return '';
  return text
    .normalize('NFKC')
    .replace(ZERO_WIDTH, '')
    .replace(VARIATION, '')
    .replace(URL_RE, ' «u» ')
    .replace(HANDLE_RE, ' «m» ')
    .replace(EMOJI_RE, ' ')
    .toLowerCase()
    .replace(PUNCT_RE, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Harsher masking that also removes the slots a template farm varies:
 * numbers, hashtags, and capitalised entity runs (names, countries, parties).
 *
 * "Sadiq Khan has destroyed London" and "Angela Rayner has destroyed Britain"
 * collapse to the same skeleton. Runs on raw text because capitalisation is
 * the entity signal and normalize() would have discarded it.
 */
export function templateMask(text) {
  if (typeof text !== 'string') return '';
  const entityMasked = text
    .normalize('NFKC')
    .replace(ZERO_WIDTH, '')
    .replace(URL_RE, ' «u» ')
    .replace(HASHTAG_RE, ' «h» ')
    .replace(HANDLE_RE, ' «m» ')
    // Capitalised run of 1-3 words, not at the very start of the string.
    .replace(/(?<=[a-z,;:]\s)(\p{Lu}[\p{L}'’-]+(?:\s+\p{Lu}[\p{L}'’-]+){0,2})/gu, ' «e» ')
    .replace(/\b\d[\d,.]*\b/g, ' «n» ');
  return normalize(entityMasked);
}

/** Word count of the normalised form — our proxy for "is there enough signal here". */
export function wordCount(normalised) {
  if (!normalised) return 0;
  return normalised.split(' ').filter(Boolean).length;
}

/**
 * Character k-grams. Character shingles beat word shingles on social text
 * because they survive typos, plurals and the deliberate letter-swapping
 * ("t0day", "v.a.c.c.i.n.e") used to dodge naive matchers.
 */
export function shingles(normalised, k = 5) {
  const set = new Set();
  if (!normalised) return set;
  if (normalised.length <= k) {
    set.add(normalised);
    return set;
  }
  for (let i = 0; i + k <= normalised.length; i++) {
    set.add(normalised.slice(i, i + k));
  }
  return set;
}

export function jaccard(a, b) {
  if (a.size === 0 && b.size === 0) return 1;
  if (a.size === 0 || b.size === 0) return 0;
  const [small, large] = a.size <= b.size ? [a, b] : [b, a];
  let intersection = 0;
  for (const item of small) if (large.has(item)) intersection++;
  return intersection / (a.size + b.size - intersection);
}

/** FNV-1a, 64-bit. Fast, dependency-free, good enough for shingle hashing. */
const FNV_PRIME = 1099511628211n;
const FNV_OFFSET = 14695981039346656037n;
const MASK64 = (1n << 64n) - 1n;

export function fnv1a64(str) {
  let hash = FNV_OFFSET;
  for (let i = 0; i < str.length; i++) {
    hash ^= BigInt(str.charCodeAt(i));
    hash = (hash * FNV_PRIME) & MASK64;
  }
  return hash;
}

/**
 * 64-bit SimHash over the shingle set.
 *
 * Used only as a cheap fingerprint for the cross-thread memory: comparing a
 * new comment against thousands of stored ones by Jaccard would be far too
 * slow, but Hamming distance over SimHash is a couple of instructions.
 */
export function simhash(shingleSet) {
  const bits = new Int32Array(64);
  for (const shingle of shingleSet) {
    const hash = fnv1a64(shingle);
    for (let bit = 0; bit < 64; bit++) {
      if ((hash >> BigInt(bit)) & 1n) bits[bit]++;
      else bits[bit]--;
    }
  }
  let out = 0n;
  for (let bit = 0; bit < 64; bit++) {
    if (bits[bit] > 0) out |= 1n << BigInt(bit);
  }
  return out;
}

export function hamming(a, b) {
  let xor = a ^ b;
  let count = 0;
  while (xor) {
    xor &= xor - 1n;
    count++;
  }
  return count;
}

/** Hex string form, for IndexedDB keys. */
export function toHex(bigint) {
  return bigint.toString(16).padStart(16, '0');
}

export function fromHex(hex) {
  return BigInt('0x' + hex);
}
