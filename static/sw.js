/**
 * sw.js — Service Worker for Family Expense Tracker PWA
 *
 * Only registered from m.expensemanager.mydailybot.com (mobile subdomain).
 * The desktop subdomain never registers this SW.
 *
 * Strategies:
 *   • HTML page loads  → Network-only, cache: 'no-store'
 *       Server-rendered + auth-gated pages must always be fresh.
 *       Never cache HTML — avoids every stale layout bug we had before.
 *   • /static/* assets → Cache-first, fall back to network.
 *       Bootstrap, Chart.js, icons don't change. Safe to cache aggressively.
 *   • Everything else  → Pass-through (not intercepted).
 */

const STATIC_CACHE = 'expense-tracker-static-v1';

// Pre-cache only truly static files — never HTML
const PRECACHE_URLS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/js/app.js',
];

const CURRENT_CACHES = [STATIC_CACHE];

// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: purge old caches ────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(
        names
          .filter(name => !CURRENT_CACHES.includes(name))
          .map(name => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;
  if (!url.protocol.startsWith('http')) return;

  // ── HTML page loads → network-only, bypass all caches ────────────────────
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request, { cache: 'no-store' }).catch(() =>
        new Response(
          `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Offline — Expense Tracker</title>
  <style>
    body{font-family:system-ui,sans-serif;display:flex;align-items:center;
         justify-content:center;min-height:100vh;margin:0;
         background:#0f1117;color:#e2e8f0;text-align:center;padding:2rem}
    h1{font-size:1.8rem;margin-bottom:.5rem}
    p{color:#94a3b8}a{color:#818cf8}
  </style>
</head>
<body>
  <div>
    <div style="font-size:3rem;margin-bottom:1rem">💰</div>
    <h1>You're offline</h1>
    <p>The expense tracker needs a connection to load.</p>
    <p><a href="/">Try again</a></p>
  </div>
</body>
</html>`,
          { status: 503, headers: { 'Content-Type': 'text/html' } }
        )
      )
    );
    return;
  }

  // ── Static assets → cache-first ───────────────────────────────────────────
  if (
    url.pathname.startsWith('/static/') ||
    url.hostname.includes('cdn.jsdelivr.net') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com')
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // Everything else (API calls, auth endpoints) → pass-through
});

// ── Helper: cache-first ───────────────────────────────────────────────────────
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    return new Response('Offline', { status: 503 });
  }
}
