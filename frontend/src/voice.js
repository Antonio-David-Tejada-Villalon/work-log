// Voz gratuita del navegador: Web Speech API (reconocimiento) + speechSynthesis (lectura).
import { useEffect, useRef, useState } from 'react'

const Recognition = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
export const voiceSupported = Boolean(Recognition)

export function useVoice(onFinal) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const rec = useRef(null)

  const start = () => {
    if (!Recognition) return
    const r = new Recognition()
    r.lang = 'es-AR'
    r.interimResults = true
    r.continuous = false
    r.onresult = (e) => {
      let text = ''
      let final = false
      for (const res of e.results) { text += res[0].transcript; if (res.isFinal) final = true }
      setInterim(text)
      if (final) { setInterim(''); onFinal(text.trim()) }
    }
    r.onerror = () => setListening(false)
    r.onend = () => setListening(false)
    rec.current = r
    r.start()
    setListening(true)
  }
  const stop = () => { rec.current?.stop(); setListening(false) }
  return { listening, interim, start, stop }
}

// ---- lectura de respuestas (speechSynthesis). Las voces dependen del dispositivo; la elección se guarda en él.
const synth = typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null
export const ttsSupported = Boolean(synth)

const load = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
const save = (k, v) => { try { localStorage.setItem(k, v) } catch { /* sin almacenamiento */ } }
export const getVoicePref = () => load('voice', '')          // voiceURI; vacío = automática
export const setVoicePref = (uri) => save('voice', uri)
export const getRatePref = () => Number(load('voiceRate', 1)) || 1
export const setRatePref = (r) => save('voiceRate', String(r))

const NATURAL = /natural|neural|premium|enhanced|mejorada/i
export const isNatural = (v) => NATURAL.test(v.name)

// Puntaje aproximado de naturalidad: las voces neuronales o en línea suenan mucho menos robóticas
// que las locales antiguas. Dentro de cada grupo se prefiere el español rioplatense/latino.
export function voiceScore(v) {
  const id = `${v.name} ${v.voiceURI}`
  const lang = (v.lang || '').toLowerCase().replace('_', '-')
  let s = 0
  if (NATURAL.test(id)) s += 100
  if (/online|google/i.test(id)) s += 40
  if (/compact|desktop/i.test(id)) s -= 30
  if (lang === 'es-ar') s += 30
  else if (['es-us', 'es-mx', 'es-419'].includes(lang)) s += 20
  else s += 10
  return s
}

// Voces en español instaladas, de la más natural a la menos.
export function listVoices() {
  if (!synth) return []
  return synth.getVoices()
    .filter((v) => (v.lang || '').toLowerCase().replace('_', '-').startsWith('es'))
    .sort((a, b) => voiceScore(b) - voiceScore(a) || a.name.localeCompare(b.name))
}

// Chrome carga las voces de forma asíncrona (evento voiceschanged).
export function useVoices() {
  const [voices, setVoices] = useState(listVoices)
  useEffect(() => {
    if (!synth) return
    const update = () => setVoices(listVoices())
    update()
    synth.addEventListener('voiceschanged', update)
    return () => synth.removeEventListener('voiceschanged', update)
  }, [])
  return voices
}

export function speak(text) {
  if (!synth || !text) return
  synth.cancel()
  const voices = listVoices()
  const v = voices.find((x) => x.voiceURI === getVoicePref()) || voices[0]  // la elegida o la más natural
  const u = new SpeechSynthesisUtterance(text)
  u.lang = v?.lang || 'es-AR'
  if (v) u.voice = v
  u.rate = getRatePref()
  synth.speak(u)
}

// ---- sonidos de alarma: tonos generados con Web Audio (sin archivos que descargar ni licencias).
export const ALARM_SOUNDS = ['clasica', 'suave', 'urgente']
let audioCtx = null

function ctx() {
  const AC = window.AudioContext || window.webkitAudioContext
  if (!AC) return null
  if (!audioCtx) audioCtx = new AC()
  return audioCtx
}

// Llamar una vez ante cualquier toque del usuario: desbloquea el audio para poder sonar sin otra interacción después.
export function unlockAlarmAudio() {
  const ac = ctx()
  if (ac?.state === 'suspended') ac.resume().catch(() => {})
}

function tone(freq, duration, type = 'sine', startDelay = 0, gainPeak = 0.32) {
  const ac = ctx()
  if (!ac) return
  const osc = ac.createOscillator()
  const gain = ac.createGain()
  osc.type = type
  osc.frequency.value = freq
  const t0 = ac.currentTime + startDelay
  gain.gain.setValueAtTime(0, t0)
  gain.gain.linearRampToValueAtTime(gainPeak, t0 + 0.02)
  gain.gain.linearRampToValueAtTime(0, t0 + duration)
  osc.connect(gain).connect(ac.destination)
  osc.start(t0)
  osc.stop(t0 + duration + 0.02)
}

const PATTERNS = {
  clasica: () => { tone(880, 0.18); tone(660, 0.18, 'sine', 0.22) },
  suave: () => { tone(440, 0.7, 'sine', 0, 0.2) },
  urgente: () => { tone(1200, 0.09, 'square', 0); tone(1200, 0.09, 'square', 0.13); tone(1200, 0.09, 'square', 0.26) },
}

// Suena una vez (un "ring") con el patrón elegido. playAlarm en App.jsx llama a esto repeat_count veces.
export function playAlarmTone(sound) {
  const ac = ctx()
  if (ac?.state === 'suspended') ac.resume().catch(() => {})
  ;(PATTERNS[sound] || PATTERNS.clasica)()
}
