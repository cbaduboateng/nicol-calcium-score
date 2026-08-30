/**
 * Evidence aggregation and banding.
 *
 * Design rule, and the one that matters most in this codebase:
 *
 *   No comment is ever raised above "weak" on the strength of account
 *   cosmetics alone. Promotion requires corroborated evidence — text shared
 *   with other accounts, a template skeleton shared with other accounts, a
 *   match against something already seen in a different thread, or literal
 *   assistant boilerplate.
 *
 * A default avatar and a numeric handle describe a person who did not
 * customise their profile. Treating that as grounds for calling someone a bot
 * would make this tool a harassment aid, so the aggregator refuses to do it
 * structurally rather than by convention. See BANDS and the hard-evidence
 * gate in scoreComment().
 */

import { normalize, templateMask, wordCount } from './text.js';
import { clusterNearDuplicates } from './cluster.js';
import {
  detectBursts,
  inspectHandle,
  detectLlmLeak,
  detectLinkRepetition,
  detectAuthorFlood,
  detectNewAccounts,
} from './signals.js';

/**
 * Evidence weights, in arbitrary "points". Tuned so that a single strong,
 * corroborated fact clears the "suspicious" bar, and two clear it decisively,
 * while any pile of weak circumstantial signals cannot.
 */
export const WEIGHTS = {
  DUPLICATE_TEXT: (authors) => (authors >= 10 ? 5 : authors >= 5 ? 4 : authors >= 3 ? 3 : 1.5),
  TEMPLATE_MATCH: (authors) => (authors >= 6 ? 3 : authors >= 4 ? 2.5 : 1.5),
  MEMORY_AUTHOR_REPEAT: 3,
  MEMORY_TEXT_SEEN: (threads) => (threads >= 3 ? 2.5 : 1.5),
  AUTHOR_FLOOD: 2,
  LLM_LEAK: 2.5,
  LINK_REPEAT: 1,
  BURST: 1.5,
  HANDLE_PATTERN: 0.5,
  NEW_ACCOUNT: 0.5,
  DEFAULT_AVATAR: 0.25,
};

/** Findings that count as corroboration — each one involves another account or hard artefact. */
const HARD_EVIDENCE = new Set([
  'DUPLICATE_TEXT',
  'TEMPLATE_MATCH',
  'MEMORY_AUTHOR_REPEAT',
  'MEMORY_TEXT_SEEN',
  'AUTHOR_FLOOD',
  'LLM_LEAK',
]);

export const BANDS = {
  COORDINATED: 'coordinated',
  SUSPICIOUS: 'suspicious',
  WEAK: 'weak',
  NONE: 'none',
};

const THRESHOLDS = { coordinated: 4, suspicious: 2, weak: 0.75 };

/** Comments too short to carry a distinguishing fingerprint are left alone. */
const MIN_WORDS_FOR_TEXT_SIGNALS = 4;

/**
 * @param {object} input
 * @param {Array} input.comments  {id, author, text, timestampMs, defaultAvatar}
 * @param {Map}   [input.memory]  id -> {authorRepeatThreads, textThreads, textAuthors}
 * @param {object} [input.options]
 */
