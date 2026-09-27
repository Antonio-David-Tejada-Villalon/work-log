// Atajo, solo Android + Chrome, para prellenar una alarma en el Reloj nativo del teléfono (fuera de esta app).
// La persona tiene que tocar "Guardar" ahí: un sitio web no tiene permiso para guardarla sola. Una vez creada,
// queda fuera de nuestro control: no se puede ver, editar ni borrar desde acá ni desde el asistente.
export const isAndroid = () => /Android/i.test(navigator.userAgent || '')

export function nativeAlarmUrl(date, message) {
  const enc = encodeURIComponent
  const fallback = enc(location.origin + '/')
  return 'intent:#Intent;action=android.intent.action.SET_ALARM;' +
    `i.android.intent.extra.alarm.HOUR=${date.getHours()};i.android.intent.extra.alarm.MINUTES=${date.getMinutes()};` +
    `S.android.intent.extra.alarm.MESSAGE=${enc(message || '')};S.browser_fallback_url=${fallback};end`
}
