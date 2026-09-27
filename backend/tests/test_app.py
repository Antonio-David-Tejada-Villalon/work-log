import json
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["OWNER_EMAIL"] = "dueno@example.com"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from io import BytesIO  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from backend.app import auth, calc  # noqa: E402
from backend.app import google_integration as gi  # noqa: E402
from backend.app.db import (AllowedEmail, BankMovement, DayOverride, GoogleToken, LoginSession, OAuthState,  # noqa: E402
                            Settings, Shift, User, engine, init_db, utcnow)
from backend.app.main import app  # noqa: E402

OWNER = "dueno@example.com"
FRIEND = "amigo@example.com"


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with Session(engine) as s:
        for model in (GoogleToken, DayOverride, BankMovement, Shift, Settings, LoginSession, OAuthState,
                      AllowedEmail, User):
            for row in s.exec(select(model)).all():
                s.delete(row)
        s.commit()
    yield


def make_user(email: str, name: str = "Test") -> tuple[int, str]:
    """Crea el usuario (si no existe) con una sesión iniciada. Devuelve (id, token de la cookie)."""
    with Session(engine) as s:
        u = s.exec(select(User).where(User.email == email)).first() or User(email=email, name=name)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id, auth.create_session(s, u.id)


def client(email: str | None = None) -> TestClient:
    c = TestClient(app)
    if email:
        c.cookies.set(auth.COOKIE, make_user(email)[1])
    return c


def invite(email: str) -> None:
    with Session(engine) as s:
        auth.invite(s, email)


# ---------------------------------------------------------------- acceso
def test_requires_login():
    c = client()
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/shifts").status_code == 401
    assert c.post("/api/clock-in", json={}).status_code == 401
    assert c.get("/api/admin/invitados").status_code == 401
    c.cookies.set(auth.COOKIE, "token-inventado")
    assert c.get("/api/status").status_code == 401


def test_session_token_is_stored_hashed_and_expires():
    uid, token = make_user(OWNER)
    with Session(engine) as s:
        rows = s.exec(select(LoginSession)).all()
        assert len(rows) == 1 and rows[0].token_hash != token and token not in rows[0].token_hash
    c = client()
    c.cookies.set(auth.COOKIE, token)
    assert c.get("/api/status").status_code == 200
    with Session(engine) as s:  # vence la sesión
        row = s.exec(select(LoginSession)).first()
        row.expires_at = utcnow() - auth.timedelta(seconds=1)
        s.add(row)
        s.commit()
    assert c.get("/api/status").status_code == 401


def test_uninvited_user_is_rejected():
    _, token = make_user("intruso@example.com")  # existe y tiene sesión, pero no está invitado
    c = client()
    c.cookies.set(auth.COOKIE, token)
    assert c.get("/api/status").status_code == 401


def test_logout_closes_session():
    c = client(OWNER)
    assert c.get("/api/status").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    with Session(engine) as s:
        assert s.exec(select(LoginSession)).all() == []
    assert c.get("/api/status").status_code == 401


