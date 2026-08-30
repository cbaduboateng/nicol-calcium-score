# Chorus

A browser extension that highlights replies repeating the same wording across many
accounts — the fingerprint of a coordinated posting campaign — and shows you the
evidence behind every mark.

Works on Bluesky, X/Twitter, YouTube and Reddit. Runs entirely in your browser.
No account, no API keys, no data leaves your machine.

---

## What this is, and what it deliberately is not

Chorus answers a question it can actually answer:

> **Is this reply repeating wording that other accounts are also posting?**

It does **not** answer "is this account a bot?" or "was this written by AI?",
because those questions cannot be answered reliably from a single short comment,
and pretending otherwise causes real harm.

### Why there is no "AI detector" in here

This was the first thing the project was going to build, and the evidence says
don't:

- OpenAI withdrew its own AI Text Classifier in July 2023, citing low accuracy.
- A Stanford study (Liang et al., *Patterns*, 2023) found GPT detectors
  systematically misclassify writing by **non-native English speakers** as
  machine-generated.
- Accuracy is worst on short text — which is exactly what a comment is.

A tool that stamps "AI-GENERATED" on a migrant's imperfectly-punctuated comment
would do more damage than the campaigns it set out to expose. So Chorus contains
no stylometric scoring at all. There is a regression test
(`no stylometric guessing: fluent formal prose is never flagged`) that fails the
build if fluent formal writing ever gets flagged on style.

What Chorus does look for instead is **corroborated, checkable facts**.

## The signals

| Signal | What it observes | Strength |
|---|---|---|
| **Duplicate text** | The same wording from multiple distinct accounts, surviving emoji, punctuation, zero-width characters and swapped `@mentions` | Strong |
| **Template match** | The same sentence skeleton once names, numbers and links are masked — "Frankly *X* has destroyed *Y* in *N* years" | Strong |
| **Cross-thread memory** | Wording this account has posted in other threads you have read | Strong |
| **Author flood** | One account posting near-identical replies repeatedly in one thread | Moderate |
| **LLM leakage** | Literal assistant boilerplate — "As an AI language model…", unfilled `[insert X]` placeholders | Moderate |
| **Link repetition** | One destination pushed by several distinct accounts | Weak |
| **Reply burst** | Replies arriving far faster than the thread's own baseline rate | Weak |
| **Handle shape / default avatar** | Auto-generated-looking handle, no profile picture | Very weak |
| **Account age** | Account created shortly before it posted (where the source exposes it) | Very weak |

### The guardrail

The last three rows can **never**, on their own, raise a comment above the lowest
band. Promotion requires corroborating evidence involving another account or a
hard artefact. A default avatar and a numeric handle describe someone who did not
customise their profile, and treating that as grounds for calling a person a bot
would turn this into a harassment tool.

This is enforced structurally in `analyze.js` — see the `HARD_EVIDENCE` set and
the gate in `band()` — not by convention, and it is covered by two tests named
`GUARDRAIL:` that fail the build if the property ever breaks.

## Two kinds of source, and why Bluesky is better

Chorus reads a thread in one of two ways.

**Scraped sources** (X, YouTube, Reddit) read the rendered DOM. That is the only
option on a closed platform, and it carries a permanent handicap: you see only
the replies the platform chose to load, which is a biased sample. It is why
burst detection is weighted low here — the arrival-rate estimate is unreliable
by construction.

**API sources** (Bluesky) fetch the *complete* reply set from the open,
unauthenticated AT Protocol AppView, analyse all of it, and then paint results
onto whichever posts happen to be on screen. This is strictly better:

- A cluster is reported at its true size. If fourteen accounts posted the same
  line and three are rendered, the chip still says fourteen, and the panel tells
  you the rest are not on screen yet.
- Timestamps come from `indexedAt`, assigned by the server. The alternative,
  `record.createdAt`, is set by the posting client and is trivially forged —
  which matters, because burst detection is a timing signal.
- Account age arrives free with every post via `profileViewBasic.createdAt`.
- Identifiers are real DIDs and AT-URIs, not guesses derived from the markup.
- **Nothing can silently rot.** There are no selectors to break.

Requests go through the extension's service worker rather than the page,
because a content script's `fetch` runs under the host page's CSP and CORS,
neither of which is under our control. The proxy is allowlisted to the Bluesky
public AppView only — it is deliberately not a general-purpose proxy.

Only two public endpoints are used, `com.atproto.identity.resolveHandle` and
`app.bsky.feed.getPostThread`, with no credentials and no user identifiers.
Results are cached per thread for 45 seconds so scrolling does not re-request.

### What about publishing labels?

AT Protocol lets third parties run *labeler* services that publish moderation
labels network-wide. Chorus deliberately does not do this, and the reason is in
the data model: a label is `{src, uri, cid, val, neg, cts, exp, sig}` where
`val` is a string of at most 128 characters. **There is no field for evidence.**

Everything that makes this tool defensible — "this wording appears in 6 replies
from 6 accounts, average similarity 100%" — has nowhere to live in a label. What
would ship instead is a bare accusation attached to a named person, published
publicly and signed. A false positive stops being a private annotation one
reader dismisses and becomes a durable public claim, with an appeals queue
someone has to staff.

