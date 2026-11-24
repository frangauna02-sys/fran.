# Radar IA & Marketing

Página con las últimas noticias de **inteligencia artificial** y **marketing** del mundo, en un solo lugar.

- Se actualiza sola cada **30 minutos** (GitHub Actions descarga los feeds RSS de 18 fuentes).
- La página abierta busca novedades cada 5 minutos y te avisa con un botón "↑ N noticias nuevas".
- Filtros: IA / Marketing, búsqueda, por fuente, solo en español, últimas 24 h y "nuevas desde mi última visita".
- Podés **guardar** noticias para leer después y **traducir** las que están en inglés.
- Modo claro/oscuro.

## Cómo publicarla (una sola vez)

1. Uní esta rama a `main`.
2. En GitHub: **Settings → Pages → Build and deployment → Source: "GitHub Actions"**.
3. En **Actions → "Actualizar noticias" → Run workflow** para la primera carga.
4. La página queda en `https://<tu-usuario>.github.io/<repo>/`.

> GitHub solo corre las tareas programadas si el repo tuvo actividad en los últimos 60 días;
> como el bot hace commits con cada actualización, se mantiene solo.

## Agregar o quitar fuentes

Editá `feeds.json`: cada fuente tiene `name`, `url` (RSS o Atom) y opcionalmente `"lang": "es"`.

## Archivos

- `index.html` — la página.
- `feeds.json` — lista de fuentes.
- `scripts/fetch_news.py` — descarga los feeds y genera `data/news.json` (solo Python estándar).
- `.github/workflows/update-news.yml` — corre el script cada 30 min y publica en GitHub Pages.