# ---------------------------------------------------------------- flujo de la app (con el dueño)
def test_flow():
    c = client(OWNER)
    assert c.get("/api/status").json()["usuario"]["es_dueno"] is True
    # 8 h de jornada; día con 9h30 → 1h30 extra
    r = c.post("/api/shifts", json={"fecha": "2026-09-21", "inicio": "08:00", "fin": "17:30", "nota": "a"})
    assert r.status_code == 200, r.text
    assert r.json()["duracion"] == "09:30:00"
    assert r.json()["inicio"].endswith("-03:00")
    # dos tramos el mismo día: 5h + 4h = 9h → 1h extra
    c.post("/api/shifts", json={"fecha": "2026-09-22", "inicio": "08:00", "fin": "13:00"})
    sid = c.post("/api/shifts", json={"fecha": "2026-09-22", "inicio": "14:00", "fin": "18:00"}).json()["id"]
    # turno nocturno que cruza medianoche: 22:00 → 06:00 = 8h, 0 extra
    c.post("/api/shifts", json={"fecha": "2026-09-23", "inicio": "22:00", "fin": "06:00"})
    s = c.get("/api/summary").json()
    days = {d["fecha"]: d for d in s["dias"]}
    assert days["2026-09-21"]["extra"] == "01:30:00"
    assert days["2026-09-22"]["extra"] == "01:00:00"
    assert days["2026-09-23"]["trabajado"] == "08:00:00"
    b = c.get("/api/bank").json()
    assert b["saldo"] == "02:30:00"
    # modificar: salida 19:00 → segundo tramo 5h → 2h extra ese día
    c.put(f"/api/shifts/{sid}", json={"fin": "19:00"})
    assert c.get("/api/bank").json()["saldo"] == "03:30:00"
    # corrección manual de extras del 21 a 0h45
    c.put("/api/days/2026-09-21/extra", json={"horas": 0, "minutos": 45})
    assert c.get("/api/bank").json()["saldo"] == "02:45:00"
    # usar 2 h del banco
    m = c.post("/api/bank", json={"fecha": "2026-09-25", "horas": 2, "nota": "trámite"}).json()
    assert m["segundos"] == -7200
    b = c.get("/api/bank").json()
    assert b["saldo"] == "00:45:00"
    assert b["desglose"]["laboral"]["minutos"] == 45
    # usar 1 día (8 h) → saldo negativo
    c.post("/api/bank", json={"fecha": "2026-09-26", "dias": 1})
    b = c.get("/api/bank").json()
    assert b["saldo"] == "-07:15:00" and b["desglose"]["laboral"]["signo"] == -1
    # fichar entrada/salida
    assert c.post("/api/clock-in", json={"hora": "2026-09-24T09:00"}).status_code == 200
    assert c.post("/api/clock-in", json={}).status_code == 400
    r = c.post("/api/clock-out", json={"hora": "12:00"})
    assert r.status_code == 200 and r.json()["duracion"] == "03:00:00"
    # excel
    x = c.get("/api/export.xlsx")
    assert x.status_code == 200
    wb = load_workbook(BytesIO(x.content))
    assert wb.sheetnames == ["Jornadas", "Resumen diario", "Banco de horas"]
    # ajustes
    assert c.put("/api/settings", json={"daily_hours": 7}).json()["daily_hours"] == 7
    assert c.put("/api/settings", json={"timezone": "Nope/X"}).status_code == 400


# ---------------------------------------------------------------- cada usuario ve solo lo suyo
def test_data_is_isolated_between_users():
    invite(FRIEND)
    boss, friend = client(OWNER), client(FRIEND)
    sid = boss.post("/api/shifts", json={"fecha": "2026-09-21", "inicio": "08:00", "fin": "17:30"}).json()["id"]
    mid = boss.post("/api/bank", json={"fecha": "2026-09-25", "horas": 1}).json()["id"]
    boss.put("/api/days/2026-09-21/extra", json={"horas": 3})
    boss.put("/api/settings", json={"daily_hours": 6})

    # el amigo no ve nada de lo del dueño
    assert friend.get("/api/shifts").json() == []
    assert friend.get("/api/summary").json()["dias"] == []
    assert friend.get("/api/bank").json()["saldo"] == "00:00:00"
    assert friend.get("/api/settings").json()["daily_hours"] == 8  # sus ajustes por defecto, no los del dueño
    # ni puede tocarlo aunque conozca los ids
    assert friend.put(f"/api/shifts/{sid}", json={"fin": "23:00"}).status_code == 400
    assert friend.delete(f"/api/shifts/{sid}").status_code == 400
    assert friend.put(f"/api/bank/{mid}", json={"horas": 9}).status_code == 400
    assert friend.delete(f"/api/bank/{mid}").status_code == 400
    # lo del dueño sigue intacto
    assert boss.get("/api/shifts").json()[0]["duracion"] == "09:30:00"
    assert boss.get("/api/bank").json()["movimientos"][0]["segundos"] == -3600

    # el mismo día puede tener corrección para cada uno
    friend.put("/api/days/2026-09-21/extra", json={"horas": 1})
    assert [d["extra"] for d in boss.get("/api/summary").json()["dias"]] == ["03:00:00"]
    assert [d["extra"] for d in friend.get("/api/summary").json()["dias"]] == ["01:00:00"]
    # cada uno puede tener su propia jornada abierta
    assert boss.post("/api/clock-in", json={"hora": "2026-09-24T09:00"}).status_code == 200
    assert friend.post("/api/clock-in", json={"hora": "2026-09-24T10:00"}).status_code == 200
    # el Excel de cada uno solo trae lo suyo
    rows = lambda c: load_workbook(BytesIO(c.get("/api/export.xlsx").content))["Jornadas"].max_row  # noqa: E731
    assert rows(boss) == 4 and rows(friend) == 3  # encabezado + jornadas + fila de total


