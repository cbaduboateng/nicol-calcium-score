/**
 * Adapters are pure data: a set of CSS selectors plus small pure helpers.
 *
 * This matters more than it looks. Social platforms reshuffle their DOM
 * constantly, and an extension whose scrapers are hand-written code needs a
 * store review (days to weeks) every time X renames a testid. Because the
 * selectors here are data, a refreshed selector pack fetched at runtime can
 * repair a broken adapter in minutes without shipping anything.
 *
 * See worker/ for the endpoint that serves packs, and background/ for the
 * refresh and validation logic.
 */

/**
 * @typedef {object} AdapterSpec
 * @property {string} id
 * @property {string[]} hosts             Hostname suffixes this adapter claims.
 * @property {object} selectors
 * @property {string} selectors.item      One rendered comment.
 * @property {string} selectors.text      Comment body within an item.
 * @property {string} selectors.author    Element carrying the handle.
 * @property {string} [selectors.time]    Element carrying a machine timestamp.
 * @property {string} [selectors.avatar]  Avatar image.
 * @property {string} [selectors.root]    Subtree to observe; defaults to body.
 * @property {string} [authorAttr]        Attribute to read the handle from.
 * @property {string[]} [defaultAvatarHints] Substrings marking a default avatar.
 */

/** Extract a handle from arbitrary author-element text. */
export function parseHandle(raw) {
  if (!raw) return null;
  const match = raw.match(/@([A-Za-z0-9_.-]{2,40})/);
  if (match) return match[1];
  const trimmed = raw.trim().replace(/^@/, '');
  return trimmed ? trimmed.split(/\s+/)[0] : null;
}

function readTimestamp(item, spec) {
  if (!spec.selectors.time) return null;
  const el = item.querySelector(spec.selectors.time);
  if (!el) return null;
  const iso = el.getAttribute('datetime') || el.getAttribute('title');
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) ? parsed : null;
}

function readDefaultAvatar(item, spec) {
  if (!spec.selectors.avatar || !spec.defaultAvatarHints?.length) return false;
  const img = item.querySelector(spec.selectors.avatar);
  if (!img) return false;
  const src = img.getAttribute('src') || '';
  return spec.defaultAvatarHints.some((hint) => src.includes(hint));
}

/**
 * Walk the page and pull out every comment the adapter can see.
 *
 * Stable ids matter: the DOM is virtualised and nodes are recycled as the user
 * scrolls, so an id derived from position would make findings jump between
 * comments. Handle plus a hash of the text is stable across re-renders.
 */
export function extractComments(doc, spec) {
  const root = spec.selectors.root ? doc.querySelector(spec.selectors.root) : doc.body;
  if (!root) return [];

  const items = root.querySelectorAll(spec.selectors.item);
  const out = [];
  const seen = new Set();

  for (const item of items) {
    const textEl = item.querySelector(spec.selectors.text);
    const authorEl = item.querySelector(spec.selectors.author);
    if (!textEl || !authorEl) continue;

    const text = (textEl.innerText || textEl.textContent || '').trim();
    const rawAuthor = spec.authorAttr
      ? authorEl.getAttribute(spec.authorAttr)
      : authorEl.innerText || authorEl.textContent;
    const author = parseHandle(rawAuthor);
    if (!text || !author) continue;

    const id = `${author}:${cheapHash(text)}`;
    if (seen.has(id)) continue;
    seen.add(id);

    out.push({
      id,
      author,
      text,
      timestampMs: readTimestamp(item, spec),
      defaultAvatar: readDefaultAvatar(item, spec),
      element: item,
    });
  }
  return out;
}

/** Non-cryptographic, only used to make ids stable. */
export function cheapHash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(36);
}

/**
 * A selector pack is untrusted input fetched over the network, so it is
 * validated before it can replace a built-in adapter. Selectors must parse,
 * and the shape must be complete — a malformed pack is ignored rather than
 * silently disabling detection.
 */
export function validateSpec(spec) {
  if (!spec || typeof spec !== 'object') return 'not an object';
  if (typeof spec.id !== 'string' || !spec.id) return 'missing id';
  if (!Array.isArray(spec.hosts) || spec.hosts.length === 0) return 'missing hosts';
  if (!spec.selectors || typeof spec.selectors !== 'object') return 'missing selectors';

  for (const required of ['item', 'text', 'author']) {
    if (typeof spec.selectors[required] !== 'string' || !spec.selectors[required]) {
      return `missing selectors.${required}`;
    }
  }
  for (const [name, value] of Object.entries(spec.selectors)) {
    if (typeof value !== 'string') return `selectors.${name} is not a string`;
    try {
      document.createDocumentFragment().querySelector(value);
    } catch {
      return `selectors.${name} is not a valid CSS selector`;
    }
  }
  return null;
}

export function findAdapter(specs, hostname) {
  const host = hostname.toLowerCase();
  return (
    specs.find((spec) =>
      spec.hosts.some((h) => host === h || host.endsWith(`.${h}`))
    ) || null
  );
}
