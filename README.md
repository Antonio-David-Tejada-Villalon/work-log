# Control Horario · Banco de horas con asistente por voz

App web instalable en el teléfono (PWA) para registrar tu jornada laboral, calcular horas extra, manejar un banco de horas y operar todo por voz con IA. Exporta a Excel y crea eventos, recordatorios y tareas en Google.

**Tecnologías (todas gratuitas):** Python 3.12 · FastAPI · SQLModel (SQLite en local / Postgres de Supabase en producción) · openpyxl · Google Gemini API (capa gratuita) · Google Calendar API y Tasks API · React 18 + Vite + vite-plugin-pwa · **Bootstrap 5.3** (personalizado con Sass) + **Bootstrap Icons** · Web Speech API del navegador (voz sin costo).

**Hosting gratuito:** Vercel (app + API) + Supabase (base de datos). No se usa Render.

---

## Funciones

| Área | Qué hace |
|---|---|
| **Hoy** | Botón Iniciar/Finalizar jornada con cronómetro en vivo. Opción "Registrar con otra hora". Muestra trabajado hoy, extra hoy y saldo del banco. |
| **Historial** | Jornadas por día (fecha, entrada, salida, duración). Agregar, editar o eliminar. Varios tramos en un mismo día se suman. Turnos que cruzan medianoche se calculan bien. Tocando el indicador de extras de un día se corrigen a mano (o se vuelve al cálculo automático). |
| **Banco** | Saldo en `hh:mm:ss` y desglosado en **meses, días, horas, minutos y segundos**, de dos formas: en *jornadas laborales* (día = tu jornada configurada; mes = N jornadas) y en *tiempo reloj* (día = 24 h; mes = 30 días). Registrar uso (días/horas/minutos) o ajustes a favor o en contra; editar o eliminar movimientos. |
| **Asistente** | Hablás o escribís: "entré a las 8", "ayer salí 17:10", "¿cuántas extras tengo?", "usá 1 día del banco el viernes", "recordame mañana 10:00 llamar al proveedor", "agregá la tarea enviar informe para el lunes". Responde en voz alta. Pide confirmación antes de eliminar. |
| **Ajustes** | Horas por jornada (define desde cuándo hay horas extra), jornadas por mes, descontar faltantes del banco (opcional), zona horaria, conexión con Google, exportar Excel, voz del asistente (elegir voz y velocidad, con botón para probarla), tema claro/oscuro/automático, cambiar el PIN de acceso. |
| **Excel** | Hojas *Jornadas*, *Resumen diario* y *Banco de horas*, con duraciones en formato `[h]:mm:ss` y totales con fórmulas `SUM`. |

**Regla de cálculo:** extra del día = máx(0, total trabajado en el día − horas de jornada). Saldo del banco = extras (o correcciones manuales) − horas usadas ± ajustes (− faltantes, si activás esa opción). El día de una jornada es la fecha local de su hora de entrada.

**Acceso con PIN:** la primera vez que abrís la app te pide crear un PIN (mínimo 4 caracteres, letras y números). Se guarda en la base de datos con hash y sal, nunca en texto plano, y hasta que lo creás la API no responde datos. Podés cambiarlo en *Ajustes → Cambiar PIN de acceso*. Tras 5 intentos fallidos seguidos la app se bloquea 1 minuto.
Si lo olvidás, se restablece desde el servidor: en Supabase (*SQL Editor*) ejecutá `delete from apppin;` y la app te pedirá crear uno nuevo (en local: `python -c "import sqlite3; c = sqlite3.connect('data/horas.db'); c.execute('delete from apppin'); c.commit()"`). También podés definir la variable `APP_PIN` con un PIN temporal: funciona como PIN de respaldo, entrás con él y lo cambiás en Ajustes (después quitá la variable).

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

## 3. Conectar Google Calendar y Tasks (OAuth)

