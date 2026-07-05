/*
 * sw.js — offline/installable app shell for Spår.
 *
 * Cache-first over the handful of static files; there is no dynamic content
 * yet, so this is both safe and complete. BUMP THE VERSION on every deploy
 * that changes any cached file — that is the whole invalidation strategy.
 */
const CACHE = "spar-v1";
const SHELL = [
  "./",
  "index.html",
  "styles.css",
  "data.js",
  "engine.js",
  "app.js",
  "manifest.webmanifest",
  "icon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request))
  );
});
