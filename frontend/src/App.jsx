import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, apiUrl, downloadExcel, fmtDate, hhmm, hms, todayISO } from './api'
import { getThemePref, setThemePref } from './theme'
import { getRatePref, getVoicePref, isNatural, setRatePref, setVoicePref, speak, ttsSupported, useVoice, useVoices, voiceSupported } from './voice'

const TABS = [
  ['hoy', 'Hoy', 'bi-clock'],
  ['hist', 'Historial', 'bi-calendar3'],
  ['banco', 'Banco', 'bi-piggy-bank'],
  ['ia', 'Asistente', 'bi-mic'],
  ['cfg', 'Ajustes', 'bi-gear'],
]
const monthStart = () => todayISO().slice(0, 8) + '01'

function useNow(active) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  return now
}

// Imagen opcional: si el archivo no existe en /public, se oculta sin romper el diseño.
function OptionalImg({ src, alt = '', className }) {
  const [ok, setOk] = useState(true)
  return ok ? <img src={src} alt={alt} className={className} onError={() => setOk(false)} /> : null
}

// Modal de Bootstrap controlado por React (sin el JS de Bootstrap).
function Modal({ title, onClose, children }) {
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', k)
    document.body.classList.add('modal-open')
    return () => { document.removeEventListener('keydown', k); document.body.classList.remove('modal-open') }
  }, [onClose])
  return (
    <>
      <div className="modal fade show d-block" tabIndex="-1" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
        <div className="modal-dialog modal-dialog-centered modal-dialog-scrollable modal-fullscreen-sm-down" onClick={(e) => e.stopPropagation()}>
          <div className="modal-content">
            <div className="modal-header">
              <h5 className="modal-title">{title}</h5>
              <button type="button" className="btn-close" aria-label="Cerrar" onClick={onClose} />
            </div>
            <div className="modal-body">{children}</div>
          </div>
        </div>
      </div>
      <div className="modal-backdrop fade show" />
    </>
  )
}

const Stat = ({ k, v, className = '', onClick }) => (
  <div className={`stat ${onClick ? 'clickable' : ''}`} onClick={onClick}>
    <div className="k">{k}</div>
    <div className={`v ${className}`}>{v}</div>
  </div>
)

