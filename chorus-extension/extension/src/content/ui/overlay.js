/**
 * Rendering.
 *
 * The interface deliberately never says "bot". It reports what was observed
 * and lets the reader draw the conclusion, because the underlying evidence
 * supports statements like "this text appears 14 times from 14 accounts" and
 * does not support "this person is a bot". Every marker is expandable into the
 * specific finding that produced it.
 */

const BAND_COPY = {
  coordinated: {
    label: 'Coordinated',
    chip: (report) => summarisePrimary(report) || 'Matches other accounts',
    caveat:
      'This describes a pattern across accounts, not a judgement about any individual. ' +
      'Coordinated posting can also come from campaigns, fandoms or organised activism.',
  },
  suspicious: {
    label: 'Shared wording',
    chip: (report) => summarisePrimary(report) || 'Shares wording with other accounts',
    caveat:
      'Shared wording has innocent explanations: quoting the article, a popular joke, ' +
      'or a slogan people are repeating deliberately.',
  },
  weak: {
    label: 'Weak signal',
    chip: () => 'Minor signal',
    caveat:
      'This is circumstantial only. Plenty of ordinary accounts look like this — ' +
      'treat it as nothing more than a prompt to read carefully.',
  },
};

function summarisePrimary(result) {
  const primary = [...result.findings].sort((a, b) => b.weight - a.weight)[0];
  return primary ? primary.label : null;
}

const BAND_CLASSES = [
  'chorus-band-coordinated',
  'chorus-band-suspicious',
  'chorus-band-weak',
];

export class Overlay {
  constructor(doc) {
    this.doc = doc;
    /** element -> {band, chipText, dimmed} describing what is currently painted. */
    this.marks = new Map();
    this.popover = null;
    this.panel = null;
    this.panelSignature = null;
    this.onDismiss = null;
  }

  /** Remove every trace of the extension from the page. */
  clear() {
    for (const el of [...this.marks.keys()]) this.unmark(el);
    this.marks.clear();
    for (const chip of this.doc.querySelectorAll('.chorus-chip')) chip.remove();
    this.closePopover();
    this.panel?.remove();
    this.panel = null;
    this.panelSignature = null;
  }

  /**
   * Reconcile the page against the latest report.
   *
   * Analysis re-runs whenever the feed mutates, which during active scrolling
   * is several times a second. Tearing every mark down and rebuilding it would
   * make the page visibly flicker and would close the popover under the user's
   * cursor, so this diffs against what is already painted and touches only
   * what actually changed.
   */
  render(report, elementsById, options = {}) {
    const { showWeak = false, focusClusterId = null } = options;

    const desired = new Map();
    for (const result of report.comments) {
      const element = elementsById.get(result.id);
      if (!element) continue;

      const visible =
        result.band === 'coordinated' ||
        result.band === 'suspicious' ||
        (result.band === 'weak' && showWeak);
      if (!visible) continue;

      const dimmed = focusClusterId
        ? !result.findings.some((f) => f.clusterId === focusClusterId)
        : false;

      desired.set(element, {
        result,
        band: result.band,
        chipText: BAND_COPY[result.band].chip(result),
        dimmed,
      });
    }

    // Retract marks that no longer apply — including nodes the platform has
    // recycled to hold entirely different comments.
    for (const element of [...this.marks.keys()]) {
      if (!desired.has(element) || !element.isConnected) this.unmark(element);
    }

    for (const [element, want] of desired) {
      const current = this.marks.get(element);
      if (
        current &&
        current.band === want.band &&
        current.chipText === want.chipText &&
        current.dimmed === want.dimmed
      ) {
        // Already correct: leave the DOM completely alone.
        this.marks.set(element, { ...want });
        continue;
      }
      this.applyMark(element, want, report);
    }

    this.renderPanel(report, options);
  }

