# Francisco Gauna · Portfolio

Sitio web profesional de Francisco Gauna (marketing digital, Cipolletti / Neuquén).
Hecho con HTML, CSS y JavaScript simples: no necesita instalar nada ni compilar.

## Estructura

```
index.html          → todo el contenido de la página (textos, proyectos, formación)
css/styles.css      → diseño (colores en las variables de :root, al principio)
js/config.js        → correo, LinkedIn, WhatsApp, CV y foto  ← completar
js/main.js          → menú móvil, botones de contacto y animaciones (no hace falta tocarlo)
assets/img/         → foto, logos y capturas de proyectos
```

## Cómo verla

Abrí `index.html` con doble clic en cualquier navegador.
Opcional, con un servidor local: `python3 -m http.server` y entrá a http://localhost:8000

## Qué completar

1. **`js/config.js`**: `email`, `linkedin`, `whatsapp` (formato `549299XXXXXXX`), `cv` y `foto`.
   Mientras un campo esté vacío, su botón aparece desactivado con la etiqueta “pendiente”.
2. **Foto**: guardala en `assets/img/` (vertical, ~800×1000 px) y poné la ruta en `foto`.
3. **CV**: guardá el PDF en `assets/` y poné la ruta en `cv`.
4. **Textos marcados en amarillo** (`class="completar"` en `index.html`): objetivo, rol y año,
   herramientas y resultados confirmados de cada proyecto; institución de la licenciatura;
   año de egreso; año de la inmersión en CEREM; experiencia laboral formal (o borrar ese bloque).
5. **Imágenes de proyectos**: reemplazá cada `<div class="placeholder placeholder-media" ...>…</div>` por
   `<img src="assets/img/archivo.jpg" alt="Descripción" loading="lazy">`.
6. Al publicar: descomentá y completá `og:url` y `og:image` en el `<head>`.

## Publicar

- **GitHub Pages**: en el repositorio, Settings → Pages → “Deploy from a branch” → rama `main`, carpeta `/ (root)`.
- **Netlify** o **Vercel**: importar el repositorio (sin comando de build, carpeta raíz).
- **Dominio propio** (ej. `franciscogauna.com.ar` en NIC Argentina): se conecta desde cualquiera de las opciones anteriores.
