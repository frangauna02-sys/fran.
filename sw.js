// Service worker: la página abre aunque no haya conexión, con las últimas noticias descargadas.
const CACHE = "radar-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  // Red primero (para tener siempre lo último) y, si no hay conexión, lo guardado.
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok) {
        const copy = res.clone();
        const key = url.pathname.endsWith(".json") ? url.pathname : e.request;
        caches.open(CACHE).then(c => c.put(key, copy));
      }
      return res;
    }).catch(() => caches.match(url.pathname.endsWith(".json") ? url.pathname : e.request))
  );
});
