const DEFAULTS = {
  enabled: true,
  showWeak: false,
  memoryEnabled: true,
  hidePanel: false,
  disabledHosts: [],
};

const TOGGLES = ['enabled', 'showWeak', 'hidePanel', 'memoryEnabled'];
const el = (id) => document.getElementById(id);

async function load() {
  const stored = await chrome.storage.sync.get('settings');
  const settings = { ...DEFAULTS, ...(stored?.settings ?? {}) };
  for (const key of TOGGLES) el(key).checked = Boolean(settings[key]);
  el('disabledHosts').value = (settings.disabledHosts ?? []).join('\n');
  return settings;
}

async function save() {
  const settings = {
    ...DEFAULTS,
    ...Object.fromEntries(TOGGLES.map((key) => [key, el(key).checked])),
    disabledHosts: el('disabledHosts')
      .value.split('\n')
      .map((line) => line.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, ''))
      .filter(Boolean),
  };
  await chrome.storage.sync.set({ settings });

  // Nudge any open tabs so the change takes effect without a reload.
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (tab.id) chrome.tabs.sendMessage(tab.id, { type: 'chorus:settings-changed' }).catch(() => {});
  }

  const saved = el('saved');
  saved.hidden = false;
  setTimeout(() => {
    saved.hidden = true;
  }, 1800);
}

async function refreshStats() {
  try {
    const stats = await chrome.runtime.sendMessage({ type: 'chorus:memory-stats' });
    if (stats?.unavailable) {
      el('stats').textContent = 'Memory is unavailable — storage may be blocked in this browser.';
      return;
    }
    const count = stats?.records ?? 0;
    el('stats').textContent =
      count === 0
        ? 'No wording fingerprints stored yet. They accumulate as you read threads.'
        : `${count.toLocaleString()} wording fingerprints stored, all on this device. ` +
          'Records older than 30 days are discarded automatically.';
  } catch {
    el('stats').textContent = 'Could not read memory statistics.';
  }
}

el('save').addEventListener('click', save);
el('clearMemory').addEventListener('click', async () => {
  if (!confirm('Erase all stored wording fingerprints? This cannot be undone.')) return;
  await chrome.runtime.sendMessage({ type: 'chorus:memory-clear' }).catch(() => {});
  refreshStats();
});

load().then(refreshStats);
