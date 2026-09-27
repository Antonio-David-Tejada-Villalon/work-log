# Prompts para imágenes de Control Horario

Paleta del Design System: verde petróleo `#1F5C52` (primario), ámbar `#F2B544` (horas extra), crema `#F6F4EF` (fondo), tinta `#1D2421`, verde claro `#DCEBE7`.
Los prompts están en inglés porque la mayoría de los generadores (Midjourney, Firefly, Ideogram, Flux, SDXL) responden mejor así. Ninguna imagen debe llevar texto: los generadores suelen escribirlo mal, y la app ya muestra el nombre.

---

## 1. Ícono de la app (logo) → `frontend/public/icon-512.png` (y reducido a 192 px → `icon-192.png`)

**Positivo**
```
Minimal flat vector app icon, a simple round clock face in cream #F6F4EF centered on a solid deep teal #1F5C52 square background, twelve small dot hour marks, one long cream minute hand and one short amber #F2B544 hour hand, subtle small amber arc suggesting accumulated time, geometric, bold clean shapes, generous safe margin around the symbol (symbol occupies central 60%), perfectly centered, symmetrical, crisp edges, modern productivity app icon, 1:1, high resolution
```
**Negativo**
```
text, letters, numbers, words, watermark, signature, gradient background, 3D render, bevel, glossy, drop shadow, photorealistic, realistic metal, roman numerals, busy details, multiple clocks, hands, people, cartoon face, clutter, noise, grain, blurry, low resolution, cropped symbol, off-center, border frame, rounded corners baked in
```
Notas: exportá PNG cuadrado sin esquinas redondeadas (Android las recorta). Parámetros sugeridos en Midjourney: `--ar 1:1 --style raw --no text`.

---

## 2. Isotipo monocromo (opcional, para documentos o favicon) → `frontend/public/img/logo-mono.svg`

**Positivo**
```
Minimal monochrome logo mark, simple clock outline with twelve dot hour marks and two hands, single flat color deep teal #1F5C52 on pure white background, thick uniform strokes, geometric, vector style, centered, flat, no fill gradients, 1:1
```
**Negativo**
```
text, letters, numbers, color, gradient, shadow, 3D, texture, photorealistic, sketch lines, extra ornaments, frame, watermark, blurry
```
Notas: si el generador entrega PNG, vectorizalo (por ejemplo con Inkscape → Trazar mapa de bits) para obtener el SVG.

---

## 3. Ilustración "historial vacío" → `frontend/public/img/empty-history.webp`

**Positivo**
```
Friendly minimal flat illustration for an empty state screen, a small open calendar page and a simple desk clock resting side by side, soft rounded geometric shapes, limited palette deep teal #1F5C52, soft mint #DCEBE7, amber accent #F2B544, charcoal #1D2421 outlines very thin or none, lots of negative space, isolated on transparent background, centered composition, calm and optimistic mood, modern productivity app style, 1:1
```
**Negativo**
```
text, letters, numbers, dates written, logo, watermark, people, faces, hands, photorealistic, 3D render, heavy shadows, gradients, busy background, scenery, clutter, dark mood, neon colors, purple, blue-purple gradient, noise, blurry
```

---

## 4. Ilustración del asistente de voz → `frontend/public/img/assistant.webp`

**Positivo**
```
Minimal flat illustration of a friendly voice assistant concept, a rounded microphone symbol emitting three soft sound-wave arcs toward a small clock and a checklist card, simple geometric shapes, limited palette deep teal #1F5C52, soft mint #DCEBE7, amber #F2B544, cream highlights, isolated on transparent background, lots of negative space, centered, calm, modern app onboarding style, 1:1
```
**Negativo**
```
text, letters, numbers, speech bubbles with words, robot face, humanoid robot, people, faces, hands, photorealistic, 3D render, glossy, heavy shadows, gradients, neon, purple, sci-fi, busy background, clutter, watermark, blurry
```

---

## Después de generar

1. Reducí el ícono a 192×192 para `icon-192.png` (misma imagen).
2. Convertí las ilustraciones a WEBP con fondo transparente, unos 600×600 px y menos de 80 KB cada una.
3. Guardalas en las rutas indicadas, ejecutá `npm run build` (o hacé `git push` si ya está en Vercel). Si una imagen falta, la app simplemente no la muestra.
4. Si cambiás el ícono de forma notable, revisá que `theme_color` en `frontend/vite.config.js` siga combinando (`#1F5C52`).
