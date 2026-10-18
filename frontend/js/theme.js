// Light / dark / system theme, remembered in this browser.

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

export function storedTheme() {
  try {
    return localStorage.getItem("mentora-theme") ?? "system";
  } catch {
    return "system";
  }
}

export function saveTheme(theme) {
  try {
    localStorage.setItem("mentora-theme", theme);
  } catch {
    /* storage unavailable */
  }
  applyTheme(theme);
  window.dispatchEvent(new Event("mentora-theme"));
}
