# Real Scanner — Mobile App

**Live Fixtures +EV Scanner** — PWA + Capacitor Android. Auto-pulls **44 ESPN fixtures** (EPL, LaLiga, Serie A, Bundesliga, Ligue 1, Eredivisie, Primeira, Brazil...), Poisson xG, +EV flags, xG table, betslip single tab, calendar for past results, auto-refresh daily.

> Built from Flask PWA → wrapped as native Android via Capacitor. Works offline (44 preloaded) + live fetch when online.

## Features (v14)
- **Auto-pull 44 fixtures** for today (server preload + client stale check). Tomorrow auto-refreshes at 00:05 + on app resume.
- **All ESPN fixtures** not just 20 — 11 leagues, 44 today (expands daily).
- **Calendar** `📅` for past results (`?date=YYYY-MM-DD` → FT badges).
- **xG Table** `📊` — home/away/total xG + OVER/BTTS probs.
- **Betslip single tab** 🎫 — every prediction `Add to Betslip`, combined odds, stake, copy.
- **League chips** + `All Global (44)` filter.
- **Auto-upgrade**: checks `build-version` every 30min → clears cache + reload.

## Run as PWA (instant)
Just open the Flask server `https://your-server/` on phone → **Add to Home Screen** → standalone.

## Run as Native Android (Capacitor)

```bash
npm install
npx cap add android
npx cap sync
npx cap open android   # opens Android Studio
# Build APK in Android Studio: Build → Build APK(s)
```

The `www/` folder is the PWA (235k `index.html` + icons + manifest + service-worker). No build step needed.

## Backend
Flask `app.py` serves:
- `GET /` → 44 fixtures preloaded server-side (no tap needed)
- `GET /api/jap/real_fixtures?provider=espn&league=all&count=all` → 44 (0.5s)
- `POST /api/jap/scan` → Poisson +EV scan

Host the Flask app (Render/Railway/Fly) and set `capacitor.config.json` → `server.url` if you want the native app to always hit your hosted API. Otherwise it works offline with preloaded 44.

## GitHub Actions — Auto APK
Push to `main` triggers `.github/workflows/build-apk.yml` → builds debug APK (no signing) + uploads artifact. Download from **Actions** tab.

## Icons
`www/icon-192.png` / `www/icon-512.png` — used for splash + launcher.

## Version
`v14-2026-09-20` — auto-pull + auto-upgrade + 44 fixtures.

---

**Port Harcourt 2026** — No virtuals, 100% real ESPN FREE (no key) + OPEN FREE 2 fallback.