1. <https://console.cloud.google.com> → crear un proyecto.
2. *APIs y servicios → Biblioteca*: habilitá **Google Calendar API** y **Google Tasks API**.
3. *Pantalla de consentimiento OAuth*: tipo **Externo**, completá nombre y correo, y agregá tu cuenta como **usuario de prueba**.
4. *Credenciales → Crear credenciales → ID de cliente OAuth → Aplicación web*. En **URI de redirección autorizados** agregá:
   - local: `http://localhost:8000/api/google/callback`
   - producción: `https://TU-PROYECTO.vercel.app/api/google/callback`
5. Copiá el ID y el secreto en `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, y la URI en `GOOGLE_REDIRECT_URI`. `FRONTEND_URL` es la dirección de la app (en local con Vite: `http://localhost:5173`; en producción: la URL de Vercel).
6. En la app: *Ajustes → Conectar con Google*.

> Con la app en estado "Prueba" Google puede vencer la autorización cada cierto tiempo (suele ser a los 7 días); si pasa, reconectá desde Ajustes o publicá la app en la pantalla de consentimiento (para uso personal podés continuar ante el aviso de app no verificada).

## 4. Publicar gratis en Vercel + Supabase

**Base de datos (Supabase, plan Free):**
1. Creá un proyecto en <https://supabase.com>.
2. Botón **Connect** → copiá la cadena del **Transaction pooler** (puerto `6543`), recomendada para funciones serverless, y reemplazá `[YOUR-PASSWORD]` por la contraseña del proyecto.
3. Esa cadena va en `DATABASE_URL`. Las tablas se crean solas en el primer arranque.
   En Vercel `DATABASE_URL` es obligatoria: sin ella la app no arranca (el disco de Vercel no es persistente).

**App + API (Vercel, plan Hobby, gratis para uso personal):**
1. Subí esta carpeta a un repositorio de GitHub (el `.gitignore` ya excluye `.env`, `node_modules` y `dist`).
2. En <https://vercel.com> → *Add New → Project* → importá el repo. Vercel detecta FastAPI en `index.py`; `vercel.json` compila el frontend (`npm ci && npm run build`) y le da hasta 60 s al asistente.
3. *Settings → Environment Variables*: `DATABASE_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `TIMEZONE`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI=https://TU-PROYECTO.vercel.app/api/google/callback` y `FRONTEND_URL=https://TU-PROYECTO.vercel.app`.
4. *Deploy*. Cada `git push` vuelve a publicar. **Abrí la URL enseguida y creá tu PIN**: mientras no exista, el primero que entre a la URL lo define.

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
  app/db.py                 modelos y conexión (Settings, Shift, DayOverride, BankMovement, AppPin, GoogleToken)
  app/security.py           PIN de acceso: creación, cambio, verificación con hash y bloqueo por intentos
  app/calc.py               cálculos: jornadas, extras, banco, desgloses
  app/excel.py              exportación .xlsx
  app/assistant.py          asistente Gemini con function calling (15 herramientas)
  app/google_integration.py OAuth + Calendar + Tasks
  app/main.py               API REST y servidor del frontend
  tests/test_app.py         pruebas
frontend/
  src/App.jsx               pantallas Hoy, Historial, Banco, Asistente, Ajustes
  src/voice.js              voz (Web Speech API)
  src/custom.scss           Bootstrap 5.3 con los tokens del Design System
  src/app.css               tokens extra y ajustes de tema oscuro
  src/theme.js              tema claro/oscuro/automático
index.py (entrada Vercel) · vercel.json · pyproject.toml · requirements.txt
```

## API (resumen)

`GET /api/status` · `POST /api/clock-in` · `POST /api/clock-out` · `GET|POST /api/shifts` · `PUT|DELETE /api/shifts/{id}` · `GET /api/summary?desde&hasta` · `PUT /api/days/{fecha}/extra` · `GET|POST /api/bank` · `PUT|DELETE /api/bank/{id}` · `GET|PUT /api/settings` · `GET /api/export.xlsx?desde&hasta` · `POST /api/assistant` · `GET /api/google/auth-url` · `POST /api/google/disconnect`.
`GET /api/pin/status` · `POST /api/pin/setup` (solo si todavía no hay PIN) · `POST /api/pin/change`.
Todas (menos health, callback de Google y los tres de `/api/pin/*`) requieren el encabezado `X-App-Pin`. Documentación interactiva en `/docs`.
