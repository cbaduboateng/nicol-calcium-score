/**
 * Bluesky adapter — the first source that does not scrape.
 *
 * Every other adapter reads whatever the page happened to render, which is a
 * biased sample: the platform decides which replies exist for us. Bluesky
 * publishes the thread over an open, unauthenticated API, so here we fetch the
 * *complete* reply set and analyse that, then paint results onto whichever
 * posts are currently on screen.
 *
 * That difference is not cosmetic. It means a cluster can be reported
 * accurately ("14 accounts posted this") even when only three of those replies
 * have been rendered, and it makes burst detection statistically meaningful
 * rather than the weak signal it necessarily is when scraping.
 *
 * Endpoints used (all public, no auth, no user identifiers sent):
 *   com.atproto.identity.resolveHandle
 *   app.bsky.feed.getPostThread
 */

export const BLUESKY_API = 'https://public.api.bsky.app/xrpc';

export const BLUESKY_SPEC = {
  id: 'bluesky',
  label: 'Bluesky',
  kind: 'api',
  hosts: ['bsky.app'],
  confirmed: '2026-08',
  // Only used to locate rendered posts for painting; the data comes from the
  // API, so there is nothing here that can silently break detection.
  postLinkPattern: /\/profile\/([^/]+)\/post\/([a-zA-Z0-9]+)/,
  // Subtree to watch for changes. Detection does not depend on this — if the
  // selector misses, the observer falls back to document.body.
  selectors: { root: 'main' },
};

/** Parse a bsky.app thread URL into its handle/DID and record key. */
export function parsePostUrl(url) {
  try {
    const { hostname, pathname } = new URL(url);
    if (hostname !== 'bsky.app' && !hostname.endsWith('.bsky.app')) return null;
    const match = pathname.match(/^\/profile\/([^/]+)\/post\/([a-zA-Z0-9]+)\/?$/);
    if (!match) return null;
    return { actor: decodeURIComponent(match[1]), rkey: match[2] };
  } catch {
    return null;
  }
}

export function buildAtUri(did, rkey) {
  return `at://${did}/app.bsky.feed.post/${rkey}`;
}

/** The record key is the last path segment of an AT-URI. */
export function rkeyFromUri(uri) {
  if (typeof uri !== 'string') return null;
  const parts = uri.split('/');
  return parts.length ? parts[parts.length - 1] : null;
}

export async function resolveActor(actor, fetchImpl = fetch) {
  if (actor.startsWith('did:')) return actor;
  const url = `${BLUESKY_API}/com.atproto.identity.resolveHandle?handle=${encodeURIComponent(actor)}`;
  const response = await fetchImpl(url, { credentials: 'omit' });
  if (!response.ok) throw new Error(`resolveHandle failed: ${response.status}`);
  const body = await response.json();
  if (!body?.did) throw new Error('resolveHandle returned no DID');
  return body.did;
}

/**
 * depth is capped at 1000 by the lexicon; 30 is far beyond any real reply
 * chain and keeps the response small. parentHeight is 0 because ancestors of
 * the post being viewed are not part of the reply set we score.
 */
export async function fetchThread(atUri, { fetchImpl = fetch, depth = 30 } = {}) {
  const url =
    `${BLUESKY_API}/app.bsky.feed.getPostThread` +
    `?uri=${encodeURIComponent(atUri)}&depth=${depth}&parentHeight=0`;
  const response = await fetchImpl(url, { credentials: 'omit' });
  if (!response.ok) throw new Error(`getPostThread failed: ${response.status}`);
  return response.json();
}

function isViewablePost(node) {
  // notFoundPost and blockedPost carry no post payload; the union is
  // discriminated by $type but checking for the payload is more forgiving.
  return Boolean(node && typeof node === 'object' && node.post && node.post.author);
}

function toComment(postView) {
  const { post } = postView;
  const author = post.author ?? {};
  const record = post.record ?? {};

  const text = typeof record.text === 'string' ? record.text : '';
  if (!text) return null;

  // indexedAt is assigned by the AppView; record.createdAt is self-reported by
  // the posting client and is trivially forged, which matters because burst
  // detection is a timing signal. Prefer the server's clock, fall back only if
  // it is missing.
  const stamp = Date.parse(post.indexedAt ?? record.createdAt ?? '');
  const accountCreated = Date.parse(author.createdAt ?? '');

  return {
    id: post.uri,
    rkey: rkeyFromUri(post.uri),
    did: author.did ?? null,
    author: author.handle ?? author.did ?? 'unknown',
    displayName: author.displayName ?? null,
    text,
    timestampMs: Number.isFinite(stamp) ? stamp : null,
    defaultAvatar: !author.avatar,
    accountCreatedMs: Number.isFinite(accountCreated) ? accountCreated : null,
  };
}

/**
 * Walk a threadViewPost into a flat list of replies.
 *
 * The root post is excluded: it is the subject under discussion, not a reply,
 * and including it would let it cluster with quotes of itself.
 */
export function flattenThread(threadRoot) {
  const out = [];
  if (!isViewablePost(threadRoot)) return out;

  const stack = [...(threadRoot.replies ?? [])];
  while (stack.length) {
    const node = stack.pop();
    if (!isViewablePost(node)) continue;
    const comment = toComment(node);
    if (comment) out.push(comment);
    if (Array.isArray(node.replies)) stack.push(...node.replies);
  }
  return out;
}

/** Everything needed to analyse the thread at `url`, or null if not a thread. */
export async function loadThread(url, { fetchImpl = fetch, depth = 30 } = {}) {
  const parsed = parsePostUrl(url);
  if (!parsed) return null;

  const did = await resolveActor(parsed.actor, fetchImpl);
  const body = await fetchThread(buildAtUri(did, parsed.rkey), { fetchImpl, depth });
  const comments = flattenThread(body?.thread);

  return {
    threadKey: `bluesky:${did}/${parsed.rkey}`,
    comments,
  };
}

/**
 * Locate the rendered post elements and key them by record key.
 *
 * Bluesky's markup changes like any app's, so rather than depending on a
 * testid this finds every link that points at a post and climbs to the
 * smallest ancestor that still contains exactly one post. That ancestor is the
 * post's card whatever the class names happen to be this week.
 */
export function findRenderedPosts(doc, spec = BLUESKY_SPEC) {
  const byRkey = new Map();
  const anchors = doc.querySelectorAll('a[href*="/post/"]');

  for (const anchor of anchors) {
    const href = anchor.getAttribute('href') || '';
    const match = href.match(spec.postLinkPattern);
    if (!match) continue;
    const rkey = match[2];

    let element = anchor;
    let candidate = null;
    for (let depth = 0; depth < 10 && element.parentElement; depth++) {
      element = element.parentElement;
      if (countDistinctPosts(element, spec) > 1) break;
      candidate = element;
    }
    if (!candidate) continue;

    // Several links inside one card resolve to the same element; keep the
    // largest region found for a given post.
    const existing = byRkey.get(rkey);
    if (!existing || candidate.contains(existing)) byRkey.set(rkey, candidate);
  }
  return byRkey;
}

function countDistinctPosts(element, spec) {
  const seen = new Set();
  for (const anchor of element.querySelectorAll('a[href*="/post/"]')) {
    const match = (anchor.getAttribute('href') || '').match(spec.postLinkPattern);
    if (match) seen.add(match[2]);
    if (seen.size > 1) return seen.size;
  }
  return seen.size;
}
