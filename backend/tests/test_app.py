import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["APP_PIN"] = "9999"

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from io import BytesIO  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app import calc, security  # noqa: E402

H = {"X-App-Pin": "9999"}


def test_flow():
    with TestClient(app) as c:
        assert c.get("/api/status").status_code == 401
        # 8 h de jornada; día con 9h30 → 1h30 extra
        r = c.post("/api/shifts", json={"fecha": "2026-09-21", "inicio": "08:00", "fin": "17:30", "nota": "a"}, headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["duracion"] == "09:30:00"
        assert r.json()["inicio"].endswith("-03:00")
        # dos tramos el mismo día: 5h + 4h = 9h → 1h extra
        c.post("/api/shifts", json={"fecha": "2026-09-22", "inicio": "08:00", "fin": "13:00"}, headers=H)
        sid = c.post("/api/shifts", json={"fecha": "2026-09-22", "inicio": "14:00", "fin": "18:00"}, headers=H).json()["id"]
        # turno nocturno que cruza medianoche: 22:00 → 06:00 = 8h, 0 extra
        c.post("/api/shifts", json={"fecha": "2026-09-23", "inicio": "22:00", "fin": "06:00"}, headers=H)
        s = c.get("/api/summary", headers=H).json()
        days = {d["fecha"]: d for d in s["dias"]}
        assert days["2026-09-21"]["extra"] == "01:30:00"
        assert days["2026-09-22"]["extra"] == "01:00:00"
        assert days["2026-09-23"]["trabajado"] == "08:00:00"
        b = c.get("/api/bank", headers=H).json()
        assert b["saldo"] == "02:30:00"
        # modificar: salida 19:00 → segundo tramo 5h → 2h extra ese día
        c.put(f"/api/shifts/{sid}", json={"fin": "19:00"}, headers=H)
        assert c.get("/api/bank", headers=H).json()["saldo"] == "03:30:00"
        # corrección manual de extras del 21 a 0h45
        c.put("/api/days/2026-09-21/extra", json={"horas": 0, "minutos": 45}, headers=H)
        assert c.get("/api/bank", headers=H).json()["saldo"] == "02:45:00"
        # usar 2 h del banco
        m = c.post("/api/bank", json={"fecha": "2026-09-25", "horas": 2, "nota": "trámite"}, headers=H).json()
        assert m["segundos"] == -7200
        b = c.get("/api/bank", headers=H).json()
        assert b["saldo"] == "00:45:00"
        assert b["desglose"]["laboral"]["minutos"] == 45
        # usar 1 día (8 h) → saldo negativo
        c.post("/api/bank", json={"fecha": "2026-09-26", "dias": 1}, headers=H)
        b = c.get("/api/bank", headers=H).json()
        assert b["saldo"] == "-07:15:00" and b["desglose"]["laboral"]["signo"] == -1
        # fichar entrada/salida
        assert c.post("/api/clock-in", json={"hora": "2026-09-24T09:00"}, headers=H).status_code == 200
        assert c.post("/api/clock-in", json={}, headers=H).status_code == 400
        r = c.post("/api/clock-out", json={"hora": "12:00"}, headers=H)
        assert r.status_code == 200 and r.json()["duracion"] == "03:00:00"
        # excel
        x = c.get("/api/export.xlsx", headers=H)
        assert x.status_code == 200
        wb = load_workbook(BytesIO(x.content))
        assert wb.sheetnames == ["Jornadas", "Resumen diario", "Banco de horas"]
        # ajustes
        assert c.put("/api/settings", json={"daily_hours": 7}, headers=H).json()["daily_hours"] == 7
        assert c.put("/api/settings", json={"timezone": "Nope/X"}, headers=H).status_code == 400


def test_pin_created_in_app(monkeypatch):
    """Caso normal: sin APP_PIN el PIN se crea desde la app, se puede cambiar y frena la fuerza bruta."""
    from datetime import timedelta
    from sqlmodel import Session
    from backend.app.db import AppPin, engine, init_db, utcnow

    monkeypatch.delenv("APP_PIN")
    with TestClient(app) as c:
        init_db()

        def wipe():
            with Session(engine) as s:
                if row := s.get(AppPin, 1):
                    s.delete(row)
                    s.commit()

        def get(pin):
            return c.get("/api/status", headers={"X-App-Pin": pin}).status_code

        wipe()
        assert c.get("/api/pin/status").json() == {"configurado": False}
        assert c.get("/api/status").status_code == 401                            # sin PIN no se abre la app
        assert c.post("/api/pin/setup", json={"pin": "12"}).status_code == 400    # muy corto
        assert c.post("/api/pin/setup", json={"pin": "clave-ñ"}).status_code == 400  # no ASCII
        assert c.post("/api/pin/setup", json={"pin": "4321"}).status_code == 200
        assert c.post("/api/pin/setup", json={"pin": "9999"}).status_code == 409  # ya existe
        assert c.get("/api/pin/status").json() == {"configurado": True}
        assert get("4321") == 200 and get("0000") == 401
        # se guarda con hash, nunca en claro
        with Session(engine) as s:
            row = s.get(AppPin, 1)
            assert row.digest and "4321" not in (row.digest + row.salt)
        # cambiar el PIN
        assert c.post("/api/pin/change", json={"actual": "0000", "nuevo": "5555"}).status_code == 401
        assert c.post("/api/pin/change", json={"actual": "4321", "nuevo": "5555"}).status_code == 200
        assert get("4321") == 401 and get("5555") == 200
        # bloqueo tras varios intentos fallidos seguidos, aunque el PIN correcto llegue después
        for _ in range(security.MAX_FAILS):
            get("mal1")
        assert get("5555") == 429
        with Session(engine) as s:  # vence el bloqueo
            row = s.get(AppPin, 1)
            row.locked_until = utcnow() - timedelta(seconds=1)
            s.add(row)
            s.commit()
        assert get("5555") == 200
        wipe()


def test_env_pin_is_backup(monkeypatch):
    """APP_PIN (opcional) funciona como PIN de respaldo aunque exista uno creado en la app."""
    monkeypatch.setenv("APP_PIN", "9999")
    with TestClient(app) as c:
        assert c.get("/api/pin/status").json() == {"configurado": True}
        assert c.post("/api/pin/setup", json={"pin": "1111"}).status_code == 409
        assert c.post("/api/pin/change", json={"actual": "9999", "nuevo": "7777"}).status_code == 200
        assert c.get("/api/status", headers={"X-App-Pin": "7777"}).status_code == 200
        assert c.get("/api/status", headers={"X-App-Pin": "9999"}).status_code == 200  # respaldo
        from sqlmodel import Session
        from backend.app.db import AppPin, engine
        with Session(engine) as s:
            s.delete(s.get(AppPin, 1))
            s.commit()


def test_dependencies_in_sync():
    """Vercel instala desde pyproject.toml y en local se usa requirements.txt: deben listar lo mismo."""
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    in_pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    in_requirements = [ln.strip() for ln in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
                       if ln.strip() and not ln.startswith("#")]
    assert sorted(in_pyproject) == sorted(in_requirements)


def test_breakdown():
    class St:  # jornada 8 h, mes 22 jornadas
        daily_hours, workdays_per_month = 8, 22
    secs = 23 * 8 * 3600 + 3 * 3600 + 5 * 60 + 7  # 23 jornadas + 3h 5m 7s
    lab = calc.bank_breakdowns(secs, St)["laboral"]
    assert (lab["meses"], lab["dias"], lab["horas"], lab["minutos"], lab["segundos"]) == (1, 1, 3, 5, 7)
    rel = calc.bank_breakdowns(90061, St)["reloj"]  # 1 día 1 h 1 min 1 s
    assert (rel["meses"], rel["dias"], rel["horas"], rel["minutos"], rel["segundos"]) == (0, 1, 1, 1, 1)


def test_parse_time_without_leading_zero():
    from datetime import date

    class St:
        timezone = "America/Argentina/San_Juan"  # UTC-3
    for txt in ("7:45", "07:45", "7:45:00"):
        assert calc.parse_dt(txt, St, date(2026, 9, 25)).isoformat() == "2026-09-25T10:45:00"


def test_assistant_tools():
    from google.genai import types
    from sqlmodel import Session
    from backend.app import assistant
    from backend.app.db import engine, init_db
    for t in assistant.TOOLS:
        types.FunctionDeclaration(**t)
    init_db()
    with Session(engine) as s:
        r = assistant.run_tool(s, "registrar_jornada", {"fecha": "2026-08-03", "inicio": "08:00", "fin": "18:00"})
        assert r["duracion"] == "10:00:00"
        assistant.run_tool(s, "fijar_extras_dia", {"fecha": "2026-08-03", "horas": 1, "minutos": 30})
        d = assistant.run_tool(s, "resumen", {"desde": "2026-08-03", "hasta": "2026-08-03"})
        assert d["dias"][0]["extra"] == "01:30:00"
        assert "error" in assistant.run_tool(s, "eliminar_jornada", {"id": r["id"], "confirmado": False})
        assert assistant.run_tool(s, "eliminar_jornada", {"id": r["id"], "confirmado": True}) == {"ok": True}
        assert "desglose" in assistant.run_tool(s, "consultar_banco", {})
        assert assistant._system_prompt(s).startswith("Sos el asistente")


def test_chat_loop(monkeypatch):
    """Simula a Gemini: primero pide una herramienta y luego responde texto."""
    from google import genai
    from google.genai import types
    from sqlmodel import Session
    from backend.app import assistant
    from backend.app.db import engine

    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(contents)
            if len(calls) == 1:
                return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
                    role="model", parts=[types.Part(function_call=types.FunctionCall(name="consultar_banco", args={}))]))])
            assert contents[-1].parts[0].function_response.name == "consultar_banco"
            return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
                role="model", parts=[types.Part(text="Tenés saldo.")]))])

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(genai, "Client", FakeClient)
    with Session(engine) as s:
        out = assistant.chat(s, "¿cuánto tengo en el banco?", [{"role": "assistant", "text": "hola"}])
    assert out["respuesta"] == "Tenés saldo." and out["acciones"][0]["ok"]