# ---------------------------------------------------------------- invitados
def test_owner_manages_invited():
    boss, friend = client(OWNER), client(FRIEND)
    assert boss.get("/api/admin/invitados").json() == []
    assert boss.post("/api/admin/invitados", json={"email": "no-es-correo"}).status_code == 400
    assert boss.post("/api/admin/invitados", json={"email": OWNER}).status_code == 400  # ya tiene acceso
    r = boss.post("/api/admin/invitados", json={"email": "  Amigo@Example.com "})
    assert r.status_code == 200 and [i["email"] for i in r.json()] == [FRIEND]
    # solo el dueño administra
    assert friend.get("/api/admin/invitados").status_code == 403
    assert friend.post("/api/admin/invitados", json={"email": "otro@example.com"}).status_code == 403
    assert friend.get("/api/status").json()["usuario"]["es_dueno"] is False
    # al quitarlo se cierra su sesión, pero sus datos se conservan
    friend.post("/api/shifts", json={"fecha": "2026-09-21", "inicio": "08:00", "fin": "09:00"})
    assert boss.delete(f"/api/admin/invitados/{FRIEND}").json() == []
    assert friend.get("/api/status").status_code == 401
    boss.post("/api/admin/invitados", json={"email": FRIEND})
    assert len(client(FRIEND).get("/api/shifts").json()) == 1


