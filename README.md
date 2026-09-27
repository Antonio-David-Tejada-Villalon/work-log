# Control Horario · Banco de horas con asistente por voz

App web instalable en el teléfono (PWA) para registrar tu jornada laboral, calcular horas extra, manejar un banco de horas y operar todo por voz con IA. Exporta a Excel y crea eventos, recordatorios y tareas en Google.

**Multiusuario:** cada persona entra con su cuenta de Google y ve solo sus propios datos (jornadas, banco, ajustes y su Calendar/Tasks). El dueño de la app decide quién puede entrar.

**Tecnologías (todas gratuitas):** Python 3.12 · FastAPI · SQLModel (SQLite en local / Postgres de Supabase en producción) · openpyxl · Google Gemini API (capa gratuita) · Google Calendar API y Tasks API · React 18 + Vite + vite-plugin-pwa · **Bootstrap 5.3** (personalizado con Sass) + **Bootstrap Icons** · Web Speech API del navegador (voz sin costo).

**Hosting gratuito:** Vercel (app + API) + Supabase (base de datos). No se usa Render.

---

## Funciones

| Área | Qué hace |
|---|---|
| **Hoy** | Botón Iniciar/Finalizar jornada con cronómetro en vivo. Opción "Registrar con otra hora". Muestra trabajado hoy, extra hoy y saldo del banco. |
| **Historial** | Jornadas por día (fecha, entrada, salida, duración). Agregar, editar o eliminar. Varios tramos en un mismo día se suman. Turnos que cruzan medianoche se calculan bien. Tocando el indicador de extras de un día se corrigen a mano (o se vuelve al cálculo automático). |
| **Banco** | Saldo en `hh:mm:ss` y desglosado en **meses, días, horas, minutos y segundos**, de dos formas: en *jornadas laborales* (día = tu jornada configurada; mes = N jornadas) y en *tiempo reloj* (día = 24 h; mes = 30 días). Registrar uso (días/horas/minutos) o ajustes a favor o en contra; editar o eliminar movimientos. |
| **Asistente** | Hablás o escribís: "entré a las 8", "ayer salí 17:10", "¿cuántas extras tengo?", "usá 1 día del banco el viernes", "recordame mañana 10:00 llamar al proveedor", "agregá la tarea enviar informe para el lunes". Responde en voz alta. Pide confirmación antes de eliminar. La conversación se guarda en tu cuenta (últimos 100 mensajes), así es la misma en todos tus dispositivos, y se puede borrar con *Borrar conversación*. Si Google agota el límite gratuito, avisa con un mensaje claro y la hora en que se reinicia. |
| **Ajustes** | Horas por jornada (define desde cuándo hay horas extra), jornadas por mes, descontar faltantes del banco (opcional), zona horaria, cuenta y cierre de sesión, conexión con Google, invitados (solo el dueño), exportar Excel, voz del asistente (elegir voz y velocidad, con botón para probarla), tema claro/oscuro/automático. |
| **Excel** | Hojas *Jornadas*, *Resumen diario* y *Banco de horas*, con duraciones en formato `[h]:mm:ss` y totales con fórmulas `SUM`. |

**Regla de cálculo:** extra del día = máx(0, total trabajado en el día − horas de jornada). Saldo del banco = extras (o correcciones manuales) − horas usadas ± ajustes (− faltantes, si activás esa opción). El día de una jornada es la fecha local de su hora de entrada.

**Usuarios y acceso:** se entra con *Continuar con Google*; no hay contraseñas ni PIN. Solo pueden entrar el dueño (`OWNER_EMAIL`) y los correos que él invite en *Ajustes → Invitados*. Cada usuario tiene sus propias jornadas, banco de horas, ajustes y conexión con Google, y el asistente solo actúa sobre lo suyo. La sesión dura 30 días y va en una cookie segura (en la base de datos se guarda solo su hash). Si el dueño quita a alguien, se le cierra la sesión pero sus datos se conservan por si se lo vuelve a invitar.
Quien administra la base de datos (Supabase) puede ver los datos de todos: conviene avisárselo a los invitados.

---

## 1. Ejecutar en tu PC

Requisitos: Python 3.12+ y Node.js 20+. Todos los comandos se ejecutan desde la carpeta raíz del proyecto.

