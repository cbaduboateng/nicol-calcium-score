/**
 * Selector-pack endpoint (Cloudflare Workers).
 *
 * Purpose: social platforms rename DOM attributes without warning, which
 * silently breaks any extension that scrapes them. Shipping a fix through an
 * extension store takes days. This endpoint serves the selectors as data so a
 * broken adapter can be repaired in minutes.
 *
 * Privacy properties, which are deliberate and worth preserving if you extend
 * this: the extension sends a plain GET with no query string, no headers of its
 * own, no cookies (credentials: 'omit') and no body. There is nothing here to
 * identify a user or reveal what they are reading, and the worker keeps no
 * logs of its own. Do not add request parameters without thinking about that.
 *
 * Deploy:  npx wrangler deploy
 * Then set PACK_URL in extension/src/background/service-worker.js.
 */

const PACK = {
  version: 3,
  updated: '2026-08-29',
  specs: [
    {
      id: 'x',
      label: 'X / Twitter',
      hosts: ['x.com', 'twitter.com'],
      confirmed: '2026-08',
      selectors: {
        root: 'main',
        item: 'article[data-testid="tweet"]',
        text: '[data-testid="tweetText"]',
        author: '[data-testid="User-Name"]',
        time: 'time[datetime]',
        avatar: '[data-testid="Tweet-User-Avatar"] img, [data-testid^="UserAvatar"] img',
      },
      defaultAvatarHints: ['default_profile'],
      threadKeyFrom: 'path:/status/',
    },
    {
      id: 'youtube',
      label: 'YouTube',
      hosts: ['youtube.com', 'm.youtube.com'],
      confirmed: '2026-08',
      selectors: {
        root: 'ytd-comments, #comments',
        item: 'ytd-comment-thread-renderer',
        text: '#content-text',
        author: '#author-text',
        avatar: '#author-thumbnail img',
      },
      defaultAvatarHints: ['default-user', 'no_profile'],
      threadKeyFrom: 'query:v',
    },
    {
      id: 'reddit',
      label: 'Reddit',
      hosts: ['reddit.com', 'old.reddit.com'],
      confirmed: '2026-08',
      selectors: {
        root: 'main, .commentarea',
        item: 'shreddit-comment, .comment',
        text: '[slot="comment"], .usertext-body',
        author: '[slot="commentMeta"] a, .author',
        time: 'time[datetime]',
      },
      threadKeyFrom: 'path:/comments/',
    },
  ],
};

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, OPTIONS',
  'access-control-max-age': '86400',
};

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }
    if (request.method !== 'GET') {
      return new Response('Method not allowed', { status: 405, headers: CORS });
    }

    const { pathname } = new URL(request.url);
    if (pathname === '/health') {
      return json({ ok: true, version: PACK.version });
    }
    if (pathname !== '/' && pathname !== '/pack') {
      return new Response('Not found', { status: 404, headers: CORS });
    }

    return json(PACK, {
      // Long enough that the endpoint costs nothing at scale, short enough
      // that a fix reaches users the same day.
      'cache-control': 'public, max-age=3600',
    });
  },
};

function json(body, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    headers: {
      'content-type': 'application/json; charset=utf-8',
      ...CORS,
      ...extraHeaders,
    },
  });
}
