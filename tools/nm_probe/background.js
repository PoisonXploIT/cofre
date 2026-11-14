// Sonda H23: abre la pagina de prueba sola, sin depender del popup.
chrome.runtime.onInstalled.addListener(() => {
  chrome.tabs.create({ url: "probe.html" });
});
chrome.runtime.onStartup.addListener(() => {
  chrome.tabs.create({ url: "probe.html" });
});
