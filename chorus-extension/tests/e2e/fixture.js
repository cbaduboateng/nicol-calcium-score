/**
 * Builds a page that mirrors X's reply DOM closely enough to exercise the real
 * adapter selectors: article[data-testid="tweet"] items containing
 * [data-testid="tweetText"], [data-testid="User-Name"] and time[datetime].
 */

export const ORGANIC = [
  ['marylouise', 'Honestly this is the best thing I have read all week, thank you for posting'],
  ['tomh_writes', 'I disagree with the second paragraph but the rest of it is solid enough'],
  ['data_nerd_88', 'Where did you get these numbers? The ONS release says something different'],
  ['pauline_g', 'my nan has been saying this for years and nobody ever listened to her'],
  ['jokesonyou', 'Lol the replies to this are going to be absolutely unhinged, popcorn ready'],
  ['s_okonkwo', 'Genuinely useful thread. Saving this for later when I have more time'],
  ['renter_rights', 'This ignores the fact that rents doubled over the same period though'],
  ['correction_guy', 'Great write up, one small correction: the vote was in November not October'],
];

export const RING_LINE =
  'The mainstream media will never tell you the truth about who is really funding this';

export const RING_HANDLES = [
  'patriot_voice7781',
  'realtalk442199',
  'wakeupsheeple31',
  'truthseeker908812',
  'britfirst2291',
  'nononsense771023',
];

function reply(handle, text, minutesAgo, opts = {}) {
  const time = new Date(Date.parse('2026-08-29T14:00:00Z') - minutesAgo * 60_000).toISOString();
  const avatar = opts.defaultAvatar
    ? 'https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png'
    : `https://example.invalid/avatar/${handle}.jpg`;
  return `
  <article data-testid="tweet">
    <div data-testid="Tweet-User-Avatar"><img src="${avatar}" alt=""></div>
    <div data-testid="User-Name">
      <span>${handle.replace(/_/g, ' ')}</span><span>@${handle}</span><span>·</span>
      <time datetime="${time}">${minutesAgo}m</time>
    </div>
    <div data-testid="tweetText">${text}</div>
  </article>`;
}

export function buildPage() {
  const organic = ORGANIC.map(([handle, text], i) => reply(handle, text, 60 - i * 5));
  // The ring posts within a few seconds of each other, all with default avatars.
  const ring = RING_HANDLES.map((handle, i) =>
    reply(handle, RING_LINE, 12 - i * 0.02, { defaultAvatar: true })
  );

  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Post</title>
<style>
  body { font: 15px/1.4 system-ui, sans-serif; margin: 0; background: #fff; color: #0f1419; }
  main { max-width: 600px; margin: 0 auto; }
  article { padding: 12px 16px; border-bottom: 1px solid #eff3f4; }
  [data-testid="User-Name"] { font-size: 14px; color: #536471; margin-bottom: 3px; }
  [data-testid="User-Name"] span:first-child { color: #0f1419; font-weight: 700; }
  [data-testid="Tweet-User-Avatar"] img { width: 32px; height: 32px; border-radius: 50%; float: left; margin-right: 10px; background: #ccd6dd; }
  [data-testid="tweetText"] { clear: both; }
  h1 { padding: 16px; margin: 0; font-size: 17px; border-bottom: 1px solid #eff3f4; }
</style></head>
<body><main>
  <h1>Thread with replies</h1>
  ${[...organic.slice(0, 4), ...ring, ...organic.slice(4)].join('\n')}
</main></body></html>`;
}
