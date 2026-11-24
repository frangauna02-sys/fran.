# Radar IA & Marketing

Tu fuente diaria de noticias de **inteligencia artificial** y **marketing**, en un solo lugar.

## Qué hace

- **Noticias de 34 fuentes** (medios, blogs oficiales, newsletters y canales de YouTube) que se actualizan solas cada **30 minutos**.
- **☀️ Resumen diario con IA**: cada mañana, las 10 noticias más importantes explicadas en español, con un **"por qué importa"** para marketers, la tendencia de la semana y una idea para probar ese día. Se guardan los últimos 14 días.
- **Te llega solo** por **Telegram** y/o **email** todas las mañanas.
- **📈 Temas en tendencia**: lo más mencionado en los últimos 3 días, con cuánto creció. Al tocar un tema, se filtran las noticias.
- **Glosario**: más de 60 términos (ROAS, RAG, GEO, CPM…). En las noticias aparecen subrayados con puntos y muestran su significado al pasar el mouse o tocarlos.
- **Modo estudio**: marcar noticias como leídas (se marcan solas al abrirlas), ocultar las leídas, guardar noticias con **notas propias** y una **racha** de días leyendo.
- **App en el celular**: se puede instalar con ícono propio y abre aunque no haya conexión, con lo último que se descargó.
- Filtros por IA o Marketing, fuente, idioma, últimas 24 h, videos y newsletters; búsqueda; modo claro y oscuro; botón para traducir.

> Las notas, las noticias guardadas y la racha se guardan **en tu navegador**: no se comparten entre el celular y la computadora.

---

## Puesta en marcha

### 1. Publicar la página (obligatorio)

1. Uní esta rama a `main`.
2. **Settings → Pages → Build and deployment → Source: "GitHub Actions"**.
3. **Actions → "Actualizar noticias" → Run workflow**.
4. La página queda en `https://<tu-usuario>.github.io/<repo>/`.

### 2. Resumen con IA (recomendado)

1. Creá una clave en <https://console.anthropic.com> (**API Keys**) y cargale crédito. El resumen diario cuesta unos pocos centavos de dólar por día.
2. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
   - Nombre: `ANTHROPIC_API_KEY` · Valor: tu clave.

Sin la clave, el resumen igual se arma, pero solo con los titulares más recientes y sin explicaciones.

### 3. Recibirlo por Telegram

1. En Telegram, abrí **@BotFather**, mandale `/newbot` y seguí los pasos. Te da un **token**.
2. Abrí el bot que creaste y mandale cualquier mensaje (por ejemplo "hola").
3. Entrá a `https://api.telegram.org/bot<TOKEN>/getUpdates` (reemplazando `<TOKEN>`) y buscá `"chat":{"id": 123456789`. Ese número es tu **chat id**.
4. Cargá los secretos `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

### 4. Recibirlo por email (Gmail)

1. Activá la verificación en 2 pasos en tu cuenta de Google.
2. Creá una **contraseña de aplicación** en <https://myaccount.google.com/apppasswords>.
3. Cargá los secretos:
   - `SMTP_USER`: tu dirección de Gmail.
   - `SMTP_PASSWORD`: la contraseña de aplicación (16 letras).
   - `EMAIL_TO`: a dónde querés recibirlo. Para varias direcciones, separalas con comas.

Para usar otro proveedor de correo, agregá las **variables** (no secretos) `SMTP_HOST` y `SMTP_PORT`.

### 5. Hora y zona horaria del resumen (opcional)

Por defecto, el resumen se arma a partir de las **7:00 de Buenos Aires**. Para cambiarlo: **Settings → Secrets and variables → Actions → Variables**.

- `DIGEST_TZ`: por ejemplo `Europe/Madrid`, `America/Mexico_City` o `America/Bogota`.
- `DIGEST_HOUR`: la hora local, por ejemplo `8`.

Para probarlo en el momento: **Actions → Actualizar noticias → Run workflow**, con la casilla **"Rehacer y reenviar el resumen de hoy"** marcada.

### Instalar en el celular

- **Android (Chrome)**: abrí la página → menú ⋮ → **Instalar app** (o tocá el botón "Instalar app").
- **iPhone (Safari)**: abrí la página → botón Compartir → **Agregar a pantalla de inicio**.

---

## Personalizar

- **Fuentes**: en `feeds.json`. Cada fuente tiene `name` y `url` (RSS o Atom) y, de forma opcional, `"lang": "es"` y `"type": "video"` o `"newsletter"`. Para agregar un canal de YouTube, usá `https://www.youtube.com/feeds/videos.xml?channel_id=<ID>`. Al pie de la página se ven las fuentes que no respondieron.
- **Qué prioriza el resumen**: el texto `PROMPT` en `scripts/daily_digest.py`.
- **Términos del glosario**: el objeto `GLOSSARY` en `index.html`.

## Archivos

| Archivo | Qué es |
|---|---|
| `index.html` | La página |
| `feeds.json` | Lista de fuentes |
| `scripts/fetch_news.py` | Descarga los feeds, calcula las tendencias y genera `data/news.json` |
| `scripts/daily_digest.py` | Arma el resumen con Claude y lo envía por Telegram y email (`data/digest.json`) |
| `.github/workflows/update-news.yml` | Corre todo cada 30 min y publica en GitHub Pages |
| `manifest.webmanifest`, `sw.js`, `icons/` | Lo necesario para instalarla como app |
