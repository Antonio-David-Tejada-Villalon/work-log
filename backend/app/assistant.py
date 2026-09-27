"""Asistente con IA (Google Gemini + function calling) para operar la app por voz o texto."""
import json
import os
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from . import calc, usage
from . import google_integration as gi
from .db import User, get_settings

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_STEPS = 6
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class AiUnavailable(Exception):
    """La IA no puede responder ahora (límite alcanzado o servicio saturado). El mensaje es claro para el usuario."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _friendly(e: Exception, s: Session, u: User) -> Optional[AiUnavailable]:
    """Traduce los errores conocidos de Google a un mensaje entendible; None si no es uno de ellos."""
    code = getattr(e, "code", None)
    if code == 429:
        hora = usage.next_reset(calc.tz(get_settings(s, u.id))).strftime("%H:%M")
        return AiUnavailable("Se alcanzó el límite gratuito de la IA de Google. Si fue el límite por minuto, probá de nuevo "
                             f"en un rato; el límite diario se reinicia a las {hora} (hora de tu zona).", 429)
    if code == 503:
        return AiUnavailable("La IA de Google tiene mucha demanda en este momento. Probá de nuevo en unos segundos.", 503)
    return None


def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {"name": name, "description": desc,
            "parameters_json_schema": {"type": "object", "properties": props, "required": required or []}}


S = {"type": "string"}
N = {"type": "number"}
HORA = {"type": "string", "description": "Hora 'HH:MM' o fecha-hora ISO 'YYYY-MM-DDTHH:MM'. Omitir = ahora."}
FECHA = {"type": "string", "description": "Fecha YYYY-MM-DD"}

TOOLS = [
    _fn("fichar_entrada", "Registra el inicio de la jornada laboral.", {"hora": HORA, "nota": S}),
    _fn("fichar_salida", "Registra el fin de la jornada en curso.", {"hora": HORA, "nota": S}),
    _fn("registrar_jornada", "Carga una jornada completa manualmente.",
        {"fecha": FECHA, "inicio": {"type": "string", "description": "HH:MM"},
         "fin": {"type": "string", "description": "HH:MM"}, "nota": S}, ["fecha", "inicio", "fin"]),
    _fn("modificar_jornada", "Modifica fecha, hora de inicio, hora de fin o nota de una jornada existente (usar su id; "
        "si no lo sabés, primero listar_jornadas).",
        {"id": {"type": "integer"}, "fecha": FECHA, "inicio": S, "fin": S, "nota": S}, ["id"]),
    _fn("eliminar_jornada", "Elimina una jornada. SOLO con confirmado=true después de que el usuario lo confirme.",
        {"id": {"type": "integer"}, "confirmado": {"type": "boolean"}}, ["id", "confirmado"]),
    _fn("listar_jornadas", "Lista las jornadas de un rango de fechas.", {"desde": FECHA, "hasta": FECHA}),
    _fn("resumen", "Horas trabajadas y horas extra por día y totales en un rango.", {"desde": FECHA, "hasta": FECHA}),
    _fn("consultar_banco", "Saldo del banco de horas extra, desglosado en meses, días, horas, minutos y segundos.", {}),
    _fn("usar_banco", "Descuenta horas/días del banco (p. ej. tomarse un día o salir antes).",
        {"fecha": FECHA, "dias": N, "horas": N, "minutos": N, "nota": S}, ["fecha"]),
    _fn("ajustar_banco", "Suma (positivo) o resta (negativo) tiempo al banco como ajuste manual.",
        {"fecha": FECHA, "horas": N, "minutos": N, "nota": S}, ["fecha"]),
    _fn("fijar_extras_dia", "Corrige manualmente las horas extra de un día (horas y minutos). "
        "quitar=true elimina la corrección y vuelve al cálculo automático.",
        {"fecha": FECHA, "horas": N, "minutos": N, "quitar": {"type": "boolean"}, "nota": S}, ["fecha"]),
    _fn("configurar", "Cambia la configuración: horas de la jornada normal, días laborables por mes, "
        "o si las horas faltantes restan del banco.",
        {"horas_diarias": N, "dias_laborables_mes": {"type": "integer"}, "descontar_faltantes": {"type": "boolean"}}),
    _fn("crear_evento_calendar", "Crea un evento o recordatorio en Google Calendar.",
        {"titulo": S, "inicio": {"type": "string", "description": "YYYY-MM-DDTHH:MM (o YYYY-MM-DD si es todo el día)"},
         "fin": S, "descripcion": S, "recordatorio_minutos": {"type": "integer"},
         "todo_el_dia": {"type": "boolean"}}, ["titulo", "inicio"]),
    _fn("listar_eventos_calendar", "Lista próximos eventos de Google Calendar.", {"desde": FECHA, "hasta": FECHA}),
    _fn("crear_tarea", "Crea una tarea en Google Tasks (la fecha límite solo guarda el día).",
        {"titulo": S, "fecha": FECHA, "notas": S}, ["titulo"]),
]


def run_tool(s: Session, u: User, name: str, a: dict[str, Any]) -> Any:
    """Ejecuta una herramienta en nombre del usuario u: solo ve y modifica lo suyo."""
    uid = u.id
    st = get_settings(s, uid)
    if name == "fichar_entrada":
        return calc.shift_out(calc.clock_in(s, uid, a.get("hora"), a.get("nota", "")), st)
    if name == "fichar_salida":
        return calc.shift_out(calc.clock_out(s, uid, a.get("hora"), a.get("nota", "")), st)
    if name == "registrar_jornada":
        return calc.shift_out(calc.create_shift(s, uid, a["fecha"], a["inicio"], a["fin"], a.get("nota", "")), st)
    if name == "modificar_jornada":
        return calc.shift_out(calc.update_shift(s, uid, int(a["id"]), a.get("fecha"), a.get("inicio"), a.get("fin"),
                                                a.get("nota")), st)
    if name == "eliminar_jornada":
        if not a.get("confirmado"):
            return {"error": "Falta confirmación del usuario."}
        calc.delete_shift(s, uid, int(a["id"]))
        return {"ok": True}
    if name == "listar_jornadas":
        return [calc.shift_out(x, st) for x in calc.list_shifts(s, uid, a.get("desde"), a.get("hasta"))][-60:]
    if name == "resumen":
        return {"totales": calc.totals(s, uid, a.get("desde"), a.get("hasta")),
                "dias": calc.daily_summary(s, uid, a.get("desde"), a.get("hasta"))[-31:]}
    if name == "consultar_banco":
        b = calc.bank_status(s, uid)
        b["movimientos"] = b["movimientos"][-10:]
        return b
    if name == "usar_banco":
        return calc.mov_out(calc.add_bank_movement(s, uid, a["fecha"], a.get("horas", 0), a.get("dias", 0),
                                                   a.get("minutos", 0), "uso", a.get("nota", "")))
    if name == "ajustar_banco":
        return calc.mov_out(calc.add_bank_movement(s, uid, a["fecha"], a.get("horas", 0), 0, a.get("minutos", 0),
                                                   "ajuste", a.get("nota", "")))
    if name == "fijar_extras_dia":
        secs = None if a.get("quitar") else int(round(a.get("horas", 0) * 3600 + a.get("minutos", 0) * 60))
        calc.set_day_extra(s, uid, a["fecha"], secs, a.get("nota", ""))
        return {"ok": True}
    if name == "configurar":
        if "horas_diarias" in a:
            st.daily_hours = float(a["horas_diarias"])
        if "dias_laborables_mes" in a:
            st.workdays_per_month = int(a["dias_laborables_mes"])
        if "descontar_faltantes" in a:
            st.count_deficit = bool(a["descontar_faltantes"])
        s.add(st)
        s.commit()
        return {"horas_diarias": st.daily_hours, "dias_laborables_mes": st.workdays_per_month,
                "descontar_faltantes": st.count_deficit}
    if name == "crear_evento_calendar":
        return gi.create_event(s, uid, a["titulo"], a["inicio"], a.get("fin"), a.get("descripcion", ""),
                               a.get("recordatorio_minutos", 10), bool(a.get("todo_el_dia")))
    if name == "listar_eventos_calendar":
        return gi.list_events(s, uid, a.get("desde"), a.get("hasta"))
    if name == "crear_tarea":
        return gi.create_task(s, uid, a["titulo"], a.get("fecha"), a.get("notas", ""))
    return {"error": f"Herramienta desconocida: {name}"}


def _system_prompt(s: Session, u: User) -> str:
    st = get_settings(s, u.id)
    now = datetime.now(calc.tz(st))
    abierta = calc.open_shift(s, u.id)
    return (
        "Sos el asistente de una app personal de control horario y banco de horas extra. Respondé en español "
        "rioplatense, breve y claro (tus respuestas se leen en voz alta: sin tablas ni markdown). "
        f"Hablás con {u.name or u.email}. "
        f"Fecha y hora actual: {DIAS[now.weekday()]} {now.strftime('%d/%m/%Y %H:%M')} ({st.timezone}). "
        f"Jornada normal: {st.daily_hours} h; mes laboral: {st.workdays_per_month} jornadas. "
        f"Jornada en curso: {'sí, desde ' + calc.to_local(abierta.start, st).strftime('%H:%M') if abierta else 'no'}. "
        "Usá las herramientas para toda acción o consulta de datos; nunca inventes datos ni confirmes una acción "
        "que la herramienta no devolvió como exitosa. Resolvé fechas relativas (hoy, ayer, el lunes) a YYYY-MM-DD. "
        "Antes de eliminar algo pedí confirmación explícita. Si falta un dato imprescindible, preguntalo. "
        "Al informar tiempos usá horas y minutos (y días si corresponde)."
    )


def chat(s: Session, u: User, message: str, history: list[dict] | None = None) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"respuesta": "Falta configurar GEMINI_API_KEY en el servidor.", "acciones": []}
    from google import genai
    from google.genai import errors, types

    client = genai.Client(api_key=key)
    contents: list = []
    for h in (history or [])[-10:]:
        role = "model" if h.get("role") in ("assistant", "model") else "user"
        if h.get("text"):
            contents.append(types.Content(role=role, parts=[types.Part(text=h["text"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    config = types.GenerateContentConfig(
        system_instruction=_system_prompt(s, u),
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(**t) for t in TOOLS])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    acciones = []
    for _ in range(MAX_STEPS):
        try:
            resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
        except errors.APIError as e:
            friendly = _friendly(e, s, u)
            if friendly:
                raise friendly from e
            raise
        um = resp.usage_metadata
        usage.record(s, u.id, um.prompt_token_count if um else 0, um.total_token_count if um else 0)
        cand = resp.candidates[0] if resp.candidates else None
        calls = resp.function_calls or []
        if not calls:
            return {"respuesta": (resp.text or "").strip() or "No obtuve respuesta.", "acciones": acciones}
        contents.append(cand.content)  # conserva thought signatures del modelo
        parts = []
        for fc in calls:
            args = dict(fc.args or {})
            try:
                result = run_tool(s, u, fc.name, args)
                ok = not (isinstance(result, dict) and "error" in result)
            except Exception as e:  # noqa: BLE001 — el error se le devuelve al modelo
                result, ok = {"error": str(e)}, False
            acciones.append({"herramienta": fc.name, "argumentos": args, "ok": ok})
            parts.append(types.Part.from_function_response(
                name=fc.name, response={"result": json.loads(json.dumps(result, default=str))}))
        contents.append(types.Content(role="user", parts=parts))
    return {"respuesta": "La solicitud requirió demasiados pasos; probá dividirla.", "acciones": acciones}
