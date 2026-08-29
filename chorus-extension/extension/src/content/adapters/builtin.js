/**
 * Built-in selector packs.
 *
 * These are the fallback used when no refreshed pack has been fetched, or when
 * a fetched pack fails validation. They will rot — that is expected and is why
 * the remote pack mechanism exists. Each entry records the date it was last
 * confirmed against the live site so a stale adapter is obvious.
 */

export const BUILTIN_SPECS = [
  {
    id: 'x',
    label: 'X / Twitter',
    hosts: ['x.com', 'twitter.com'],
    confirmed: '2026-08',
    // Replies and the root post share the same testid; the root post is
    // filtered out later by comparing against the thread's focused status.
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
    // YouTube exposes only relative times ("2 days ago"), so burst detection
    // is unavailable here and the analyser will simply skip that signal.
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
];

/**
 * Threads are identified by a stable key so cross-thread memory can tell
 * "seen elsewhere" from "seen twice on this page". Query strings and tracking
 * parameters must not change the key.
 */
export function threadKeyFor(spec, url) {
  try {
    const parsed = new URL(url);
    const rule = spec.threadKeyFrom || '';
    if (rule.startsWith('path:')) {
      const marker = rule.slice(5);
      const idx = parsed.pathname.indexOf(marker);
      if (idx !== -1) {
        const tail = parsed.pathname.slice(idx + marker.length).split('/')[0];
        return `${spec.id}:${tail}`;
      }
    } else if (rule.startsWith('query:')) {
      const param = parsed.searchParams.get(rule.slice(6));
      if (param) return `${spec.id}:${param}`;
    }
    return `${spec.id}:${parsed.origin}${parsed.pathname}`;
  } catch {
    return `${spec.id}:unknown`;
  }
}
