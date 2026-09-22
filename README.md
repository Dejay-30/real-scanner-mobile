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

## 📲 Download the Android APK (direct)

**[`Real-Scanner-v16.apk`](https://dejay-30.github.io/real-scanner-mobile/Real-Scanner-v16.apk)** — debug build, no signing needed to install. v16: real prices everywhere (SofaScore multi-book + ESPN cross-fill), auto-predictions with W/L ticks.

On your phone: open the link → let it download → tap the file → allow *Install unknown apps* if asked. The app runs fullscreen with its own icon, auto-pulls every fixture on open, and the engine is identical to the web version at **https://dejay-30.github.io/real-scanner-mobile/**.

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
`v15-2026-09-22` — EVERY-fixture capture + honesty fixes:
- **SofaScore primary source** (client-side): every not-started fixture on the wire, real multi-book averaged 1X2, per-team ATK/DEF from the last 10 real matches (home_xg = ATK_home x DEF_away).
- **ESPN fallback uses `all/scoreboard` + `limit=500`** — every league ESPN carries (118+ today vs the old 13-league/44 list), no hardcoded slug list.
- **No invented odds, ever.** Missing prices are `null` (shown as —) instead of the old `true x uniform` fill-ins; BTTS bookie prices are never fabricated; +EV is flagged ONLY when a real book price beats the FORM model's true odds.
- **Stale preload removed** — the standalone no longer ships a frozen 44-fixture snapshot; it auto-captures fresh on open.
- **Demo fixtures removed** — capture failure shows an honest empty state, never fake data.
- Flask backend (`app.py`) patched to match: every league, real DraftKings prices only, manual adds without odds carry no odds.

`v14-2026-09-20` — auto-pull + auto-upgrade + 44 fixtures.

---

**Port Harcourt 2026** — No virtuals, 100% real ESPN FREE (no key) + OPEN FREE 2 fallback.
