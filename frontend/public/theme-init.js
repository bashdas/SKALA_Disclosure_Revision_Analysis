// Run before styles and Vue mount so a saved dark theme never starts in light mode.
;(function () {
  var theme = 'light'
  try {
    if (localStorage.getItem('disclosure-check.theme.v1') === 'dark') theme = 'dark'
  } catch (_) {
    // Storage is optional; opening the application must always work.
  }
  document.documentElement.dataset.theme = theme
})()
