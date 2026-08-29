const DEFAULTS = {
  enabled: true,
  showWeak: false,
  memoryEnabled: true,
  hidePanel: false,
  disabledHosts: [],
};

const el = (id) => document.getElementById(id);

async function currentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function loadSettings() {
  const stored = await chrome.storage.sync.get('settings');
  return { ...DEFAULTS, ...(stored?.settings ?? {}) };
}

async function saveSettings(settings) {
  await chrome.storage.sync.set({ settings });
  const tab = await currentTab();
  if (tab?.id) {
    chrome.tabs.sendMessage(tab.id, { type: 'chorus:settings-changed' }).catch(() => {});
  }
}

function renderSummary(summary, platform) {
  el('platform').textContent = platform
    ? `Reading ${platform}`
    : 'No supported comment section on this page.';

  const target = el('summary');
  target.textContent = '';

  if (!summary) {
    const p = document.createElement('div');
    p.className = 'empty';
    p.textContent = 'Nothing analysed yet. Open a thread with replies loaded.';
    target.appendChild(p);
    return;
  }

  if (!summary.clusters && !summary.coordinated && !summary.suspicious) {
    const p = document.createElement('div');
    p.className = 'empty';
    p.textContent = `Checked ${summary.total} replies. No repeated wording found.`;
    target.appendChild(p);
    return;
  }

  const rows = [
    ['Replies checked', summary.total],
    ['Repeated-text groups', summary.clusters],
    ['Accounts involved', summary.accountsInClusters],
    ['Strong matches', summary.coordinated],
    ['Partial matches', summary.suspicious],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement('div');
    row.className = 'stat';
    const l = document.createElement('span');
    l.textContent = label;
    const v = document.createElement('span');
    v.textContent = String(value ?? 0);
    row.appendChild(l);
    row.appendChild(v);
    target.appendChild(row);
  }
}

async function init() {
  const settings = await loadSettings();
  for (const key of ['enabled', 'showWeak', 'memoryEnabled']) {
    el(key).checked = Boolean(settings[key]);
    el(key).addEventListener('change', async () => {
      settings[key] = el(key).checked;
      await saveSettings(settings);
    });
  }

  el('rescan').addEventListener('click', async () => {
    const tab = await currentTab();
    if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: 'chorus:rescan' }).catch(() => {});
    setTimeout(refresh, 700);
  });

  el('options').addEventListener('click', () => chrome.runtime.openOptionsPage());

  refresh();
}

async function refresh() {
  const tab = await currentTab();
  if (!tab?.id) return renderSummary(null, null);
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: 'chorus:request-summary' });
    renderSummary(response?.summary ?? null, response?.platform ?? null);
  } catch {
    // No content script on this tab — an unsupported site, or the page was
    // loaded before the extension was installed.
    renderSummary(null, null);
  }
}

init();
