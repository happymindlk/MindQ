// Loaded as an external file because the CSP (script-src 'self') blocks inline scripts.
// Runs before first paint so the stored theme applies without a flash.
(function () {
  var theme = 'dark';
  try {
    var stored = window.localStorage.getItem('theme');
    if (stored === 'light' || stored === 'dark') theme = stored;
  } catch (e) {
    theme = 'dark';
  }
  var root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.style.colorScheme = theme;
})();