export function analyzeThread({ comments = [], memory = new Map(), options = {} } = {}) {
  const opts = {
    duplicateThreshold: 0.82,
    templateThreshold: 0.9,
    ...options,
  };

  const prepared = comments.map((c) => {
    const norm = normalize(c.text);
    return {
      ...c,
      norm,
      words: wordCount(norm),
      template: templateMask(c.text),
    };
  });
  const byId = new Map(prepared.map((c) => [c.id, c]));

  const longEnough = prepared.filter((c) => c.words >= MIN_WORDS_FOR_TEXT_SIGNALS);

  // --- cluster detection -------------------------------------------------
  const duplicateClusters = clusterNearDuplicates(
    longEnough.map((c) => ({ id: c.id, norm: c.norm })),
    { threshold: opts.duplicateThreshold }
  ).map((cluster, i) => decorate(cluster, byId, 'duplicate', i));

  const inDuplicate = new Set(duplicateClusters.flatMap((c) => c.members));

  // Template clusters are computed over everything, then reduced to the
  // comments a duplicate cluster did not already explain, so the same fact is
  // not counted twice.
  const templateClusters = clusterNearDuplicates(
    longEnough.map((c) => ({ id: c.id, norm: c.template })),
    { threshold: opts.templateThreshold }
  )
    .map((cluster, i) => decorate(cluster, byId, 'template', i))
    .map((cluster) => ({
      ...cluster,
      members: cluster.members.filter((id) => !inDuplicate.has(id)),
    }))
    .filter((cluster) => {
      const authors = new Set(cluster.members.map((id) => byId.get(id)?.author));
      return cluster.members.length > 1 && authors.size >= 3;
    })
    .map((cluster) => ({
      ...cluster,
      authors: [...new Set(cluster.members.map((id) => byId.get(id)?.author))],
    }));

  // --- thread-level signals ---------------------------------------------
  const bursts = detectBursts(prepared);
  const links = detectLinkRepetition(prepared);
  const floods = detectAuthorFlood(prepared, duplicateClusters);
  const newAccounts = detectNewAccounts(prepared);

  const clusterOf = new Map();
  for (const cluster of [...duplicateClusters, ...templateClusters]) {
    for (const id of cluster.members) {
      if (!clusterOf.has(id)) clusterOf.set(id, []);
      clusterOf.get(id).push(cluster);
    }
  }

  // --- per-comment scoring ----------------------------------------------
  const scored = prepared.map((comment) =>
    scoreComment(comment, {
      clusters: clusterOf.get(comment.id) || [],
      burst: bursts.flagged.has(comment.id),
      linkDomain: links.flagged.get(comment.id),
      floodCount: floods.get(comment.id),
      accountAgeDays: newAccounts.get(comment.id),
      memoryHit: memory.get(comment.id),
    })
  );

  const clusters = [...duplicateClusters, ...templateClusters].filter(
    (c) => c.members.length > 1
  );

  return {
    comments: scored,
    clusters,
    bursts: bursts.windows,
    linkDomains: links.domains,
    summary: summarise(scored, clusters),
  };
}

function decorate(cluster, byId, kind, index) {
  const authors = [...new Set(cluster.members.map((id) => byId.get(id)?.author).filter(Boolean))];
  return {
    id: `${kind}-${index}`,
    kind,
    members: cluster.members,
    authors,
    similarity: cluster.similarity,
    representative: byId.get(cluster.members[0])?.text ?? cluster.representative,
  };
}