// ---------------------------------------------------------------- App
export default function App() {
  const [tab, setTab] = useState('hoy')
  const [status, setStatus] = useState(null)
  const [fetchedAt, setFetchedAt] = useState(Date.now())
  const [toast, setToast] = useState('')
  const [needLogin, setNeedLogin] = useState(false)
  const [loginMsg] = useState(() => new URLSearchParams(location.search).get('login') || '')
  const [rev, setRev] = useState(0)

  const notify = useCallback((m) => { setToast(m); setTimeout(() => setToast(''), 3500) }, [])
  const refresh = useCallback(async () => {
    try {
      setStatus(await api('/status'))
      setFetchedAt(Date.now())
      setNeedLogin(false)
      setRev((r) => r + 1)
    } catch (e) {
      if (e.status === 401) setNeedLogin(true)
      else notify(e.message)
    }
  }, [notify])

  useEffect(() => {
    refresh()
    if (loginMsg) {
      history.replaceState(null, '', '/')
      if (loginMsg === 'ok') notify('Sesión iniciada. Google Calendar y Tareas conectados.')
    }
  }, [refresh, notify, loginMsg])

  if (needLogin) return <LoginScreen msg={loginMsg} />

  const props = { status, refresh, notify, rev, fetchedAt, setTab }
  const current = TABS.find((t) => t[0] === tab)
  return (
    <>
      <nav className="navbar navbar-app sticky-top">
        <div className="container app-container px-3">
          <span className="navbar-brand d-flex align-items-center gap-2 fw-bold mb-0">
            <img src="/icon-192.png" alt="" />
            <span>{current[1]}</span>
          </span>
          {status?.en_curso && <span className="badge rounded-pill badge-live"><i className="bi bi-record-circle-fill me-1" />Trabajando</span>}
        </div>
      </nav>

      <main className="container app-container px-3 py-3">
        {!status ? (
          <div className="text-center py-5"><div className="spinner-border text-primary" role="status"><span className="visually-hidden">Cargando…</span></div></div>
        ) : (
          <>
            {tab === 'hoy' && <Today {...props} />}
            {tab === 'hist' && <History {...props} />}
            {tab === 'banco' && <Bank {...props} />}
            {tab === 'ia' && <Assistant {...props} />}
            {tab === 'cfg' && <SettingsView {...props} />}
          </>
        )}
      </main>

      <nav className="nav-bottom fixed-bottom" aria-label="Secciones">
        <ul className="nav nav-fill container app-container px-0">
          {TABS.map(([k, label, icon]) => (
            <li className="nav-item" key={k}>
              <button className={`nav-link w-100 border-0 bg-transparent ${tab === k ? 'active' : ''}`}
                aria-current={tab === k ? 'page' : undefined} onClick={() => setTab(k)}>
                <i className={`bi ${tab === k ? icon + '-fill' : icon}`} aria-hidden="true" />{label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {toast && (
        <div className="toast-container position-fixed start-50 translate-middle-x p-2">
          <div className="toast show text-bg-dark border-0" role="status" aria-live="polite">
            <div className="toast-body">{toast}</div>
          </div>
        </div>
      )}
    </>
  )
}

const LOGIN_MSG = {
  denied: 'Tu cuenta de Google no tiene acceso. Pedile al dueño de la app que te invite con ese correo.',
  error: 'No se pudo iniciar sesión con Google. Probá de nuevo.',
  config: 'La app todavía no está configurada para iniciar sesión. Avisale al dueño.',
}

// Cada persona entra con su cuenta de Google: un solo permiso cubre su identidad y su Calendar y Tasks.
function LoginScreen({ msg }) {
  return (
    <main className="container app-container px-3 d-flex align-items-center" style={{ minHeight: '85dvh' }}>
      <div className="card w-100">
        <div className="card-body p-4 text-center">
          <img src="/icon-192.png" alt="" width="64" height="64" className="rounded-3 mb-3" />
          <h1 className="h4 mb-1">Control Horario</h1>
          <p className="text-body-secondary small mb-4">Registrá tu jornada, tus horas extra y tu banco de horas. Entrá con tu cuenta de Google.</p>
          {LOGIN_MSG[msg] && <div className="alert alert-danger small py-2 text-start" role="alert">{LOGIN_MSG[msg]}</div>}
          <a className="btn btn-primary btn-lg w-100" href={apiUrl('/auth/google/start')}>
            <i className="bi bi-google me-2" />Continuar con Google
          </a>
          <p className="form-text mt-3 mb-0">
            Se te va a pedir permiso para ver tu correo y crear eventos y tareas en tu Google Calendar y Tasks. Cada persona ve solo sus propios datos.
          </p>
        </div>
      </div>
    </main>
  )
}

// ---------------------------------------------------------------- Hoy
function Today({ status, refresh, notify, fetchedAt, setTab }) {
  const open = status.en_curso
  const now = useNow(Boolean(open))
  const [custom, setCustom] = useState(false)
  const [hora, setHora] = useState('')
  const [nota, setNota] = useState('')
  const [busy, setBusy] = useState(false)

  const elapsed = open ? (now - new Date(open.inicio).getTime()) / 1000 : 0
  const base = status.resumen_hoy?.trabajado_segundos || 0
  const todayWorked = open ? base + (now - fetchedAt) / 1000 : base
  const target = status.ajustes.daily_hours * 3600
  const extraNow = Math.max(0, todayWorked - target)
  const progress = Math.min(100, (todayWorked / target) * 100)

  const act = async () => {
    setBusy(true)
    try {
      const body = { hora: custom && hora ? `${todayISO()}T${hora}` : null, nota }
      await api(open ? '/clock-out' : '/clock-in', { method: 'POST', body })
      notify(open ? 'Salida registrada' : 'Entrada registrada')
      setCustom(false); setHora(''); setNota('')
      await refresh()
    } catch (e) { notify(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between small text-body-secondary">
            <span><i className="bi bi-calendar-event me-1" />{fmtDate(status.hoy)}</span>
            {open && <span><i className="bi bi-box-arrow-in-right me-1" />Desde {hhmm(open.inicio)}</span>}
          </div>
          <div className="timer text-center my-2">{hms(open ? elapsed : 0)}</div>
          <p className="text-center text-body-secondary small mb-2">{open ? 'Jornada en curso' : 'Sin jornada en curso'}</p>
          <div className="progress mb-3" role="progressbar" aria-label="Avance de la jornada" aria-valuenow={Math.round(progress)} aria-valuemin="0" aria-valuemax="100" style={{ height: 6 }}>
            <div className={`progress-bar ${extraNow > 0 ? 'bg-warning' : ''}`} style={{ width: `${progress}%` }} />
          </div>
          {custom && (
            <div className="mb-3">
              <label className="form-label small" htmlFor="hora">Hora de {open ? 'salida' : 'entrada'}</label>
              <input id="hora" className="form-control" type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
            </div>
          )}
          <div className="mb-3">
            <label className="form-label small" htmlFor="nota">Nota (opcional)</label>
            <input id="nota" className="form-control" value={nota} onChange={(e) => setNota(e.target.value)} placeholder="Ej.: guardia, reunión…" />
          </div>
          <button className={`btn ${open ? 'btn-outline-danger' : 'btn-primary'} btn-jornada w-100 fw-semibold`} disabled={busy || (custom && !hora)} onClick={act}>
            {busy ? <span className="spinner-border spinner-border-sm me-2" /> : <i className={`bi ${open ? 'bi-stop-circle' : 'bi-play-circle'} me-2`} />}
            {open ? 'Finalizar jornada' : 'Iniciar jornada'}
          </button>
          <button className="btn btn-link w-100 mt-1 text-decoration-none small" onClick={() => setCustom(!custom)}>
            <i className={`bi ${custom ? 'bi-clock' : 'bi-pencil-square'} me-1`} />
            {custom ? 'Usar la hora actual' : 'Registrar con otra hora'}
          </button>
        </div>
      </div>
      <div className="row g-2 mb-3">
        <div className="col-6"><Stat k="Trabajado hoy" v={hms(todayWorked)} /></div>
        <div className="col-6"><Stat k="Extra hoy" v={hms(extraNow)} className={extraNow ? 'text-extra' : ''} /></div>
        <div className="col-6"><Stat k="Jornada normal" v={hms(target)} /></div>
        <div className="col-6"><Stat k="Banco de horas" v={status.banco.saldo} onClick={() => setTab('banco')}
          className={status.banco.saldo_segundos < 0 ? 'text-danger' : 'text-primary'} /></div>
      </div>
      <button className="btn btn-outline-primary w-100" onClick={() => setTab('ia')}>
        <i className="bi bi-mic-fill me-2" />Hablar con el asistente
      </button>
    </>
  )
}

// ---------------------------------------------------------------- Historial
function ShiftForm({ initial, onSave, onDelete, onClose }) {
  const [f, setF] = useState(initial)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <Modal title={initial.id ? 'Editar jornada' : 'Nueva jornada'} onClose={onClose}>
      <div className="mb-3"><label className="form-label">Fecha</label><input className="form-control" type="date" value={f.fecha} onChange={set('fecha')} /></div>
      <div className="row g-2 mb-2">
        <div className="col"><label className="form-label">Entrada</label><input className="form-control" type="time" value={f.inicio} onChange={set('inicio')} /></div>
        <div className="col"><label className="form-label">Salida</label><input className="form-control" type="time" value={f.fin} onChange={set('fin')} /></div>
      </div>
      <p className="form-text mt-0 mb-3">Si la salida es anterior a la entrada se toma como del día siguiente. Dejá la salida vacía para una jornada en curso.</p>
      <div className="mb-3"><label className="form-label">Nota</label><input className="form-control" value={f.nota} onChange={set('nota')} /></div>
      <button className="btn btn-primary w-100 mb-2" disabled={!f.fecha || !f.inicio} onClick={() => onSave(f)}><i className="bi bi-check2 me-1" />Guardar</button>
      {initial.id && <button className="btn btn-outline-danger w-100" onClick={onDelete}><i className="bi bi-trash3 me-1" />Eliminar jornada</button>}
    </Modal>
  )
}

function ExtraForm({ day, onSave, onClose }) {
  const secs = day.extra_segundos
  const [h, setH] = useState(Math.floor(secs / 3600))
  const [m, setM] = useState(Math.floor((secs % 3600) / 60))
  const [nota, setNota] = useState(day.nota_ajuste || '')
  return (
    <Modal title={`Horas extra · ${fmtDate(day.fecha)}`} onClose={onClose}>
      <div className="alert alert-secondary py-2 small">Calculado automáticamente: <b className="mono">{day.extra_calculada}</b></div>
      <div className="row g-2 mb-3">
        <div className="col"><label className="form-label">Horas</label><input className="form-control" type="number" min="0" value={h} onChange={(e) => setH(e.target.value)} /></div>
        <div className="col"><label className="form-label">Minutos</label><input className="form-control" type="number" min="0" max="59" value={m} onChange={(e) => setM(e.target.value)} /></div>
      </div>
      <div className="mb-3"><label className="form-label">Motivo</label><input className="form-control" value={nota} onChange={(e) => setNota(e.target.value)} /></div>
      <button className="btn btn-primary w-100 mb-2" onClick={() => onSave({ horas: Number(h) || 0, minutos: Number(m) || 0, nota })}>Guardar corrección</button>
      {day.ajuste_manual && <button className="btn btn-outline-secondary w-100" onClick={() => onSave({ horas: null, nota: '' })}>Volver al cálculo automático</button>}
    </Modal>
  )
}

function History({ refresh, notify, rev }) {
  const [desde, setDesde] = useState(monthStart())
  const [hasta, setHasta] = useState(todayISO())
  const [shifts, setShifts] = useState([])
  const [sum, setSum] = useState(null)
  const [edit, setEdit] = useState(null)
  const [extra, setExtra] = useState(null)

  const load = useCallback(async () => {
    try {
      const q = `?desde=${desde}&hasta=${hasta}`
      const [sh, sm] = await Promise.all([api('/shifts' + q), api('/summary' + q)])
      setShifts(sh); setSum(sm)
    } catch (e) { notify(e.message) }
  }, [desde, hasta, notify])
  useEffect(() => { load() }, [load, rev])

  const days = useMemo(() => {
    const map = {}
    for (const d of sum?.dias || []) map[d.fecha] = { ...d, shifts: [] }
    for (const s of shifts) (map[s.fecha] ||= { fecha: s.fecha, shifts: [] }).shifts.push(s)
    return Object.values(map).sort((a, b) => b.fecha.localeCompare(a.fecha))
  }, [shifts, sum])

  const save = async (f) => {
    try {
      const body = { fecha: f.fecha, inicio: f.inicio, fin: f.fin || null, nota: f.nota }
      if (f.id) await api(`/shifts/${f.id}`, { method: 'PUT', body })
      else await api('/shifts', { method: 'POST', body })
      setEdit(null); notify('Jornada guardada'); refresh()
    } catch (e) { notify(e.message) }
  }
  const del = async () => {
    if (!window.confirm('¿Eliminar esta jornada? Esta acción no se puede deshacer.')) return
    try { await api(`/shifts/${edit.id}`, { method: 'DELETE' }); setEdit(null); notify('Jornada eliminada'); refresh() } catch (e) { notify(e.message) }
  }
  const saveExtra = async (b) => {
    try { await api(`/days/${extra.fecha}/extra`, { method: 'PUT', body: b }); setExtra(null); notify('Extras actualizadas'); refresh() } catch (e) { notify(e.message) }
  }

  return (
    <>
      <div className="card mb-3">
        <div className="card-body">
          <div className="row g-2 mb-3">
            <div className="col"><label className="form-label small">Desde</label><input className="form-control" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} /></div>
            <div className="col"><label className="form-label small">Hasta</label><input className="form-control" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} /></div>
          </div>
          {sum && (
            <div className="row g-2 mb-3">
              <div className="col-6"><Stat k={`Trabajado (${sum.totales.dias_trabajados} días)`} v={sum.totales.trabajado} /></div>
              <div className="col-6"><Stat k="Horas extra" v={sum.totales.extras} className="text-extra" /></div>
            </div>
          )}
          <div className="row g-2">
            <div className="col-6"><button className="btn btn-primary w-100" onClick={() => setEdit({ fecha: todayISO(), inicio: '', fin: '', nota: '' })}><i className="bi bi-plus-lg me-1" />Agregar</button></div>
            <div className="col-6"><button className="btn btn-outline-primary w-100" onClick={() => downloadExcel(desde, hasta).catch((e) => notify(e.message))}><i className="bi bi-file-earmark-excel me-1" />Excel</button></div>
          </div>
        </div>
      </div>

      {days.length === 0 && (
        <div className="text-center text-body-secondary py-4">
          <OptionalImg src="/img/empty-history.webp" className="empty-img mb-3" />
          <p className="mb-0">No hay jornadas en este período.</p>
        </div>
      )}
      {days.map((d) => (
        <div key={d.fecha} className="mb-3">
          <div className="d-flex justify-content-between align-items-center small fw-semibold text-body-secondary mb-1 px-1">
            <span className="text-capitalize">{fmtDate(d.fecha)}</span>
            <span className="d-flex align-items-center gap-2">
              <span className="mono">{d.trabajado}</span>
              <button className={`badge rounded-pill border-0 ${d.extra_segundos ? 'badge-extra' : 'text-bg-secondary bg-opacity-25 text-body-secondary'}`}
                onClick={() => setExtra(d)} aria-label={`Corregir horas extra del ${d.fecha}`}>
                +{d.extra}{d.ajuste_manual && <i className="bi bi-pencil-fill ms-1" />}
              </button>
            </span>
          </div>
          <div className="list-group">
            {d.shifts.map((s) => (
              <button key={s.id} className="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                onClick={() => setEdit({ id: s.id, fecha: s.fecha, inicio: hhmm(s.inicio), fin: s.fin ? hhmm(s.fin) : '', nota: s.nota })}>
                <span>
                  <b className="mono">{hhmm(s.inicio)} – {s.fin ? hhmm(s.fin) : 'en curso'}</b>
                  {s.nota && <span className="text-body-secondary small"> · {s.nota}</span>}
                </span>
                <span className="mono small">{s.duracion}<i className="bi bi-chevron-right ms-2 text-body-secondary" /></span>
              </button>
            ))}
            {d.shifts.length === 0 && <div className="list-group-item small text-body-secondary">Solo corrección manual de extras</div>}
          </div>
        </div>
      ))}
      {edit && <ShiftForm initial={edit} onSave={save} onDelete={del} onClose={() => setEdit(null)} />}
      {extra && <ExtraForm day={extra} onSave={saveExtra} onClose={() => setExtra(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- Banco
function Units({ d }) {
  const sign = d.signo < 0 ? '-' : ''
  return (
    <div className="units">
      {[['meses', 'meses'], ['dias', 'días'], ['horas', 'horas'], ['minutos', 'min'], ['segundos', 'seg']].map(([k, l]) => (
        <div key={k}><b>{sign}{d[k]}</b><span>{l}</span></div>
      ))}
    </div>
  )
}

function Bank({ status, refresh, notify, rev }) {
  const [bank, setBank] = useState(null)
  const [f, setF] = useState({ fecha: todayISO(), dias: '', horas: '', minutos: '', nota: '', tipo: 'uso', signo: 1 })
  const [edit, setEdit] = useState(null)
  useEffect(() => { api('/bank').then(setBank).catch((e) => notify(e.message)) }, [rev, notify])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const add = async () => {
    try {
      const sg = f.tipo === 'ajuste' ? Number(f.signo) : 1
      await api('/bank', { method: 'POST', body: { fecha: f.fecha, tipo: f.tipo, nota: f.nota, dias: Number(f.dias) || 0, horas: sg * Math.abs(Number(f.horas) || 0), minutos: sg * Math.abs(Number(f.minutos) || 0) } })
      notify(f.tipo === 'uso' ? 'Horas descontadas del banco' : 'Ajuste registrado')
      setF({ ...f, dias: '', horas: '', minutos: '', nota: '' })
      refresh()
    } catch (e) { notify(e.message) }
  }
  const saveEdit = async () => {
    try {
      const total = (Math.abs(Number(edit.horas) || 0) + Math.abs(Number(edit.minutos) || 0) / 60) * Number(edit.signo)
      await api(`/bank/${edit.id}`, { method: 'PUT', body: { fecha: edit.fecha, horas: total, minutos: 0, nota: edit.nota } })
      setEdit(null); notify('Movimiento actualizado'); refresh()
    } catch (e) { notify(e.message) }
  }
  const delMov = async () => {
    if (!window.confirm('¿Eliminar este movimiento del banco?')) return
    try { await api(`/bank/${edit.id}`, { method: 'DELETE' }); setEdit(null); notify('Movimiento eliminado'); refresh() } catch (e) { notify(e.message) }
  }
  if (!bank) return <div className="text-center py-5"><div className="spinner-border text-primary" role="status" /></div>
  const neg = bank.saldo_segundos < 0

  return (
    <>
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center">
            <span className="small text-body-secondary"><i className="bi bi-piggy-bank me-1" />Saldo del banco</span>
            {neg && <span className="badge rounded-pill text-bg-danger">Saldo negativo</span>}
          </div>
          <div className={`timer text-center my-2 ${neg ? 'text-danger' : 'text-primary'}`}>{bank.saldo}</div>
          <p className="small text-body-secondary mb-1">En jornadas laborales ({bank.jornada_horas} h por día · mes de {bank.dias_laborables_mes} jornadas)</p>
          <Units d={bank.desglose.laboral} />
          <p className="small text-body-secondary mb-1 mt-3">En tiempo reloj (día de 24 h · mes de 30 días)</p>
          <Units d={bank.desglose.reloj} />
          <div className="row g-2 mt-2">
            <div className="col-6"><Stat k="Extras acumuladas" v={bank.extras_acumuladas} className="text-extra" /></div>
            <div className="col-6"><Stat k="Horas usadas" v={bank.usadas} /></div>
            <div className="col-6"><Stat k="Ajustes a favor" v={bank.ajustes_a_favor} /></div>
            <div className="col-6"><Stat k="Faltantes" v={bank.faltantes} /></div>
          </div>
        </div>
      </div>

      <div className="card mb-3">
        <div className="card-body">
          <h2 className="h6 card-title mb-3">Registrar movimiento</h2>
          <div className="btn-group w-100 mb-3" role="group" aria-label="Tipo de movimiento">
            <input type="radio" className="btn-check" name="tipo" id="t-uso" checked={f.tipo === 'uso'} onChange={() => setF({ ...f, tipo: 'uso' })} />
            <label className="btn btn-outline-primary" htmlFor="t-uso"><i className="bi bi-dash-circle me-1" />Usar horas</label>
            <input type="radio" className="btn-check" name="tipo" id="t-aj" checked={f.tipo === 'ajuste'} onChange={() => setF({ ...f, tipo: 'ajuste' })} />
            <label className="btn btn-outline-primary" htmlFor="t-aj"><i className="bi bi-sliders me-1" />Ajuste</label>
          </div>
          {f.tipo === 'ajuste' && (
            <div className="mb-3">
              <label className="form-label small">Sentido del ajuste</label>
              <select className="form-select" value={f.signo} onChange={set('signo')}><option value={1}>Sumar al banco</option><option value={-1}>Restar del banco</option></select>
            </div>
          )}
          <div className="mb-3"><label className="form-label small">Fecha</label><input className="form-control" type="date" value={f.fecha} onChange={set('fecha')} /></div>
          <div className="row g-2 mb-3">
            {f.tipo === 'uso' && <div className="col"><label className="form-label small">Días</label><input className="form-control" type="number" min="0" step="0.5" value={f.dias} onChange={set('dias')} /></div>}
            <div className="col"><label className="form-label small">Horas</label><input className="form-control" type="number" min="0" step="0.5" value={f.horas} onChange={set('horas')} /></div>
            <div className="col"><label className="form-label small">Minutos</label><input className="form-control" type="number" min="0" value={f.minutos} onChange={set('minutos')} /></div>
          </div>
          <div className="mb-3"><label className="form-label small">Nota</label><input className="form-control" value={f.nota} onChange={set('nota')} placeholder="Ej.: día libre por trámite" /></div>
          <button className="btn btn-primary w-100" onClick={add}>{f.tipo === 'uso' ? 'Descontar del banco' : 'Registrar ajuste'}</button>
          <div className="form-text">1 día = {status.ajustes.daily_hours} h (tu jornada configurada).</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header bg-transparent fw-semibold">Movimientos</div>
        <div className="list-group list-group-flush">
          {bank.movimientos.length === 0 && <div className="list-group-item small text-body-secondary">Sin movimientos.</div>}
          {[...bank.movimientos].reverse().map((m) => (
            <button key={m.id} className="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
              onClick={() => { const a = Math.abs(m.segundos); setEdit({ ...m, signo: m.segundos < 0 ? -1 : 1, horas: Math.floor(a / 3600), minutos: Math.floor((a % 3600) / 60) }) }}>
              <span>
                <span className="fw-semibold text-capitalize">{fmtDate(m.fecha)}</span>{' '}
                <span className="badge rounded-pill text-bg-light border">{m.tipo}</span>
                {m.nota && <div className="small text-body-secondary">{m.nota}</div>}
              </span>
              <span className={`mono ${m.segundos < 0 ? 'text-danger' : 'text-success'}`}>{m.tiempo}</span>
            </button>
          ))}
        </div>
      </div>
      {edit && (
        <Modal title="Editar movimiento" onClose={() => setEdit(null)}>
          <div className="mb-3"><label className="form-label">Fecha</label><input className="form-control" type="date" value={edit.fecha} onChange={(e) => setEdit({ ...edit, fecha: e.target.value })} /></div>
          <div className="row g-2 mb-3">
            <div className="col"><label className="form-label">Horas</label><input className="form-control" type="number" min="0" value={edit.horas} onChange={(e) => setEdit({ ...edit, horas: e.target.value })} /></div>
            <div className="col"><label className="form-label">Minutos</label><input className="form-control" type="number" min="0" max="59" value={edit.minutos} onChange={(e) => setEdit({ ...edit, minutos: e.target.value })} /></div>
          </div>
          {edit.tipo === 'uso' ? <p className="form-text">En los usos el tiempo siempre se resta del banco.</p> : (
            <div className="mb-3"><label className="form-label">Sentido</label>
              <select className="form-select" value={edit.signo} onChange={(e) => setEdit({ ...edit, signo: Number(e.target.value) })}><option value={1}>Sumar al banco</option><option value={-1}>Restar del banco</option></select>
            </div>
          )}
          <div className="mb-3"><label className="form-label">Nota</label><input className="form-control" value={edit.nota} onChange={(e) => setEdit({ ...edit, nota: e.target.value })} /></div>
          <button className="btn btn-primary w-100 mb-2" onClick={saveEdit}>Guardar</button>
          <button className="btn btn-outline-danger w-100" onClick={delMov}><i className="bi bi-trash3 me-1" />Eliminar movimiento</button>
        </Modal>
      )}
    </>
  )
}

// ---------------------------------------------------------------- Asistente IA
const EJEMPLOS = [
  'Empecé a trabajar a las 8',
  'Terminé la jornada',
  'Ayer entré 7:45 y salí 17:10',
  '¿Cuántas horas extra tengo en el banco?',
  'Usá 4 horas del banco para el viernes',
  'Recordame mañana a las 10 llamar al proveedor',
]

function Assistant({ status, refresh }) {
  const [msgs, setMsgs] = useState([{ role: 'assistant', text: '¡Hola! Decime qué querés registrar, consultar o agendar.' }])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [voiceOut, setVoiceOut] = useState(true)
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy])

  const send = useCallback(async (t) => {
    const m = (t ?? text).trim()
    if (!m || busy) return
    setText('')
    const hist = msgs.slice(-10)
    setMsgs((x) => [...x, { role: 'user', text: m }])
    setBusy(true)
    try {
      const r = await api('/assistant', { method: 'POST', body: { mensaje: m, historial: hist } })
      setMsgs((x) => [...x, { role: 'assistant', text: r.respuesta, acciones: r.acciones }])
      if (voiceOut) speak(r.respuesta)
      if (r.acciones?.length) refresh()
    } catch (e) {
      setMsgs((x) => [...x, { role: 'assistant', text: '⚠ ' + e.message }])
    } finally { setBusy(false) }
  }, [text, busy, msgs, voiceOut, refresh])

  const { listening, interim, start, stop } = useVoice((t) => send(t))

  if (!status.ia) {
    return <div className="alert alert-warning"><i className="bi bi-exclamation-triangle me-2" />El asistente necesita la variable <b>GEMINI_API_KEY</b> en el servidor. Ver README.</div>
  }

  return (
    <>
      <div className="chat">
        {msgs.length <= 1 && <OptionalImg src="/img/assistant.webp" className="empty-img mx-auto mb-2" />}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role === 'user' ? 'user' : 'bot'}`}>
            {m.text}
            {m.acciones?.length > 0 && (
              <div className="acts">{m.acciones.map((a, j) => (
                <div key={j}><i className={`bi ${a.ok ? 'bi-check-circle' : 'bi-x-circle'} me-1`} />{a.herramienta.replaceAll('_', ' ')}</div>
              ))}</div>
            )}
          </div>
        ))}
        {interim && <div className="msg user opacity-75">{interim}</div>}
        {busy && <div className="msg bot"><span className="spinner-grow spinner-grow-sm me-2" />Pensando…</div>}
        <div ref={endRef} />
      </div>
      {msgs.length <= 1 && (
        <div className="d-flex flex-wrap gap-2 my-3">
          {EJEMPLOS.map((e) => <button key={e} className="btn btn-sm btn-outline-secondary rounded-pill" style={{ minHeight: 32 }} onClick={() => send(e)}>{e}</button>)}
        </div>
      )}
      <div className="card composer mt-3">
        <div className="card-body d-flex gap-3 align-items-center p-3">
          {voiceSupported && (
            <button className={`btn mic ${listening ? 'btn-danger on' : 'btn-primary'}`} onClick={listening ? stop : start} aria-label={listening ? 'Detener' : 'Hablar'}>
              <i className={`bi ${listening ? 'bi-stop-fill' : 'bi-mic-fill'}`} />
            </button>
          )}
          <div className="flex-grow-1">
            <div className="input-group mb-2">
              <input className="form-control" value={text} placeholder={voiceSupported ? 'Tocá el micrófono o escribí…' : 'Escribí tu consulta…'}
                onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} aria-label="Mensaje" />
              <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={() => send()} aria-label="Enviar"><i className="bi bi-send-fill" /></button>
            </div>
            <div className="form-check form-switch small mb-0">
              <input className="form-check-input" type="checkbox" role="switch" id="voz" checked={voiceOut} onChange={(e) => setVoiceOut(e.target.checked)} />
              <label className="form-check-label" htmlFor="voz">Leer respuestas en voz alta</label>
            </div>
          </div>
        </div>
      </div>
      {!voiceSupported && <p className="small text-body-secondary mt-2">Tu navegador no admite reconocimiento de voz. En Android usá Chrome.</p>}
    </>
  )
}

// ---------------------------------------------------------------- Ajustes
function VoiceSettings() {
  const voices = useVoices()
  const [uri, setUri] = useState(getVoicePref())
  const [rate, setRate] = useState(getRatePref())
  if (!ttsSupported) return null
  const pick = (v) => { setUri(v); setVoicePref(v) }
  const pace = (r) => { setRate(r); setRatePref(r) }
  const test = () => speak('Hola, soy tu asistente. Registré tu entrada a las ocho de la mañana. Hoy tenés dos horas y media en el banco.')
  return (
    <div className="card mb-3">
      <div className="card-body">
        <h2 className="h6 card-title mb-3"><i className="bi bi-volume-up me-2" />Voz del asistente</h2>
        {voices.length === 0 ? (
          <div className="alert alert-secondary small mb-0">Este dispositivo no tiene voces en español instaladas. Probá con Microsoft Edge (Windows) o Chrome (Android).</div>
        ) : (
          <>
            <label className="form-label small" htmlFor="voz-sel">Voz</label>
            <select id="voz-sel" className="form-select mb-3" value={uri} onChange={(e) => pick(e.target.value)}>
              <option value="">Automática · {voices[0].name}</option>
              {voices.map((v) => <option key={v.voiceURI} value={v.voiceURI}>{isNatural(v) ? '★ ' : ''}{v.name} · {v.lang}</option>)}
            </select>
            <label className="form-label small" htmlFor="voz-vel">Velocidad: {rate.toFixed(2).replace(/0$/, '')}×</label>
            <input id="voz-vel" className="form-range mb-2" type="range" min="0.7" max="1.3" step="0.05" value={rate} onChange={(e) => pace(Number(e.target.value))} />
            <button className="btn btn-outline-primary w-100 mb-2" onClick={test}><i className="bi bi-play-fill me-1" />Probar voz</button>
            <p className="form-text mb-0">
              Las marcadas con ★ (Natural o Neural) son las más fluidas. En Windows abrí la app con Microsoft Edge para ver las «Online (Natural)».
              Cada dispositivo tiene sus propias voces, así que esta elección se guarda solo en este equipo.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function SettingsView({ status, refresh, notify }) {
  const [c, setC] = useState(status.ajustes)
  const [d, setD] = useState(monthStart())
  const [h, setH] = useState(todayISO())
  const [theme, setTheme] = useState(getThemePref())
  const save = async () => {
    try {
      await api('/settings', { method: 'PUT', body: { daily_hours: Number(c.daily_hours), workdays_per_month: Number(c.workdays_per_month), count_deficit: c.count_deficit, timezone: c.timezone } })
      notify('Configuración guardada'); refresh()
    } catch (e) { notify(e.message) }
  }
  const disconnect = async () => {
    if (!window.confirm('¿Desconectar tu cuenta de Google?')) return
    await api('/google/disconnect', { method: 'POST' }); refresh()
  }
  const hh = Math.floor(c.daily_hours), mm = Math.round((c.daily_hours - hh) * 60)

  return (
    <>
      <AccountSettings status={status} />

      <div className="card mb-3">
        <div className="card-body">
          <h2 className="h6 card-title mb-3"><i className="bi bi-briefcase me-2" />Jornada laboral</h2>
          <div className="row g-2 mb-2">
            <div className="col"><label className="form-label small">Horas por jornada</label><input className="form-control" type="number" min="0.5" step="0.25" value={c.daily_hours} onChange={(e) => setC({ ...c, daily_hours: e.target.value })} /></div>
            <div className="col"><label className="form-label small">Jornadas por mes</label><input className="form-control" type="number" min="1" value={c.workdays_per_month} onChange={(e) => setC({ ...c, workdays_per_month: e.target.value })} /></div>
          </div>
          <p className="form-text mt-0">Equivale a {hh} h {mm} min. Lo que supere esta cantidad por día se cuenta como hora extra.</p>
          <div className="form-check form-switch mb-3">
            <input className="form-check-input" type="checkbox" role="switch" id="deficit" checked={c.count_deficit} onChange={(e) => setC({ ...c, count_deficit: e.target.checked })} />
            <label className="form-check-label" htmlFor="deficit">Descontar del banco los días en que trabajo menos</label>
          </div>
          <div className="mb-3"><label className="form-label small">Zona horaria</label><input className="form-control" value={c.timezone} onChange={(e) => setC({ ...c, timezone: e.target.value })} /></div>
          <button className="btn btn-primary w-100" onClick={save}>Guardar</button>
        </div>
      </div>

      <div className="card mb-3">
        <div className="card-body">
          <h2 className="h6 card-title mb-3"><i className="bi bi-google me-2" />Google Calendar y Tareas</h2>
          {status.google.conectado ? (
            <><p className="small text-success"><i className="bi bi-check-circle-fill me-1" />Conectado. El asistente puede crear eventos, recordatorios y tareas en tu cuenta.</p>
              <button className="btn btn-outline-danger w-100" onClick={disconnect}>Desconectar</button></>
          ) : (
            <><p className="small text-body-secondary">No conectado: el asistente no puede crear eventos ni tareas. Puede pasar si Google venció el permiso.</p>
              <a className="btn btn-primary w-100" href={apiUrl('/auth/google/start')}><i className="bi bi-link-45deg me-1" />Volver a conectar con Google</a></>
          )}
        </div>
      </div>

      {status.usuario.es_dueno && <InvitedSettings notify={notify} />}

      <div className="card mb-3">
        <div className="card-body">
          <h2 className="h6 card-title mb-3"><i className="bi bi-file-earmark-excel me-2" />Exportar a Excel</h2>
          <div className="row g-2 mb-3">
            <div className="col"><label className="form-label small">Desde</label><input className="form-control" type="date" value={d} onChange={(e) => setD(e.target.value)} /></div>
            <div className="col"><label className="form-label small">Hasta</label><input className="form-control" type="date" value={h} onChange={(e) => setH(e.target.value)} /></div>
          </div>
          <button className="btn btn-outline-primary w-100 mb-2" onClick={() => downloadExcel(d, h).catch((e) => notify(e.message))}><i className="bi bi-download me-1" />Descargar .xlsx</button>
          <button className="btn btn-link w-100 text-decoration-none small" onClick={() => downloadExcel().catch((e) => notify(e.message))}>Descargar todo el historial</button>
        </div>
      </div>

      <VoiceSettings />

      <div className="card mb-3">
        <div className="card-body">
          <h2 className="h6 card-title mb-3"><i className="bi bi-circle-half me-2" />Apariencia</h2>
          <div className="btn-group w-100" role="group" aria-label="Tema">
            {[['auto', 'Automático'], ['light', 'Claro'], ['dark', 'Oscuro']].map(([k, l]) => (
              <Fragment key={k}>
                <input type="radio" className="btn-check" name="theme" id={`th-${k}`} checked={theme === k} onChange={() => { setTheme(k); setThemePref(k) }} />
                <label className="btn btn-outline-primary" htmlFor={`th-${k}`}>{l}</label>
              </Fragment>
            ))}
          </div>
        </div>
      </div>

    </>
  )
}

function AccountSettings({ status }) {
  const u = status.usuario
  const logout = async () => {
    try { await api('/auth/logout', { method: 'POST' }) } catch { /* igual se vuelve al inicio */ }
    location.href = '/'
  }
  return (
    <div className="card mb-3">
      <div className="card-body">
        <h2 className="h6 card-title mb-3"><i className="bi bi-person-circle me-2" />Cuenta</h2>
        <div className="d-flex align-items-center gap-3 mb-3">
          {u.foto && <img src={u.foto} alt="" width="44" height="44" className="rounded-circle" referrerPolicy="no-referrer" />}
          <div className="flex-grow-1" style={{ minWidth: 0 }}>
            <div className="fw-semibold text-truncate">{u.nombre || u.email}</div>
            <div className="small text-body-secondary text-truncate">{u.email}{u.es_dueno && ' · dueño'}</div>
          </div>
        </div>
        <button className="btn btn-outline-secondary w-100" onClick={logout}><i className="bi bi-box-arrow-right me-1" />Cerrar sesión</button>
      </div>
    </div>
  )
}

// Solo lo ve el dueño: quién puede entrar a la app.
function InvitedSettings({ notify }) {
  const [list, setList] = useState(null)
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/admin/invitados').then(setList).catch((e) => notify(e.message)) }, [notify])

  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      setList(await api('/admin/invitados', { method: 'POST', body: { email } }))
      setEmail('')
      notify('Invitación agregada')
    } catch (err) { notify(err.message) } finally { setBusy(false) }
  }
  const remove = async (mail) => {
    if (!window.confirm(`¿Quitar el acceso a ${mail}? Se cierra su sesión; sus datos se conservan.`)) return
    try { setList(await api(`/admin/invitados/${encodeURIComponent(mail)}`, { method: 'DELETE' })) } catch (err) { notify(err.message) }
  }
  const lastLogin = (iso) => (iso ? `último ingreso ${new Date(iso + 'Z').toLocaleDateString('es-AR')}` : 'todavía no entró')

  return (
    <div className="card mb-3">
      <div className="card-body">
        <h2 className="h6 card-title mb-3"><i className="bi bi-people me-2" />Invitados</h2>
        <p className="small text-body-secondary">Solo pueden entrar los correos de esta lista (y el tuyo), con una cuenta de Google que use ese correo.</p>
        <form className="input-group mb-3" onSubmit={add}>
          <input className="form-control" type="email" inputMode="email" placeholder="correo@gmail.com" aria-label="Correo a invitar"
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="btn btn-primary" type="submit" disabled={busy || !email.trim()}>Invitar</button>
        </form>
        {list === null ? (
          <div className="text-center py-2"><div className="spinner-border spinner-border-sm text-primary" role="status"><span className="visually-hidden">Cargando…</span></div></div>
        ) : list.length === 0 ? (
          <p className="small text-body-secondary mb-0">Todavía no invitaste a nadie.</p>
        ) : (
          <ul className="list-group list-group-flush">
            {list.map((i) => (
              <li key={i.email} className="list-group-item d-flex align-items-center justify-content-between px-0 bg-transparent">
                <div style={{ minWidth: 0 }}>
                  <div className="text-truncate">{i.nombre || i.email}</div>
                  <div className="small text-body-secondary text-truncate">{i.nombre ? `${i.email} · ` : ''}{lastLogin(i.ultimo_ingreso)}</div>
                </div>
                <button className="btn btn-sm btn-outline-danger ms-2" onClick={() => remove(i.email)} aria-label={`Quitar a ${i.email}`}><i className="bi bi-x-lg" /></button>
              </li>
            ))}
          </ul>
        )}
        <p className="form-text mt-3 mb-0">Mientras la app de Google esté en modo prueba, agregá también ese correo en Google Cloud → Google Auth Platform → Audience → Test users.</p>
      </div>
    </div>
  )
}