  applyMark(element, want, report) {
    element.classList.add('chorus-marked');
    for (const cls of BAND_CLASSES) {
      element.classList.toggle(cls, cls === `chorus-band-${want.band}`);
    }
    element.classList.toggle('chorus-dimmed', want.dimmed);

    let chip = element.querySelector(':scope > .chorus-chip');
    if (!chip) {
      chip = this.buildChip();
      element.appendChild(chip);
    }
    this.updateChip(chip, want, report);
    this.marks.set(element, { ...want });
  }

  unmark(element) {
    element.classList.remove('chorus-marked', 'chorus-dimmed', ...BAND_CLASSES);
    element.querySelector(':scope > .chorus-chip')?.remove();
    this.marks.delete(element);
  }

  /**
   * The chip is built once per element and then updated in place. Its click
   * handler reads the current result off the node rather than closing over it,
   * so re-analysis never needs to detach and re-attach listeners.
   */
  buildChip() {
    const chip = this.doc.createElement('button');
    chip.type = 'button';

    const dot = this.doc.createElement('span');
    dot.className = 'chorus-chip-dot';
    chip.appendChild(dot);
    chip.appendChild(this.doc.createTextNode(''));

    chip.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const { result, report } = chip.chorusState ?? {};
      if (result) this.showPopover(chip, result, report);
    });
    return chip;
  }

  updateChip(chip, want, report) {
    chip.className = `chorus-chip chorus-chip-${want.band}`;
    chip.setAttribute(
      'aria-label',
      `Why this reply was marked: ${BAND_COPY[want.band].label}`
    );
    chip.lastChild.nodeValue = want.chipText;
    chip.chorusState = { result: want.result, report };
  }

  showPopover(anchor, result, report) {
    this.closePopover();

    const copy = BAND_COPY[result.band];
    const pop = this.doc.createElement('div');
    pop.className = 'chorus-popover';
    pop.setAttribute('role', 'dialog');

    const bandLabel = this.doc.createElement('div');
    bandLabel.className = 'chorus-band-label';
    bandLabel.style.color =
      result.band === 'coordinated' ? '#d1344b' : result.band === 'suspicious' ? '#b5701c' : '#6b7280';
    bandLabel.textContent = copy.label;
    pop.appendChild(bandLabel);

    const heading = this.doc.createElement('h3');
    heading.textContent = 'What was observed';
    pop.appendChild(heading);

    for (const finding of [...result.findings].sort((a, b) => b.weight - a.weight)) {
      const wrap = this.doc.createElement('div');
      wrap.className = 'chorus-finding';

      const label = this.doc.createElement('div');
      label.className = 'chorus-finding-label';
      label.textContent = finding.label;
      wrap.appendChild(label);

      const detail = this.doc.createElement('div');
      detail.className = 'chorus-finding-detail';
      detail.textContent = finding.detail;
      wrap.appendChild(detail);

      pop.appendChild(wrap);
    }

    const caveat = this.doc.createElement('div');
    caveat.className = 'chorus-caveat';
    caveat.textContent = copy.caveat;
    pop.appendChild(caveat);

    const actions = this.doc.createElement('div');
    actions.className = 'chorus-popover-actions';

    const clusterFinding = result.findings.find((f) => f.clusterId);
    if (clusterFinding) {
      const highlight = this.doc.createElement('button');
      highlight.className = 'chorus-btn';
      highlight.type = 'button';
      highlight.textContent = 'Show the other matching replies';
      highlight.addEventListener('click', () => {
        this.onFocusCluster?.(clusterFinding.clusterId);
        this.closePopover();
      });
      actions.appendChild(highlight);
    }

    const dismiss = this.doc.createElement('button');
    dismiss.className = 'chorus-btn';
    dismiss.type = 'button';
    dismiss.textContent = 'Not a match — unmark';
    dismiss.addEventListener('click', () => {
      this.onDismiss?.(result);
      this.closePopover();
    });
    actions.appendChild(dismiss);

    pop.appendChild(actions);
    this.doc.body.appendChild(pop);
    this.position(pop, anchor);
    this.popover = pop;

    this.escHandler = (e) => {
      if (e.key === 'Escape') this.closePopover();
    };
    this.outsideHandler = (e) => {
      if (!pop.contains(e.target) && e.target !== anchor) this.closePopover();
    };
    this.doc.addEventListener('keydown', this.escHandler);
    // Deferred so the click that opened the popover does not immediately close it.
    setTimeout(() => this.doc.addEventListener('click', this.outsideHandler), 0);
  }

  position(pop, anchor) {
    const rect = anchor.getBoundingClientRect();
    const width = pop.offsetWidth;
    const height = pop.offsetHeight;
    let left = rect.left;
    let top = rect.bottom + 8;
    if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
    if (top + height > window.innerHeight - 12) top = Math.max(12, rect.top - height - 8);
    pop.style.left = `${Math.max(12, left)}px`;
    pop.style.top = `${top}px`;
  }

  closePopover() {
    if (!this.popover) return;
    this.popover.remove();
    this.popover = null;
    if (this.escHandler) this.doc.removeEventListener('keydown', this.escHandler);
    if (this.outsideHandler) this.doc.removeEventListener('click', this.outsideHandler);
  }

  renderPanel(report, options) {
    if (options.hidePanel) {
      this.panel?.remove();
      this.panel = null;
      this.panelSignature = null;
      return;
    }

    // Rebuild only when the numbers actually change, so the panel does not
    // flicker on every scroll tick.
    const signature = JSON.stringify([report.summary, options.focusClusterId]);
    if (this.panel?.isConnected && signature === this.panelSignature) return;
    this.panelSignature = signature;
    this.panel?.remove();

    const { summary } = report;
    const panel = this.doc.createElement('div');
    panel.className = 'chorus-panel';

    const title = this.doc.createElement('div');
    title.className = 'chorus-panel-title';
    const titleText = this.doc.createElement('span');
    titleText.textContent = 'Chorus';
    title.appendChild(titleText);

    const close = this.doc.createElement('button');
    close.className = 'chorus-panel-close';
    close.type = 'button';
    close.setAttribute('aria-label', 'Hide panel');
    close.textContent = '×';
    close.addEventListener('click', () => panel.remove());
    title.appendChild(close);
    panel.appendChild(title);

    if (summary.clusters === 0 && summary.coordinated === 0 && summary.suspicious === 0) {
      const clean = this.doc.createElement('div');
      clean.className = 'chorus-clean';
      clean.textContent = `Checked ${summary.total} replies. No repeated wording or shared templates found.`;
      panel.appendChild(clean);
    } else {
      panel.appendChild(stat(this.doc, 'Replies checked', summary.total));
      panel.appendChild(stat(this.doc, 'Repeated-text groups', summary.clusters));
      panel.appendChild(stat(this.doc, 'Accounts involved', summary.accountsInClusters));
      if (summary.coordinated) panel.appendChild(stat(this.doc, 'Strong matches', summary.coordinated));
      if (summary.suspicious) panel.appendChild(stat(this.doc, 'Partial matches', summary.suspicious));

      if (options.focusClusterId) {
        const actions = this.doc.createElement('div');
        actions.className = 'chorus-popover-actions';
        const reset = this.doc.createElement('button');
        reset.className = 'chorus-btn';
        reset.type = 'button';
        reset.textContent = 'Clear highlight';
        reset.addEventListener('click', () => this.onFocusCluster?.(null));
        actions.appendChild(reset);
        panel.appendChild(actions);
      }
    }

    this.doc.body.appendChild(panel);
    this.panel = panel;
  }
}

function stat(doc, label, value) {
  const row = doc.createElement('div');
  row.className = 'chorus-stat';
  const l = doc.createElement('span');
  l.textContent = label;
  const v = doc.createElement('span');
  v.className = 'chorus-stat-value';
  v.textContent = String(value);
  row.appendChild(l);
  row.appendChild(v);
  return row;
}