function scoreComment(comment, context) {
  const findings = [];

  for (const cluster of context.clusters) {
    const others = cluster.authors.filter((a) => a !== comment.author).length;
    if (cluster.kind === 'duplicate' && cluster.authors.length >= 2) {
      findings.push({
        code: 'DUPLICATE_TEXT',
        weight: WEIGHTS.DUPLICATE_TEXT(cluster.authors.length),
        label: `Identical text from ${cluster.authors.length} accounts`,
        detail:
          `This wording appears in ${cluster.members.length} replies in this thread, ` +
          `posted by ${cluster.authors.length} different accounts ` +
          `(average similarity ${(cluster.similarity * 100).toFixed(0)}%).`,
        clusterId: cluster.id,
      });
    } else if (cluster.kind === 'template' && others >= 2) {
      findings.push({
        code: 'TEMPLATE_MATCH',
        weight: WEIGHTS.TEMPLATE_MATCH(cluster.authors.length),
        label: `Shared sentence template across ${cluster.authors.length} accounts`,
        detail:
          `Once names, numbers and links are masked, this reply has the same ` +
          `skeleton as ${cluster.members.length - 1} others from ` +
          `${cluster.authors.length - 1} other accounts.`,
        clusterId: cluster.id,
      });
    }
  }

  if (context.memoryHit?.authorRepeatThreads > 0) {
    findings.push({
      code: 'MEMORY_AUTHOR_REPEAT',
      weight: WEIGHTS.MEMORY_AUTHOR_REPEAT,
      label: 'Same account, same text, other threads',
      detail:
        `You have seen this account post near-identical text in ` +
        `${context.memoryHit.authorRepeatThreads} other thread(s).`,
    });
  } else if (context.memoryHit?.textThreads > 0) {
    findings.push({
      code: 'MEMORY_TEXT_SEEN',
      weight: WEIGHTS.MEMORY_TEXT_SEEN(context.memoryHit.textThreads),
      label: 'Text seen in other threads',
      detail:
        `This wording has appeared in ${context.memoryHit.textThreads} other thread(s) ` +
        `you have viewed, from ${context.memoryHit.textAuthors || 'other'} account(s).`,
    });
  }

  if (context.floodCount) {
    findings.push({
      code: 'AUTHOR_FLOOD',
      weight: WEIGHTS.AUTHOR_FLOOD,
      label: 'Repeated by the same account',
      detail: `This account posted ${context.floodCount} near-identical replies in this thread.`,
    });
  }

  const leak = detectLlmLeak(comment.text);
  if (leak) {
    findings.push({
      code: 'LLM_LEAK',
      weight: WEIGHTS.LLM_LEAK,
      label: 'Language-model boilerplate',
      detail: `Contains ${leak.label}: "${leak.excerpt}".`,
    });
  }

  if (context.linkDomain) {
    findings.push({
      code: 'LINK_REPEAT',
      weight: WEIGHTS.LINK_REPEAT,
      label: 'Link pushed by several accounts',
      detail: `Several distinct accounts in this thread link to ${context.linkDomain}.`,
    });
  }

  if (context.burst) {
    findings.push({
      code: 'BURST',
      weight: WEIGHTS.BURST,
      label: 'Posted inside a reply burst',
      detail: 'Part of a cluster of replies arriving far faster than this thread’s normal rate.',
    });
  }

  const handleShape = inspectHandle(comment.author);
  if (handleShape) {
    findings.push({
      code: 'HANDLE_PATTERN',
      weight: WEIGHTS.HANDLE_PATTERN,
      label: 'Default-style handle',
      detail: `Handle looks auto-generated (${handleShape}). Many real users never change theirs.`,
    });
  }

  if (context.accountAgeDays !== undefined) {
    findings.push({
      code: 'NEW_ACCOUNT',
      weight: WEIGHTS.NEW_ACCOUNT,
      label: 'Account was new when it posted',
      detail:
        `The account was ${context.accountAgeDays} day(s) old when this was posted. ` +
        'Every genuine new user looks like this too.',
    });
  }

  if (comment.defaultAvatar) {
    findings.push({
      code: 'DEFAULT_AVATAR',
      weight: WEIGHTS.DEFAULT_AVATAR,
      label: 'No profile picture',
      detail: 'Account uses the default avatar. Very weak on its own.',
    });
  }

  const points = findings.reduce((sum, f) => sum + f.weight, 0);
  const hasHardEvidence = findings.some((f) => HARD_EVIDENCE.has(f.code));

  return {
    id: comment.id,
    author: comment.author,
    findings,
    points: Number(points.toFixed(2)),
    hasHardEvidence,
    band: band(points, hasHardEvidence),
  };
}

/**
 * The hard-evidence gate. Without corroboration a comment cannot exceed WEAK,
 * no matter how many circumstantial signals accumulate.
 */
export function band(points, hasHardEvidence) {
  if (!hasHardEvidence) return points >= THRESHOLDS.weak ? BANDS.WEAK : BANDS.NONE;
  if (points >= THRESHOLDS.coordinated) return BANDS.COORDINATED;
  if (points >= THRESHOLDS.suspicious) return BANDS.SUSPICIOUS;
  if (points >= THRESHOLDS.weak) return BANDS.WEAK;
  return BANDS.NONE;
}

function summarise(scored, clusters) {
  const counts = { coordinated: 0, suspicious: 0, weak: 0, none: 0 };
  for (const c of scored) counts[c.band]++;
  const clusteredAuthors = new Set(clusters.flatMap((c) => c.authors));
  return {
    total: scored.length,
    ...counts,
    clusters: clusters.length,
    accountsInClusters: clusteredAuthors.size,
  };
}