# ---------------------------------------------------------------- ingreso con Google
class FakeCreds:
    id_token = "id-token-falso"

    def to_json(self):
        return json.dumps({"token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                           "token_uri": "https://oauth2.googleapis.com/token"})


class FakeFlow:
    code_verifier = None
    credentials = FakeCreds()

    def fetch_token(self, code):
        assert code == "codigo"


def google_setup(monkeypatch, email: str):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secreto")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/api/google/callback")
    monkeypatch.setattr(gi, "_verify_id_token",
                        lambda t: {"email": email, "email_verified": True, "name": "Ana", "picture": "http://x/a.png"})


def start_login(c: TestClient) -> str:
    r = c.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"].startswith("https://accounts.google.com/")
    with Session(engine) as s:
        return s.exec(select(OAuthState)).one().state


def test_google_login_creates_session(monkeypatch):
    google_setup(monkeypatch, OWNER)
    c = client()
    state = start_login(c)
    monkeypatch.setattr(gi, "_flow", lambda state=None: FakeFlow())
    r = c.get("/api/google/callback", params={"code": "codigo", "state": state}, follow_redirects=False)
    assert r.headers["location"].endswith("?login=ok")
    assert auth.COOKIE in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    me = c.get("/api/status").json()
    assert me["usuario"]["email"] == OWNER and me["usuario"]["nombre"] == "Ana" and me["google"]["conectado"] is True
    with Session(engine) as s:
        assert s.exec(select(OAuthState)).all() == []  # el estado se usa una sola vez
        assert json.loads(s.exec(select(GoogleToken)).one().credentials_json)["refresh_token"] == "r"
    # el estado usado no sirve de nuevo
    r = c.get("/api/google/callback", params={"code": "codigo", "state": state}, follow_redirects=False)
    assert r.headers["location"].endswith("?login=error")


def test_google_login_denied_for_uninvited(monkeypatch):
    google_setup(monkeypatch, "intruso@example.com")
    c = client()
    state = start_login(c)
    monkeypatch.setattr(gi, "_flow", lambda state=None: FakeFlow())
    r = c.get("/api/google/callback", params={"code": "codigo", "state": state}, follow_redirects=False)
    assert r.headers["location"].endswith("?login=denied") and "set-cookie" not in r.headers
    with Session(engine) as s:  # no se crea el usuario ni se guardan sus permisos
        assert s.exec(select(User)).all() == [] and s.exec(select(GoogleToken)).all() == []
    assert c.get("/api/status").status_code == 401


def test_google_login_invited_and_bad_state(monkeypatch):
    google_setup(monkeypatch, FRIEND)
    invite(FRIEND)
    c = client()
    monkeypatch.setattr(gi, "_flow", lambda state=None: FakeFlow())
    r = c.get("/api/google/callback", params={"code": "codigo", "state": "inventado"}, follow_redirects=False)
    assert r.headers["location"].endswith("?login=error")
    monkeypatch.undo()
    google_setup(monkeypatch, FRIEND)
    state = start_login(c)
    monkeypatch.setattr(gi, "_flow", lambda state=None: FakeFlow())
    r = c.get("/api/google/callback", params={"code": "codigo", "state": state}, follow_redirects=False)
    assert r.headers["location"].endswith("?login=ok")
    assert c.get("/api/status").json()["usuario"]["email"] == FRIEND


def test_google_start_without_config_redirects_with_notice(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    r = client().get("/api/auth/google/start", follow_redirects=False)
    assert r.headers["location"].endswith("?login=config")


def test_google_disconnect_only_affects_the_user(monkeypatch):
    invite(FRIEND)
    for email in (OWNER, FRIEND):
        uid, _ = make_user(email)
        with Session(engine) as s:
            s.add(GoogleToken(user_id=uid, credentials_json='{"token": "t"}'))
            s.commit()
    monkeypatch.setattr("requests.post", lambda *a, **k: None)  # no llama a Google
    boss, friend = client(OWNER), client(FRIEND)
    assert boss.post("/api/google/disconnect").status_code == 200
    assert boss.get("/api/status").json()["google"]["conectado"] is False
    assert friend.get("/api/status").json()["google"]["conectado"] is True


# ---------------------------------------------------------------- lógica
def test_parse_time_without_leading_zero():
    from datetime import date

    class St:
        timezone = "America/Argentina/San_Juan"  # UTC-3
    for txt in ("7:45", "07:45", "7:45:00"):
        assert calc.parse_dt(txt, St, date(2026, 9, 25)).isoformat() == "2026-09-25T10:45:00"


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


# ---------------------------------------------------------------- asistente
def test_assistant_tools():
    from google.genai import types
    from backend.app import assistant
    for t in assistant.TOOLS:
        types.FunctionDeclaration(**t)
    uid, _ = make_user(OWNER, "Ana")
    other, _ = make_user(FRIEND)
    with Session(engine) as s:
        u, o = s.get(User, uid), s.get(User, other)
        r = assistant.run_tool(s, u, "registrar_jornada", {"fecha": "2026-08-03", "inicio": "08:00", "fin": "18:00"})
        assert r["duracion"] == "10:00:00"
        assistant.run_tool(s, u, "fijar_extras_dia", {"fecha": "2026-08-03", "horas": 1, "minutos": 30})
        d = assistant.run_tool(s, u, "resumen", {"desde": "2026-08-03", "hasta": "2026-08-03"})
        assert d["dias"][0]["extra"] == "01:30:00"
        # otro usuario no ve ni puede borrar esa jornada
        assert assistant.run_tool(s, o, "listar_jornadas", {}) == []
        with pytest.raises(ValueError):
            assistant.run_tool(s, o, "eliminar_jornada", {"id": r["id"], "confirmado": True})
        assert "error" in assistant.run_tool(s, u, "eliminar_jornada", {"id": r["id"], "confirmado": False})
        assert assistant.run_tool(s, u, "eliminar_jornada", {"id": r["id"], "confirmado": True}) == {"ok": True}
        assert "desglose" in assistant.run_tool(s, u, "consultar_banco", {})
        assert assistant._system_prompt(s, u).startswith("Sos el asistente") and "Ana" in assistant._system_prompt(s, u)


def test_chat_loop(monkeypatch):
    """Simula a Gemini: primero pide una herramienta y luego responde texto."""
    from google import genai
    from google.genai import types
    from backend.app import assistant

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
    uid, _ = make_user(OWNER)
    with Session(engine) as s:
        out = assistant.chat(s, s.get(User, uid), "¿cuánto tengo en el banco?", [{"role": "assistant", "text": "hola"}])
    assert out["respuesta"] == "Tenés saldo." and out["acciones"][0]["ok"]
