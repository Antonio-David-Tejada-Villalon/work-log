// Cliente de la API. VITE_API_URL permite usar un backend en otro dominio; vacío = mismo origen.
const BASE = import.meta.env.VITE_API_URL || ''

export const apiUrl = (path) => BASE + '/api' + path

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + '/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = `Error ${res.status}`
    try { msg = (await res.json()).detail || msg } catch { /* respuesta sin JSON */ }
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return res.json()
}

export async function downloadExcel(desde, hasta) {
  const q = new URLSearchParams()
  if (desde) q.set('desde', desde)
  if (hasta) q.set('hasta', hasta)
  const res = await fetch(`${BASE}/api/export.xlsx?${q}`)
  if (!res.ok) throw new Error('No se pudo generar el Excel')
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `control_horario_${new Date().toISOString().slice(0, 10)}.xlsx`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

// ---- utilidades de tiempo
export const hms = (secs) => {
  const neg = secs < 0
  let s = Math.round(Math.abs(secs))
  const h = Math.floor(s / 3600); s %= 3600
  const m = Math.floor(s / 60); s %= 60
  return (neg ? '-' : '') + [h, m, s].map((n) => String(n).padStart(2, '0')).join(':')
}
export const hhmm = (iso) => (iso ? iso.slice(11, 16) : '—')
export const todayISO = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
export const fmtDate = (d) => {
  const [y, m, dd] = d.split('-').map(Number)
  return new Date(y, m - 1, dd).toLocaleDateString('es-AR', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' })
}