So Chorus reads from AT Protocol and publishes nothing. If that ever changes it
should be post records only, never accounts; `severity: inform`, `blurs: none`,
`defaultSetting: ignore`; and with `exp` set, because coordination is a property
of a moment rather than of a person.

## Installing

Nothing to compile.

```bash
git clone <this repo>
cd chorus-extension
node --test 'tests/*.test.js'   # 31 tests, no dependencies

# Optional: end-to-end tests, which load the real extension into Chromium.
npm install playwright && npx playwright install chromium
node tests/e2e/run.js       # scraped adapter, against an X-shaped page
node tests/e2e/bluesky.js   # API adapter, against a mocked AT Protocol thread
```

**Chrome / Edge / Brave**
1. Go to `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select the `extension/` folder

**Firefox**
1. Go to `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on** → select `extension/manifest.json`

Then open any Bluesky, X, YouTube or Reddit thread and scroll the replies.

## What you will see

- A coloured stripe down the left edge of marked replies
- A small chip explaining the mark in a few words
- Click the chip for the full evidence: exactly what matched, how many accounts
  are involved, and the caveats that apply
- **Show the other matching replies** dims everything except that cluster, so
  you can see the whole ring at once
- A thread summary panel: *"Checked 214 replies. 3 repeated-text groups, 27 accounts involved."*
- **Not a match — unmark** on every popover, because the tool will be wrong
  sometimes and you should be able to say so

Nothing is ever hidden, blocked or reported. Chorus annotates; you decide.

## Privacy

- **Nothing is uploaded.** There is no analytics, no telemetry, no account.
- Cross-thread memory stores a 64-bit fingerprint of a reply's *wording*, the
  handle, and which thread it appeared in — **never the comment text**, never a
  browsing history. It lives in the extension's own IndexedDB and is capped at
  50,000 records / 30 days.
- You can inspect the count and erase it at any time in Settings.
- The optional selector-pack endpoint receives a plain GET with no query string,
  no cookies and no body. It cannot learn who you are or what you are reading.

## How it works

```
extension/src/
  core/          Pure, browser-free, fully unit tested
    text.js        normalisation, char-shingles, Jaccard, SimHash
    cluster.js     union-find clustering over sketch-generated candidate pairs
    signals.js     burst detection, handle shapes, LLM leakage, link repetition
    analyze.js     evidence aggregation, banding, and the hard-evidence gate
  content/
    adapters/      per-platform sources: selectors as DATA, plus the Bluesky API adapter
    ui/            markers, evidence popover, thread panel
    index.js       observe → extract → analyse → paint
  storage/db.js    cross-thread memory (LSH over SimHash bands)
  background/      badge, selector-pack refresh, memory (one shared store)
worker/            optional Cloudflare Worker serving selector packs
```

Two design decisions carry most of the weight:

**Selectors are data, not code.** Platforms rename DOM attributes constantly, and
shipping a scraper fix through an extension store takes days. Because adapters are
plain selector maps, a refreshed pack from `worker/` repairs a broken platform in
minutes. Fetched packs are validated before use and fall back to the built-ins.

**Memory lives in the service worker.** A content script's IndexedDB belongs to the
*host page's* origin, so storing sightings in the content script would give x.com
one silo and youtube.com another — defeating the entire point. All memory
operations are messaged to the background worker, which owns a single store on the
extension's own origin.

## Known limitations

Stated plainly, because a tool like this is dangerous when oversold:

- **On scraped sources it only sees loaded replies.** Platforms load a biased
  subset, which is why burst detection is weighted low there. This limitation
  does not apply to Bluesky, where the whole thread is fetched.
- **Selectors rot.** When X reshuffles its DOM, detection silently stops until the
  adapter is updated. Check `confirmed` dates in `builtin.js`. Again, not a
  Bluesky problem — that adapter does not scrape.
- **The Bluesky adapter has not been run against the live API.** It is built to
  the published lexicons and covered end-to-end against a mocked AppView, but
  the network was unavailable in the environment where it was written, so it
  needs one real-world smoke test.
- **Coordinated ≠ inauthentic.** Fandoms, activist campaigns and ordinary people
  repeating a slogan all produce genuine clusters. The UI says so on every popover.
- **Short replies are ignored** (under 4 words). "lol", "this" and "same" are
  identical across thousands of real people.
- **Sophisticated operations defeat it.** A campaign that generates genuinely
  varied wording per account will not cluster. Chorus raises the cost of cheap
  copypasta operations; it does not stop a well-resourced one.
- **YouTube exposes no machine-readable timestamps**, so burst detection is
  unavailable there.

## Roadmap

- Account-history signals (reply-only ratio, follower shape) where sources expose them
- Optional fact-check matching via the Google Fact Check Tools API, through the worker
- Image provenance: C2PA Content Credentials verification on media in replies
- Exportable cluster reports for researchers and platform reporting
- Firefox MV3 packaging and store submission

## Contributing

The core is dependency-free and unit tested; please keep it that way.
Any change touching `analyze.js` must keep both `GUARDRAIL:` tests passing.

## Licence

MIT — see [LICENSE](LICENSE).