```bash
# Backend
python -m venv .venv
# Windows: .venv\Scripts\activate    ·   Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # (Linux/Mac: cp) y completá los valores
uvicorn index:app --reload --port 8000

# Frontend (otra terminal)
cd frontend
npm install
npm run dev -- --host          # abrí http://localhost:5173
```

`npm run build` genera `frontend/dist`, que la API sirve en `http://localhost:8000`.
El micrófono del navegador y la instalación como app requieren **HTTPS** (salvo `localhost`); en el teléfono se usan con la versión publicada en Vercel (paso 4).

Pruebas: `pip install pytest` y luego `pytest -q` (desde la raíz).

## 2. Clave gratuita de Gemini (IA)

1. Entrá a <https://aistudio.google.com/apikey> con tu cuenta de Google y creá una API key.
2. Ponela en `GEMINI_API_KEY`. El modelo se elige con `GEMINI_MODEL` (por defecto `gemini-3.5-flash-lite`, que responde en 1-3 s y alcanza para operar la app; `gemini-3.5-flash` es más capaz pero en pruebas tardó entre 10 y 30 s por respuesta).
3. Los límites de la capa gratuita los fija Google y pueden cambiar; revisalos en la página de precios de la Gemini API.
4. No hay un "saldo de tokens": Google limita las solicitudes y los tokens **por minuto** y las solicitudes **por día**, **por proyecto** (todas las personas de la app comparten el mismo tope). Los diarios se reinician a la medianoche del Pacífico de EE. UU. (las 04:00 en Argentina mientras rige el horario de verano de EE. UU., las 05:00 el resto del año). El tope real y lo que resta se ven en <https://aistudio.google.com/rate-limit>. En *Ajustes → Uso de la IA hoy* la app lleva la cuenta de lo consumido (el dueño ve el de cada persona).

## 3. Ingreso con Google, Calendar y Tasks (OAuth)

Cada persona entra con su cuenta de Google, así que este paso es **obligatorio**. Un solo permiso cubre el correo (la identidad) y el acceso a Calendar y Tasks de esa persona.

1. <https://console.cloud.google.com> → crear un proyecto.
2. *APIs y servicios → Biblioteca*: habilitá **Google Calendar API** y **Google Tasks API**.
3. *Google Auth Platform* (antes "Pantalla de consentimiento OAuth"): en *Branding* poné nombre y correo; en *Audience* elegí tipo **Externo**. Mientras la app esté en "Prueba", agregá en **Test users** el correo del dueño y el de cada invitado (hasta 100).
   Para pasar a **En producción** (sin lista de probadores ni vencimiento semanal), Google exige completar en *Branding* la **Application home page** (la URL de la app) y la **Application privacy policy link** (`https://TU-PROYECTO.vercel.app/privacidad.html`, una página que ya trae la app).
4. *Clients → Create client → Aplicación web*. En **URI de redirección autorizados** agregá (dejá vacío *Authorized JavaScript origins*):
   - local: `http://localhost:8000/api/google/callback`
   - producción: `https://TU-PROYECTO.vercel.app/api/google/callback`
5. Copiá el ID y el secreto en `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`, la URI en `GOOGLE_REDIRECT_URI`, tu correo de Google en `OWNER_EMAIL` y en `FRONTEND_URL` la dirección de la app (en local `http://localhost:8000`, o `http://localhost:5173` si usás Vite; en producción, la URL de Vercel).
6. Abrí la app, tocá *Continuar con Google* y después, en *Ajustes → Invitados*, agregá los correos de quienes pueden entrar.

> Cada persona verá "Google no verificó esta app": es normal, con menos de 100 usuarios no hace falta verificarla (*Avanzado → Ir a … (no seguro)*). Con la app en estado "Prueba" Google vence el permiso de Calendar a los 7 días y hay que volver a entrar; para evitarlo pasá la app a *En producción* en *Audience*.

## 4. Publicar gratis en Vercel + Supabase

**Base de datos (Supabase, plan Free):**
1. Creá un proyecto en <https://supabase.com>.
2. Botón **Connect** → copiá la cadena del **Transaction pooler** (puerto `6543`), recomendada para funciones serverless, y reemplazá `[YOUR-PASSWORD]` por la contraseña del proyecto.
3. Esa cadena va en `DATABASE_URL`. Las tablas se crean solas en el primer arranque.
   Si venías de la versión de un solo usuario, sus tablas (`shift`, `settings`, `dayoverride`, `bankmovement`, `googletoken`, `apppin`) quedan sin usar y se pueden borrar cuando quieras: `drop table if exists shift, settings, dayoverride, bankmovement, googletoken, apppin;`.
   En Vercel `DATABASE_URL` es obligatoria: sin ella la app no arranca (el disco de Vercel no es persistente).

