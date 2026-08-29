/**
 * MV3 content scripts are classic scripts and cannot use static imports, so
 * this stub is the registered entry point and pulls in the real module graph
 * dynamically. Every file under src/ is listed in web_accessible_resources to
 * make that import resolvable.
 */
(async () => {
  try {
    await import(chrome.runtime.getURL('src/content/index.js'));
  } catch (error) {
    console.error('[chorus] failed to load', error);
  }
})();
