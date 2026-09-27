// Tema claro/oscuro de Bootstrap (data-bs-theme). Preferencia por dispositivo: auto | light | dark.
const mq = window.matchMedia('(prefers-color-scheme: dark)')

export function getThemePref() {
  try { return localStorage.getItem('theme') || 'auto' } catch { return 'auto' }
}

export function applyTheme(pref = getThemePref()) {
  const theme = pref === 'auto' ? (mq.matches ? 'dark' : 'light') : pref
  document.documentElement.setAttribute('data-bs-theme', theme)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#1B211E' : '#1F5C52')
}

export function setThemePref(pref) {
  try { localStorage.setItem('theme', pref) } catch { /* sin almacenamiento */ }
  applyTheme(pref)
}

export function initTheme() {
  applyTheme()
  mq.addEventListener('change', () => applyTheme())
}