**App + API (Vercel, plan Hobby, gratis para uso personal y no comercial):**
1. Subí esta carpeta a un repositorio de GitHub (el `.gitignore` ya excluye `.env`, `node_modules` y `dist`).
2. En <https://vercel.com> → *Add New → Project* → importá el repo. Vercel detecta FastAPI en `index.py`; `vercel.json` compila el frontend (`npm ci && npm run build`) y le da hasta 60 s al asistente.
3. *Settings → Environment Variables*: `OWNER_EMAIL`, `DATABASE_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `TIMEZONE`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI=https://TU-PROYECTO.vercel.app/api/google/callback` y `FRONTEND_URL=https://TU-PROYECTO.vercel.app`.
4. *Deploy*. Cada `git push` vuelve a publicar. Abrí la URL y entrá con Google usando el correo de `OWNER_EMAIL`; después invitá a los demás en *Ajustes → Invitados*.

**Instalar en el teléfono:** abrí la URL en Chrome (Android) → menú ⋮ → *Instalar app / Agregar a la pantalla principal*. En iPhone: Safari → Compartir → *Agregar a inicio* (si el reconocimiento de voz no está disponible en tu versión de iOS, podés escribir o usar el dictado del teclado).

## 5. Imágenes opcionales

La app funciona sin imágenes. Si generás las tuyas, guardalas con estos nombres y volvé a compilar/publicar:

| Archivo | Tamaño | Uso |
|---|---|---|
| `frontend/public/icon-512.png` | 512×512 PNG | Ícono de la app instalada (con margen de seguridad para recorte circular) |
| `frontend/public/icon-192.png` | 192×192 PNG | Ícono chico y logo del encabezado (reducción del de 512) |
| `frontend/public/img/empty-history.webp` | ~600×600 WEBP, fondo transparente | Historial sin jornadas |
| `frontend/public/img/assistant.webp` | ~600×600 WEBP, fondo transparente | Pantalla inicial del asistente |

---

## Estructura

```
backend/
  app/db.py                 modelos y conexión (User, AllowedEmail, LoginSession, Settings, Shift, DayOverride, BankMovement, GoogleToken)
  app/auth.py               sesiones por cookie, dueño e invitados
  app/calc.py               cálculos: jornadas, extras, banco, desgloses
  app/excel.py              exportación .xlsx
  app/assistant.py          asistente Gemini con function calling (15 herramientas)
  app/history.py            conversación con el asistente guardada por usuario
  app/usage.py              contador de uso de la IA (solicitudes y tokens por usuario y por día)
  app/google_integration.py ingreso con Google (OAuth) + Calendar + Tasks
  app/main.py               API REST y servidor del frontend
  tests/test_app.py         pruebas
frontend/
  src/App.jsx               pantallas Hoy, Historial, Banco, Asistente, Ajustes
  src/voice.js              voz (Web Speech API)
  src/custom.scss           Bootstrap 5.3 con los tokens del Design System
  src/app.css               tokens extra y ajustes de tema oscuro
  src/theme.js              tema claro/oscuro/automático
  public/privacidad.html    política de privacidad (Google la exige para publicar la app)
index.py (entrada Vercel) · vercel.json · pyproject.toml · requirements.txt
```

## API (resumen)

`GET /api/status` · `POST /api/clock-in` · `POST /api/clock-out` · `GET|POST /api/shifts` · `PUT|DELETE /api/shifts/{id}` · `GET /api/summary?desde&hasta` · `PUT /api/days/{fecha}/extra` · `GET|POST /api/bank` · `PUT|DELETE /api/bank/{id}` · `GET|PUT /api/settings` · `GET /api/export.xlsx?desde&hasta` · `POST /api/assistant` · `GET|DELETE /api/assistant/history` · `GET /api/ai-usage` · `POST /api/google/disconnect`.
Ingreso: `GET /api/auth/google/start` · `GET /api/google/callback` · `POST /api/auth/logout`. Invitados (solo el dueño): `GET|POST /api/admin/invitados` · `DELETE /api/admin/invitados/{correo}`.
Todas (menos health y las de ingreso) requieren la cookie de sesión y devuelven solo los datos del usuario. Documentación interactiva en `/docs`.
