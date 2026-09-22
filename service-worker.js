// v14 AUTO-REFRESH - wipe caches, bypass API, network only for pages
self.addEventListener('install', e=> self.skipWaiting());
self.addEventListener('activate', e=> {
  e.waitUntil(
    caches.keys().then(keys=> Promise.all(keys.map(k=> caches.delete(k)))).then(()=> self.clients.claim())
  );
});
self.addEventListener('fetch', e=> {
  const url = new URL(e.request.url);
  // never intercept API - let browser fetch directly (prevents stuck)
  if(url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request, {cache:'no-store'}).catch(()=> fetch(e.request)));
});
