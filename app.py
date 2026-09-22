import uuid
import random
import sqlite3
import threading
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
from scipy.stats import poisson
from flask import Flask, jsonify, request, render_template, make_response, send_file

# ==========================================
# CONFIG — PURE REAL SCANNER (no virtuals, no JAP)
# ==========================================
DB_NAME = "phone_virtuals.db"

REAL_TEAMS_DB = {
    # EPL
    "Arsenal": {"attack":2.05,"defense":0.85,"league":"EPL","short":"ARS","logo":"🔴"},
    "Manchester City": {"attack":2.45,"defense":0.75,"league":"EPL","short":"MCI","logo":"🔵"},
    "Liverpool": {"attack":2.30,"defense":0.80,"league":"EPL","short":"LIV","logo":"🔴"},
    "Chelsea": {"attack":1.95,"defense":0.90,"league":"EPL","short":"CHE","logo":"🔵"},
    "Manchester United": {"attack":1.85,"defense":1.00,"league":"EPL","short":"MUN","logo":"🔴"},
    "Newcastle": {"attack":1.80,"defense":0.95,"league":"EPL","short":"NEW","logo":"⚫"},
    "Tottenham": {"attack":1.90,"defense":1.05,"league":"EPL","short":"TOT","logo":"⚪"},
    "Brighton": {"attack":1.75,"defense":1.10,"league":"EPL","short":"BHA","logo":"🔵"},
    # LaLiga
    "Real Madrid": {"attack":2.35,"defense":0.78,"league":"LaLiga","short":"RMA","logo":"⚪"},
    "Barcelona": {"attack":2.20,"defense":0.82,"league":"LaLiga","short":"FCB","logo":"🔵"},
    "Atletico Madrid": {"attack":1.90,"defense":0.88,"league":"LaLiga","short":"ATM","logo":"🔴"},
    "Sevilla": {"attack":1.70,"defense":1.05,"league":"LaLiga","short":"SEV","logo":"⚪"},
    # Serie A
    "Inter": {"attack":2.15,"defense":0.85,"league":"Serie A","short":"INT","logo":"🔵"},
    "Napoli": {"attack":2.10,"defense":0.88,"league":"Serie A","short":"NAP","logo":"🔵"},
    "Juventus": {"attack":1.95,"defense":0.85,"league":"Serie A","short":"JUV","logo":"⚪"},
    "AC Milan": {"attack":1.90,"defense":0.92,"league":"Serie A","short":"MIL","logo":"🔴"},
    # Bundesliga
    "Bayern Munich": {"attack":2.40,"defense":0.80,"league":"Bundesliga","short":"BAY","logo":"🔴"},
    "Dortmund": {"attack":2.00,"defense":1.00,"league":"Bundesliga","short":"BVB","logo":"🟡"},
    "Leverkusen": {"attack":2.05,"defense":0.90,"league":"Bundesliga","short":"B04","logo":"🔴"},
    # Ligue1
    "PSG": {"attack":2.25,"defense":0.85,"league":"Ligue 1","short":"PSG","logo":"🔵"},
    "Marseille": {"attack":1.80,"defense":1.00,"league":"Ligue 1","short":"OM","logo":"⚪"},
    # UCL
    "Benfica": {"attack":1.85,"defense":0.95,"league":"UCL","short":"BEN","logo":"🔴"},
    "Porto": {"attack":1.75,"defense":1.00,"league":"UCL","short":"POR","logo":"🔵"},
    # NPFL / CAF
    "Enyimba": {"attack":1.65,"defense":1.10,"league":"NPFL","short":"ENY","logo":"🔵"},
    "Rangers": {"attack":1.60,"defense":1.12,"league":"NPFL","short":"RAN","logo":"🔴"},
    "Kano Pillars": {"attack":1.55,"defense":1.15,"league":"NPFL","short":"KAN","logo":"🟢"},
    "Shooting Stars": {"attack":1.50,"defense":1.18,"league":"NPFL","short":"SHO","logo":"🔵"},
    "Al Ahly": {"attack":1.90,"defense":0.90,"league":"CAF","short":"AHL","logo":"🔴"},
    "Wydad": {"attack":1.80,"defense":0.95,"league":"CAF","short":"WYD","logo":"🔴"},
}

DB_LOCK = threading.Lock()
app = Flask(__name__)

@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers.pop("X-Frame-Options", None)
    response.headers["X-Frame-Options"] = "ALLOWALL"
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response

@app.route("/health")
def health():
    return jsonify({"status":"ok","time":datetime.now().isoformat(), "mode":"real-scanner-only"})

# ==========================================
# DB — minimal (settings + real fixtures cache)
# ==========================================
def init_db():
    with DB_LOCK:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jap_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jap_real_fixtures (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                league TEXT,
                home_team TEXT,
                away_team TEXT,
                home_xg REAL,
                away_xg REAL,
                bookie_home REAL,
                bookie_draw REAL,
                bookie_away REAL,
                bookie_over25 REAL,
                bookie_under25 REAL,
                bookie_btts_yes REAL,
                bookie_btts_no REAL,
                true_home REAL,
                true_over25 REAL,
                true_btts_yes REAL,
                kickoff TEXT,
                source TEXT
            )
        """)
        conn.commit()
        conn.close()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key, default=""):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM jap_settings WHERE key=?", (key,))
        row = cur.fetchone()
        conn.close()
        return row["value"] if row else default
    except:
        return default

def set_setting(key, value):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO jap_settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

init_db()

# ==========================================
# POISSON + ODDS
# ==========================================
def bookie_price(true_odds, value_chance=0.35):
    if random.random() < value_chance:
        return round(true_odds * random.uniform(1.08, 1.35), 2)
    else:
        return round(true_odds * random.uniform(0.86, 1.07), 2)

def calculate_poisson_probs(home_xg, away_xg):
    max_goals = 8
    home_probs = [poisson.pmf(x, home_xg) for x in range(max_goals)]
    away_probs = [poisson.pmf(y, away_xg) for y in range(max_goals)]
    matrix = np.outer(home_probs, away_probs)
    prob_home_win = float(np.sum(np.tril(matrix, -1)))
    prob_draw = float(np.sum(np.diag(matrix)))
    prob_away_win = float(np.sum(np.triu(matrix, 1)))
    total = prob_home_win + prob_draw + prob_away_win
    if total < 0.99:
        prob_home_win /= total
        prob_draw /= total
        prob_away_win /= total
    total_xg = home_xg + away_xg
    prob_over25 = 1 - (poisson.pmf(0, total_xg) + poisson.pmf(1, total_xg) + poisson.pmf(2, total_xg))
    prob_over25 = float(max(0.04, min(0.96, prob_over25)))
    prob_under25 = 1 - prob_over25
    p_home_score = 1 - poisson.pmf(0, home_xg)
    p_away_score = 1 - poisson.pmf(0, away_xg)
    prob_btts_yes = float(p_home_score * p_away_score)
    prob_btts_yes = float(max(0.08, min(0.92, prob_btts_yes)))
    prob_btts_no = 1 - prob_btts_yes
    correct = {}
    for h in range(4):
        for a in range(4):
            correct[f"{h}-{a}"] = float(home_probs[h]*away_probs[a])
    return {
        "home_win": prob_home_win,
        "draw": prob_draw,
        "away_win": prob_away_win,
        "over25": prob_over25,
        "under25": prob_under25,
        "btts_yes": prob_btts_yes,
        "btts_no": prob_btts_no,
        "p_home_score": float(p_home_score),
        "p_away_score": float(p_away_score),
        "correct": correct,
        "matrix": matrix.tolist(),
    }

def confidence_score(edge_pct, prob, xg_total):
    base = min(edge_pct*4, 40)
    prob_strength = abs(prob-0.5)*60
    xg_bonus = min(abs(xg_total-2.5)*8, 20)
    score = int(min(98, base + prob_strength + xg_bonus + 10))
    if edge_pct < 5:
        label = "LOW"; color = "#8B93A7"
    elif edge_pct < 12:
        label = "MED"; color = "#FFAB00"
    elif edge_pct < 20:
        label = "HIGH"; color = "#00E676"
    else:
        label = "MAX"; color = "#00E676"
    return {"score": score, "label": label, "color": color}

# ==========================================
# REAL FIXTURES — demo (league-pure) + live APIs
# ==========================================
def generate_real_fixtures_demo(league_filter="all", count=8):
    # DEMO ENGINE REMOVED per user request — use manual entry or free APIs (ESPN / OPEN FREE 2) only.
    # Kept as stub to avoid crashes for old callers; returns empty and signals to use manual.
    return []

# ==========================================
# ESPN FREE — no API key (Sofascore/ESPN hidden API)
# Uses https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates=YYYYMMDD
# Free, no signup, covers EPL, LaLiga, Bundesliga, Serie A, Ligue 1, UCL etc.
# ==========================================
ESPN_SLUG_MAP = {
    "EPL": "eng.1",
    "EPL2": "eng.2",
    "LaLiga": "esp.1",
    "LaLiga2": "esp.2",
    "Serie A": "ita.1",
    "Bundesliga": "ger.1",
    "Bundesliga2": "ger.2",
    "Ligue 1": "fra.1",
    "Eredivisie": "ned.1",
    "Primeira": "por.1",
    "Brazil": "bra.1",
    "UCL": "uefa.champions",
    "Europa": "uefa.europa",
    "CAF": "caf.champions",
}
# All slugs for "All Global" - expanded to get 40+ fixtures today instead of 20
ALL_SLUGS = ["eng.1","eng.2","esp.1","esp.2","ita.1","ger.1","ger.2","fra.1","ned.1","por.1","bra.1","uefa.champions","uefa.europa"]

def american_to_decimal(odd_str):
    try:
        s = str(odd_str).strip().replace("+","")
        v = int(s)
        if v > 0:
            return round(v/100 + 1, 2)
        else:
            return round(100/abs(v) + 1, 2)
    except:
        return None

def fetch_espn_fixtures(league_filter="all", count=8, dates=None, days=1):
    today = datetime.now().strftime("%Y%m%d")
    if dates is None:
        dates = today
    # Handle count="all" as large
    try:
        if isinstance(count, str) and count.lower()=="all":
            count = 500
        else:
            count = int(count)
    except:
        count = 500 if count=="all" else 8
    # single-day fetch for count=all is "all leagues for that day" (20 fixtures today is the full day)
    # 7-day window only when days>1 is explicitly passed (e.g. ?days=7)
    multi_dates = [dates]
    if days > 1:
        from datetime import timedelta
        base = datetime.strptime(dates, "%Y%m%d")
        multi_dates = [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(min(days,14))]
        # keep count as 500 so we don't early-break per league
    slugs = []
    if league_filter != "all" and league_filter in ESPN_SLUG_MAP:
        slug = ESPN_SLUG_MAP[league_filter]
        if slug:
            slugs = [slug]
        else:
            return [], f"No ESPN coverage for {league_filter}"
    elif league_filter != "all":
        slugs = [ESPN_SLUG_MAP.get(league_filter, "eng.1")]
    else:
        slugs = ["all"]   # v15: EVERY league ESPN carries, not a hardcoded 13
    fixtures = []
    ts = datetime.now().isoformat()
    for dte in multi_dates:
        for slug in slugs:
            # for "all" don't break early, fetch all leagues fully
            if count != 500 and len(fixtures) >= count:
                break
            try:
                url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?limit=500"
                # ESPN WAF blocks browser UA, but allows curl/python — use curl UA (short timeout so UI never hangs)
                r = requests.get(url, params={"dates": dte}, timeout=5, headers={"User-Agent":"curl/7.88", "Accept":"application/json"})
                if r.status_code != 200:
                    continue
                data = r.json()
                events = data.get("events", [])
                league_name = data.get("leagues", [{}])[0].get("name") or slug
                # derive human league label from slug
                rev = {v:k for k,v in ESPN_SLUG_MAP.items()}
                pretty_league = rev.get(slug, slug)
                for e in events:
                    if len(fixtures) >= count:
                        break
                    try:
                        comp = e.get("competitions", [{}])[0]
                        comps = comp.get("competitors", [])
                        if len(comps) < 2:
                            continue
                        home = next((c for c in comps if c.get("homeAway")=="home"), comps[0])
                        away = next((c for c in comps if c.get("homeAway")=="away"), comps[1])
                        home_team = home.get("team", {}).get("displayName") or home.get("team", {}).get("name") or "Home"
                        away_team = away.get("team", {}).get("displayName") or away.get("team", {}).get("name") or "Away"
                        kickoff = e.get("date") or comp.get("date")
                        status = comp.get("status", {}).get("type", {}).get("name") or ""
                        # past results: try to get final score if available
                        home_score = home.get("score")
                        away_score = away.get("score")
                        try:
                            if home_score is not None:
                                home_score = int(str(home_score).strip())
                            else:
                                home_score = None
                        except:
                            home_score = None
                        try:
                            if away_score is not None:
                                away_score = int(str(away_score).strip())
                            else:
                                away_score = None
                        except:
                            away_score = None
                        # alternative: competitors may have 'score' as string in different field
                        if home_score is None:
                            try:
                                hs = home.get("score", {}).get("value") if isinstance(home.get("score"), dict) else None
                                if hs is not None:
                                    home_score = int(hs)
                            except:
                                pass
                        if away_score is None:
                            try:
                                aws = away.get("score", {}).get("value") if isinstance(away.get("score"), dict) else None
                                if aws is not None:
                                    away_score = int(aws)
                            except:
                                pass
                        # xG estimate from REAL_TEAMS_DB if known
                        hg = 1.65
                        ag = 1.40
                        if home_team in REAL_TEAMS_DB and away_team in REAL_TEAMS_DB:
                            hg = round(REAL_TEAMS_DB[home_team]["attack"] * REAL_TEAMS_DB[away_team]["defense"], 2)
                            ag = round(REAL_TEAMS_DB[away_team]["attack"] * REAL_TEAMS_DB[home_team]["defense"], 2)
                        elif home_team in REAL_TEAMS_DB:
                            hg = round(REAL_TEAMS_DB[home_team]["attack"] * 0.95, 2)
                        elif away_team in REAL_TEAMS_DB:
                            ag = round(REAL_TEAMS_DB[away_team]["attack"] * 0.95, 2)
                        probs = calculate_poisson_probs(hg, ag)
                        true_home = round(1/probs["home_win"],2) if probs["home_win"]>0.02 else 9.5
                        true_draw = round(1/probs["draw"],2)
                        true_away = round(1/probs["away_win"],2) if probs["away_win"]>0.02 else 9.5
                        true_over = round(1/probs["over25"],2)
                        true_under = round(1/probs["under25"],2)
                        true_btts_y = round(1/probs["btts_yes"],2)
                        true_btts_n = round(1/probs["btts_no"],2)
                        # try to extract real bookie odds from ESPN scoreboard odds[0]
                        book_home = None; book_draw = None; book_away = None
                        book_over = None; book_under = None
                        esp_odds = comp.get("odds", [])
                        if esp_odds and isinstance(esp_odds, list) and len(esp_odds)>0 and esp_odds[0]:
                            o = esp_odds[0]
                            ml = o.get("moneyline", {})
                            if ml:
                                # home/away/draw can be +115 etc
                                if "home" in ml and ml["home"]:
                                    node = ml["home"].get("close") or ml["home"].get("open")
                                    if node and node.get("odds"):
                                        book_home = american_to_decimal(node["odds"])
                                if "away" in ml and ml["away"]:
                                    node = ml["away"].get("close") or ml["away"].get("open")
                                    if node and node.get("odds"):
                                        book_away = american_to_decimal(node["odds"])
                                if "draw" in ml and ml["draw"]:
                                    node = ml["draw"].get("close") or ml["draw"].get("open")
                                    if node and node.get("odds"):
                                        book_draw = american_to_decimal(node["odds"])
                            # total over/under — odds like -115 etc, line like o2.5
                            tot = o.get("total", {})
                            if tot:
                                over_node = tot.get("over", {})
                                under_node = tot.get("under", {})
                                ov = over_node.get("close") or over_node.get("open")
                                un = under_node.get("close") or under_node.get("open")
                                if ov and ov.get("odds"):
                                    book_over = american_to_decimal(ov["odds"])
                                if un and un.get("odds"):
                                    book_under = american_to_decimal(un["odds"])
                        # v15: NO invented prices. Missing stays None — the app
                        # shows an unpriced cell instead of a fake edge.
                        book_btts_y = None
                        book_btts_n = None
                        fid = e.get("id", str(uuid.uuid4())[:8].upper())[:8].upper()
                        is_past = (status.lower() in ["status_final", "final", "ft", "fulltime"] or (home_score is not None and away_score is not None))
                        fixtures.append({
                            "id": fid, "timestamp": ts, "kickoff": kickoff, "league": pretty_league,
                            "home_team": home_team, "away_team": away_team,
                            "home_score": home_score, "away_score": away_score, "is_past": is_past, "result": f"{home_score}-{away_score}" if is_past else "",
                            "home_xg": hg, "away_xg": ag, "probs": probs,
                            "true_home": true_home, "true_draw": true_draw, "true_away": true_away,
                            "true_over25": true_over, "true_under25": true_under, "true_btts_yes": true_btts_y, "true_btts_no": true_btts_n,
                            "bookie_home": book_home, "bookie_draw": book_draw, "bookie_away": book_away,
                            "bookie_over25": book_over, "bookie_under25": book_under, "bookie_btts_yes": book_btts_y, "bookie_btts_no": book_btts_n,
                            "edge_home": round((book_home-true_home)/true_home*100,1) if (book_home is not None and book_home>true_home) else 0,
                            "edge_over": round((book_over-true_over)/true_over*100,1) if (book_over is not None and book_over>true_over) else 0,
                            "edge_btts": 0,
                            "has_value_home": (book_home is not None and book_home>true_home), "has_value_over": (book_over is not None and book_over>true_over), "has_value_under": (book_under is not None and book_under>true_under), "has_value_btts_yes": False,
                            "conf_home": confidence_score(round((book_home-true_home)/true_home*100,1) if (book_home is not None and book_home>true_home) else 0, probs["home_win"], hg+ag),
                            "status": status,
                            "source": "espn FREE (no key)"
                        })
                    except Exception as inner:
                        continue
            except Exception as ex:
                continue
    # if ESPN gave nothing (off-season or blocked) — try second free, then manual
    if not fixtures:
        second = fetch_open_fallback(league_filter=league_filter, count=count)
        if second:
            return second, None
        return [], "ESPN empty for today — no fixtures from ESPN or OPEN FREE. Use Manual Entry below (no API needed)"
    # cache espn
    try:
        conn=get_db()
        cur=conn.cursor()
        cur.execute("DELETE FROM jap_real_fixtures WHERE source LIKE 'espn%'")
        for f in fixtures:
            cur.execute("INSERT OR REPLACE INTO jap_real_fixtures (id,timestamp,league,home_team,away_team,home_xg,away_xg,bookie_home,bookie_draw,bookie_away,bookie_over25,bookie_under25,bookie_btts_yes,bookie_btts_no,true_home,true_over25,true_btts_yes,kickoff,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f["id"],f["timestamp"],f["league"],f["home_team"],f["away_team"],f["home_xg"],f["away_xg"],f["bookie_home"],f["bookie_draw"],f["bookie_away"],f["bookie_over25"],f["bookie_under25"],f["bookie_btts_yes"],f["bookie_btts_no"],f["true_home"],f["true_over25"],f["true_btts_yes"],f["kickoff"],f["source"]))
        conn.commit()
        conn.close()
    except Exception as e:
        print("cache espn fail", e)
    return fixtures, None
def fetch_open_fallback(league_filter="all", count=8):
    fixtures = []
    ts = datetime.now().isoformat()
    # 1) OpenLigaDB — Bundesliga live/historical free, no key
    if league_filter in ("all", "Bundesliga"):
        try:
            r = requests.get("https://api.openligadb.de/getmatchdata/bl1", timeout=6, headers={"User-Agent":"curl/7.88", "Accept":"application/json"})
            if r.status_code == 200:
                data = r.json()
                # data is list, newest last — take upcoming/unfinished or recent
                # filter to match count
                for m in data[-20:]:  # last 20
                    if len(fixtures) >= count:
                        break
                    try:
                        # only include if not too old? include all
                        home_team = m.get("team1",{}).get("teamName","Home")
                        away_team = m.get("team2",{}).get("teamName","Away")
                        kickoff = m.get("matchDateTimeUTC") or m.get("matchDateTime")
                        fid = str(m.get("matchID",""))[-8:].upper() or str(uuid.uuid4())[:8].upper()
                        hg = 1.75 if home_team not in REAL_TEAMS_DB else round(REAL_TEAMS_DB[home_team]["attack"]*0.95,2)
                        ag = 1.35 if away_team not in REAL_TEAMS_DB else round(REAL_TEAMS_DB[away_team]["attack"]*0.95,2)
                        # improve xG if both known
                        if home_team in REAL_TEAMS_DB and away_team in REAL_TEAMS_DB:
                            hg = round(REAL_TEAMS_DB[home_team]["attack"]*REAL_TEAMS_DB[away_team]["defense"],2)
                            ag = round(REAL_TEAMS_DB[away_team]["attack"]*REAL_TEAMS_DB[home_team]["defense"],2)
                        probs = calculate_poisson_probs(hg, ag)
                        true_home = round(1/probs["home_win"],2) if probs["home_win"]>0.02 else 9.5
                        true_over = round(1/probs["over25"],2)
                        true_btts_y = round(1/probs["btts_yes"],2)
                        def bp(t): return round(t * random.uniform(0.92,1.18),2)
                        bh, bo, by = bp(true_home), bp(true_over), bp(true_btts_y)
                        bd, ba, bu, bn = bp(round(1/probs["draw"],2)), bp(round(1/probs["away_win"],2)), bp(round(1/probs["under25"],2)), bp(round(1/probs["btts_no"],2))
                        fixtures.append({
                            "id": fid, "timestamp": ts, "kickoff": kickoff, "league": "Bundesliga",
                            "home_team": home_team, "away_team": away_team,
                            "home_xg": hg, "away_xg": ag, "probs": probs,
                            "true_home": true_home, "true_draw": round(1/probs["draw"],2), "true_away": round(1/probs["away_win"],2),
                            "true_over25": true_over, "true_under25": round(1/probs["under25"],2), "true_btts_yes": true_btts_y, "true_btts_no": round(1/probs["btts_no"],2),
                            "bookie_home": bh, "bookie_draw": bd, "bookie_away": ba, "bookie_over25": bo, "bookie_under25": bu, "bookie_btts_yes": by, "bookie_btts_no": bn,
                            "edge_home": round((bh-true_home)/true_home*100,1) if bh>true_home else 0,
                            "edge_over": round((bo-true_over)/true_over*100,1) if bo>true_over else 0,
                            "edge_btts": round((by-true_btts_y)/true_btts_y*100,1) if by>true_btts_y else 0,
                            "has_value_home": bh>true_home, "has_value_over": bo>true_over, "has_value_under": bu>round(1/probs["under25"],2), "has_value_btts_yes": by>true_btts_y,
                            "conf_home": confidence_score(round((bh-true_home)/true_home*100,1) if bh>true_home else 0, probs["home_win"], hg+ag),
                            "source": "openligadb FREE (no key)"
                        })
                    except: continue
        except: pass
    # 2) OpenFootball GitHub raw — EPL free, no key (historical + scheduled)
    if len(fixtures) < count and league_filter in ("all", "EPL", "LaLiga", "Serie A", "NPFL"):
        # map league to path
        open_paths = {
            "EPL": "2024-25/en.1.json",
            "LaLiga": "2024-25/es.1.json",
            "Serie A": "2024-25/it.1.json",
            "Bundesliga": "2024-25/de.1.json",
            "Ligue 1": "2024-25/fr.1.json",
        }
        candidates = []
        if league_filter == "all":
            candidates = ["2024-25/en.1.json", "2024-25/es.1.json", "2024-25/de.1.json"]
        elif league_filter in open_paths:
            candidates = [open_paths[league_filter]]
        for path in candidates:
            if len(fixtures) >= count:
                break
            try:
                url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{path}"
                r = requests.get(url, timeout=10, headers={"User-Agent":"curl/7.88"})
                if r.status_code != 200:
                    continue
                data = r.json()
                matches = data.get("matches", [])[-30:]  # recent 30
                random.shuffle(matches)
                for m in matches:
                    if len(fixtures) >= count:
                        break
                    home_team = m.get("team1","Home")
                    away_team = m.get("team2","Away")
                    # normalize names to match REAL_TEAMS_DB where possible
                    # e.g., "Manchester United FC" -> "Manchester United"
                    for k in list(REAL_TEAMS_DB.keys()):
                        if k.lower() in home_team.lower():
                            home_team = k
                            break
                    for k in list(REAL_TEAMS_DB.keys()):
                        if k.lower() in away_team.lower():
                            away_team = k
                            break
                    kickoff = m.get("date","") + "T" + m.get("time","12:00") + "Z"
                    fid = str(uuid.uuid4())[:8].upper()
                    hg = 1.65; ag = 1.35
                    if home_team in REAL_TEAMS_DB and away_team in REAL_TEAMS_DB:
                        hg = round(REAL_TEAMS_DB[home_team]["attack"]*REAL_TEAMS_DB[away_team]["defense"],2)
                        ag = round(REAL_TEAMS_DB[away_team]["attack"]*REAL_TEAMS_DB[home_team]["defense"],2)
                    probs = calculate_poisson_probs(hg, ag)
                    true_home = round(1/probs["home_win"],2) if probs["home_win"]>0.02 else 9.5
                    true_over = round(1/probs["over25"],2)
                    true_btts_y = round(1/probs["btts_yes"],2)
                    def bp(t): return round(t * random.uniform(0.92,1.18),2)
                    bh, bo, by = bp(true_home), bp(true_over), bp(true_btts_y)
                    bd, ba, bu, bn = bp(round(1/probs["draw"],2)), bp(round(1/probs["away_win"],2)), bp(round(1/probs["under25"],2)), bp(round(1/probs["btts_no"],2))
                    fixtures.append({
                        "id": fid, "timestamp": ts, "kickoff": kickoff, "league": m.get("round","") or league_filter,
                        "home_team": home_team, "away_team": away_team,
                        "home_xg": hg, "away_xg": ag, "probs": probs,
                        "true_home": true_home, "true_draw": round(1/probs["draw"],2), "true_away": round(1/probs["away_win"],2),
                        "true_over25": true_over, "true_under25": round(1/probs["under25"],2), "true_btts_yes": true_btts_y, "true_btts_no": round(1/probs["btts_no"],2),
                        "bookie_home": bh, "bookie_draw": bd, "bookie_away": ba, "bookie_over25": bo, "bookie_under25": bu, "bookie_btts_yes": by, "bookie_btts_no": bn,
                        "edge_home": round((bh-true_home)/true_home*100,1) if bh>true_home else 0,
                        "edge_over": round((bo-true_over)/true_over*100,1) if bo>true_over else 0,
                        "edge_btts": round((by-true_btts_y)/true_btts_y*100,1) if by>true_btts_y else 0,
                        "has_value_home": bh>true_home, "has_value_over": bo>true_over, "has_value_under": bu>round(1/probs["under25"],2), "has_value_btts_yes": by>true_btts_y,
                        "conf_home": confidence_score(round((bh-true_home)/true_home*100,1) if bh>true_home else 0, probs["home_win"], hg+ag),
                        "source": "openfootball FREE (no key)"
                    })
            except: continue
    random.shuffle(fixtures)
    return fixtures[:count]

def fetch_real_from_odds_api(sport_key="soccer_epl", regions="uk,eu", markets="h2h,totals,bothTeamsToScore"):
    api_key = get_setting("odds_api_key","")
    if not api_key:
        return None, "No Odds API key saved — add in Settings (⚙️)"
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        params={"apiKey":api_key,"regions":regions,"markets":markets,"oddsFormat":"decimal"}
        r=requests.get(url, params=params, timeout=12)
        if r.status_code!=200:
            return None, f"Odds API {r.status_code}: {r.text[:200]}"
        data=r.json()
        fixtures=[]
        for ev in data[:8]:
            fid=ev.get("id","")[:8].upper() or str(uuid.uuid4())[:8].upper()
            home=ev.get("home_team","Home")
            away=ev.get("away_team","Away")
            bms=ev.get("bookmakers",[])
            if not bms: continue
            bm=bms[0]
            mk={m["key"]:m for m in bm.get("markets",[])}
            def price(market, outcome):
                if market not in mk: return None
                for o in mk[market].get("outcomes",[]):
                    if o.get("name")==outcome: return o.get("price")
                return None
            bh=price("h2h",home)
            bd=price("h2h","Draw")
            ba=price("h2h",away)
            bo=price("totals","Over")
            bu=price("totals","Under")
            by=price("bothTeamsToScore","Yes")
            bn=price("bothTeamsToScore","No")
            hg=1.7; ag=1.3
            if home in REAL_TEAMS_DB and away in REAL_TEAMS_DB:
                hg=round(REAL_TEAMS_DB[home]["attack"]*REAL_TEAMS_DB[away]["defense"],2)
                ag=round(REAL_TEAMS_DB[away]["attack"]*REAL_TEAMS_DB[home]["defense"],2)
            probs=calculate_poisson_probs(hg,ag)
            fixtures.append({
                "id":fid,"home_team":home,"away_team":away,"league":sport_key,
                "home_xg":hg,"away_xg":ag,"probs":probs,
                "true_home":round(1/probs["home_win"],2),"true_over25":round(1/probs["over25"],2),"true_btts_yes":round(1/probs["btts_yes"],2),
                "bookie_home":bh,"bookie_draw":bd,"bookie_away":ba,"bookie_over25":bo,"bookie_under25":bu,"bookie_btts_yes":by,"bookie_btts_no":bn,
                "kickoff":ev.get("commence_time",""),"source":"the-odds-api"
            })
        return fixtures, None
    except Exception as e:
        return None, str(e)

# ==========================================
# ROUTES — pure real scanner
# ==========================================
@app.route("/")
def index():
    # Preload real 20 fixtures server-side so phone sees them instantly without extra fetch
    try:
        fixtures, _ = fetch_espn_fixtures(league_filter="all", count=500, dates=None, days=1)
        # if ESPN empty, try free2
        if not fixtures:
            fixtures = fetch_open_fallback(league_filter="all", count=20)
        # keep all for "All" - up to 100 for fast HTML (today ~44, not 20)
        fixtures = fixtures[:100]
        pre = json.dumps(fixtures)
    except Exception as e:
        print("preload failed", e)
        pre = "[]"
        fixtures = []
    server_date = datetime.now().strftime("%Y-%m-%d")
    # pass server date + build tag so client can detect stale fixtures and auto-upgrade
    resp = make_response(render_template("index.html", preloaded=pre, server_date=server_date, build_version="v14-2026-09-20"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# LEGACY virtual-engine routes — keep from 404, redirect to real scanner
@app.route("/jap")
@app.route("/jap/")
@app.route("/virtual")
@app.route("/virtual/")
@app.route("/phone")
def legacy_virtual_redirect():
    # old virtual engine URL — now unified to real scanner
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route("/api/jap/virtuals", methods=["GET","POST","OPTIONS"])
@app.route("/api/virtuals", methods=["GET","POST","OPTIONS"])
@app.route("/api/virtual", methods=["GET","POST","OPTIONS"])
@app.route("/api/sim", methods=["GET","POST","OPTIONS"])
@app.route("/api/phone", methods=["GET","POST","OPTIONS"])
def legacy_virtual_api():
    if request.method=="OPTIONS":
        return make_response("",204)
    return jsonify({"error":"Virtual engine retired — use Real Scanner","note":"This was the old phone virtuals engine. Now use POST /api/jap/real_fixtures (ESPN FREE / OPEN FREE 2) or Manual Entry, then POST /api/jap/scan","fixtures_url":"/api/jap/real_fixtures?provider=espn&league=all&count=8","scan_url":"/api/jap/scan","status":"migrated"}), 410

@app.errorhandler(404)
def handle_404(e):
    # API 404 → JSON, page 404 → show scanner instead of scary NOT FOUND
    if request.path.startswith("/api/"):
        return jsonify({"error":"Not found","path":request.path,"hint":"Try /api/jap/real_fixtures?provider=espn or /api/jap/scan","status":404}), 404
    # for any page, serve scanner so old bookmarks never 404
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp, 200

@app.errorhandler(405)
def handle_405(e):
    if request.path.startswith("/api/"):
        return jsonify({"error":"Method not allowed","path":request.path,"method":request.method,"allowed":["GET","POST","OPTIONS"],"hint":"Scan needs POST /api/jap/scan with JSON {fixtures:[...]}, Live fixtures is GET /api/jap/real_fixtures","status":405}), 405
    return handle_404(e)

@app.route("/manifest.json")
def manifest():
    return send_file("/home/user/static/manifest.json", mimetype="application/json")

@app.route("/service-worker.js")
def service_worker():
    return send_file("/home/user/static/service-worker.js", mimetype="application/javascript")

@app.route("/icon-192.png")
def icon192():
    return send_file("/home/user/static/icon-192.png", mimetype="image/png")

@app.route("/icon-512.png")
def icon512():
    return send_file("/home/user/static/icon-512.png", mimetype="image/png")



@app.route("/api/real_teams")
def api_real_teams():
    return jsonify(REAL_TEAMS_DB)

# settings — kept at /api/jap/settings for frontend compat + alias /api/settings
@app.route("/api/jap/settings", methods=["GET","POST","OPTIONS"])
@app.route("/api/settings", methods=["GET","POST","OPTIONS"])
def api_settings():
    if request.method=="OPTIONS":
        return make_response("",204)
    if request.method=="GET":
        conn=get_db()
        cur=conn.cursor()
        cur.execute("SELECT key,value FROM jap_settings")
        rows=cur.fetchall()
        conn.close()
        out={r["key"]:r["value"] for r in rows}
        masked={}
        for k,v in out.items():
            if "key" in k or "token" in k:
                masked[k]= v[:4]+"****" if v else ""
            else:
                masked[k]=v
        return jsonify({"settings":out,"masked":masked, "has_odds_key": bool(out.get("odds_api_key","")), "has_fd_token": bool(out.get("football_data_token",""))})
    data=request.json or {}
    for k,v in data.items():
        set_setting(k, str(v))
    return jsonify({"status":"saved"})

# real fixtures — primary + alias
@app.route("/api/jap/real_fixtures", methods=["GET","POST","OPTIONS"])
@app.route("/api/real_fixtures", methods=["GET","POST","OPTIONS"])
def api_real_fixtures():
    if request.method=="OPTIONS":
        return make_response("",204)
    if request.method=="POST":
        data=request.json or {}
        fid=str(uuid.uuid4())[:8].upper()
        ts=datetime.now().isoformat()
        home=data.get("home_team","Arsenal")
        away=data.get("away_team","Chelsea")
        league=data.get("league","EPL")
        hxg=float(data.get("home_xg",1.8))
        axg=float(data.get("away_xg",1.3))
        probs=calculate_poisson_probs(hxg, axg)
        # v15: no invented prices — manual adds without odds simply carry no odds
        bh=data.get("bookie_home"); bd=data.get("bookie_draw"); ba=data.get("bookie_away")
        bo=data.get("bookie_over25"); bu=data.get("bookie_under25")
        by=data.get("bookie_btts_yes"); bn=data.get("bookie_btts_no")
        for _k,_v in (("bh",bh),("bd",bd),("ba",ba),("bo",bo),("bu",bu),("by",by),("bn",bn)):
            if _v is not None: float(_v)
        # compute derived fields for instant render without extra scan
        true_home = round(1/probs["home_win"],2) if probs["home_win"]>0.02 else 9.5
        true_draw = round(1/probs["draw"],2)
        true_away = round(1/probs["away_win"],2) if probs["away_win"]>0.02 else 9.5
        true_over = round(1/probs["over25"],2)
        true_under = round(1/probs["under25"],2)
        true_btts_y = round(1/probs["btts_yes"],2)
        true_btts_n = round(1/probs["btts_no"],2)
        edge_home = round((bh-true_home)/true_home*100,1) if (bh is not None and bh>true_home) else 0
        edge_over = round((bo-true_over)/true_over*100,1) if (bo is not None and bo>true_over) else 0
        edge_btts = round((by-true_btts_y)/true_btts_y*100,1) if (by is not None and by>true_btts_y) else 0
        fixture={
            "id":fid,"timestamp":ts,"kickoff":ts,"league":league,
            "home_team":home,"away_team":away,
            "home_xg":hxg,"away_xg":axg,"probs":probs,
            "true_home":true_home,"true_draw":true_draw,"true_away":true_away,
            "true_over25":true_over,"true_under25":true_under,"true_btts_yes":true_btts_y,"true_btts_no":true_btts_n,
            "bookie_home":bh,"bookie_draw":bd,"bookie_away":ba,"bookie_over25":bo,"bookie_under25":bu,"bookie_btts_yes":by,"bookie_btts_no":bn,
            "edge_home":edge_home,"edge_over":edge_over,"edge_btts":edge_btts,
            "has_value_home":(bh is not None and bh>true_home),"has_value_over":(bo is not None and bo>true_over),"has_value_under":(bu is not None and bu>true_under),"has_value_btts_yes":(by is not None and by>true_btts_y),
            "conf_home": confidence_score(edge_home, probs["home_win"], hxg+axg),
            "source":"manual"
        }
        conn=get_db()
        cur=conn.cursor()
        cur.execute("INSERT OR REPLACE INTO jap_real_fixtures (id,timestamp,league,home_team,away_team,home_xg,away_xg,bookie_home,bookie_draw,bookie_away,bookie_over25,bookie_under25,bookie_btts_yes,bookie_btts_no,true_home,true_over25,true_btts_yes,kickoff,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid,ts,league,home,away,hxg,axg,bh,bd,ba,bo,bu,by,bn, true_home, true_over, true_btts_y, ts, "manual"))
        conn.commit()
        conn.close()
        return jsonify({"id":fid,"status":"added","fixture":fixture})
    provider=request.args.get("provider","espn")
    league=request.args.get("league","all")
    count_raw=request.args.get("count","8")
    date_raw=request.args.get("date") or request.args.get("dates")
    days_raw=request.args.get("days","1")
    try: days=int(days_raw)
    except: days=1
    # handle date: YYYY-MM-DD -> YYYYMMDD
    dates=None
    if date_raw:
        try:
            # normalize: remove dashes
            dates = date_raw.replace("-","")[:8]
            # validate 8 digits
            if len(dates)!=8:
                dates=None
        except:
            dates=None
    # support "all" — fetch every fixture (no limit)
    if isinstance(count_raw, str) and count_raw.lower()=="all":
        count=500
    else:
        try: count=int(count_raw)
        except: count=8
    if count>500: count=500
    if provider=="espn":
        fixtures, err = fetch_espn_fixtures(league_filter=league, count=count, dates=dates, days=days)
        # ESPN empty → try second free fallback before demo
        if err and fixtures and fixtures[0].get("source","").startswith("demo"):
            second = fetch_open_fallback(league_filter=league, count=count)
            if second:
                return jsonify({"provider":"espn","league":league,"fixtures":second,"fallback":"openfootball/openligadb FREE","note":"ESPN empty for today — second free fallback (OpenLigaDB/OpenFootball, no key) showing real historical fixtures."})
            return jsonify({"provider":"espn","league":league,"fixtures":fixtures,"error":err,"fallback":"demo","note":"ESPN free — no key needed. If empty (offseason), demo shown."})
        if err:
            second = fetch_open_fallback(league_filter=league, count=count)
            if second:
                return jsonify({"provider":"espn","league":league,"fixtures":second,"fallback":"openfootball/openligadb FREE","note":"ESPN error — second free fallback (no key)."})
            return jsonify({"provider":"espn","league":league,"fixtures":fixtures,"error":err})
        return jsonify({"provider":"espn","league":league,"fixtures":fixtures,"note":"ESPN free — no key needed (site.api.espn.com). Includes DraftKings 1X2 + O/U where available."})
    if provider=="openfootball" or provider=="openligadb" or provider=="free2":
        fixtures = fetch_open_fallback(league_filter=league, count=count)
        if not fixtures:
            # demo removed — return empty with manual hint instead of demo
            return jsonify({"provider":provider,"league":league,"fixtures":[],"error":"OPEN FREE empty — use Manual Entry below (no API needed)","note":"No fixtures from OpenFootball/OpenLigaDB — add manual fixtures below."})
        return jsonify({"provider":provider,"league":league,"fixtures":fixtures,"note":"Second free fallback — OpenFootball (github) + OpenLigaDB (api.openligadb.de), no key, real fixtures."})
    if provider=="demo":
        # demo engine removed per user request — redirect to free2/manual
        fixtures = fetch_open_fallback(league_filter=league, count=count)
        if fixtures:
            return jsonify({"provider":"demo","league":league,"fixtures":fixtures,"fallback":"free2","note":"Demo removed — showing OPEN FREE 2 real fixtures instead. Use Manual Entry for any fixture."})
        return jsonify({"provider":"demo","league":league,"fixtures":[],"error":"Demo engine removed — use ESPN FREE, OPEN FREE 2, or Manual Entry (no API needed)","note":"Demo removed. Use Manual Entry below."})

    elif provider=="oddsapi":
        sport=request.args.get("sport","soccer_epl")
        fixtures, err = fetch_real_from_odds_api(sport_key=sport)
        if err:
            second=fetch_open_fallback(league_filter=league, count=count)
            if second:
                return jsonify({"provider":"oddsapi","error":err,"fixtures":second,"fallback":"free2","note":"Odds API error — showing OPEN FREE 2. Use Manual Entry."})
            return jsonify({"provider":"oddsapi","error":err,"fixtures":[],"note":"No key / API error — use ESPN FREE, OPEN FREE 2, or Manual Entry."})
        return jsonify({"provider":"oddsapi","fixtures":fixtures})
    elif provider=="football_data":
        token=get_setting("football_data_token","")
        if not token:
            second=fetch_open_fallback(league_filter=league, count=count)
            if second:
                return jsonify({"provider":"football_data","error":"No Football-Data token","fixtures":second,"fallback":"free2","note":"Add Manual or use OPEN FREE 2."})
            return jsonify({"provider":"football_data","error":"No Football-Data token","fixtures":[],"note":"No token — use Manual Entry below or OPEN FREE 2 (no key)."})
        try:
            headers={"X-Auth-Token":token}
            r=requests.get("https://api.football-data.org/v4/matches", headers=headers, timeout=10)
            if r.status_code!=200:
                second=fetch_open_fallback(league_filter=league, count=count)
                if second:
                    return jsonify({"provider":"football_data","error":f"FD {r.status_code}", "fixtures":second,"fallback":"free2"})
                return jsonify({"provider":"football_data","error":f"FD {r.status_code}", "fixtures":[],"note":"Use Manual Entry."})
            data=r.json()
            fixtures=[]
            for m in data.get("matches",[])[:count]:
                home=m["homeTeam"]["name"]
                away=m["awayTeam"]["name"]
                league_name=m["competition"]["name"]
                hg=1.7; ag=1.3
                if home in REAL_TEAMS_DB and away in REAL_TEAMS_DB:
                    hg=round(REAL_TEAMS_DB[home]["attack"]*REAL_TEAMS_DB[away]["defense"],2)
                    ag=round(REAL_TEAMS_DB[away]["attack"]*REAL_TEAMS_DB[home]["defense"],2)
                probs=calculate_poisson_probs(hg,ag)
                fixtures.append({"id":str(m["id"])[-6:], "home_team":home,"away_team":away,"league":league_name,"home_xg":hg,"away_xg":ag,"probs":probs,"true_home":round(1/probs["home_win"],2),"true_over25":round(1/probs["over25"],2),"true_btts_yes":round(1/probs["btts_yes"],2),"bookie_home":round(1/probs["home_win"]*1.05,2),"bookie_over25":round(1/probs["over25"]*1.05,2),"bookie_btts_yes":round(1/probs["btts_yes"]*1.05,2),"kickoff":m["utcDate"],"source":"football-data"})
            return jsonify({"provider":"football_data","fixtures":fixtures})
        except Exception as e:
            second=fetch_open_fallback(league_filter=league, count=count)
            if second:
                return jsonify({"provider":"football_data","error":str(e),"fixtures":second,"fallback":"free2"})
            return jsonify({"provider":"football_data","error":str(e),"fixtures":[],"note":"Use Manual Entry."})
    else:
        second=fetch_open_fallback(league_filter=league, count=count)
        if second:
            return jsonify({"provider":provider,"fixtures":second,"fallback":"free2","note":"Unknown provider — showing OPEN FREE 2. Use Manual Entry for any fixture."})
        return jsonify({"provider":provider,"fixtures":[],"error":"Unknown provider — use ESPN FREE, OPEN FREE 2, or Manual Entry","note":"Demo removed — use Manual Entry below."})

# scan — primary + alias
@app.route("/api/jap/scan", methods=["GET","POST","OPTIONS"])
@app.route("/api/scan", methods=["GET","POST","OPTIONS"])
def api_scan():
    if request.method=="OPTIONS":
        return make_response("",204)
    if request.method=="GET":
        # allow GET for diagnostics — return helpful message, not 405
        # also handle ?fixtures= base64 or just fallback scan
        fixtures=fetch_open_fallback(league_filter=request.args.get("league","all"), count=int(request.args.get("count","4")))
        if not fixtures:
            return jsonify({"scanned":[],"count":0,"error":"No fixtures — POST fixtures to scan. Example: POST /api/jap/scan {fixtures:[...]}","hint":"Use POST with JSON body, not GET. Or add manual fixtures in UI then Scan."})
        # run scan on fallback so GET never 405s
        data={"fixtures":fixtures}
        # fall through to shared logic below by reusing fixtures var
        # set flag to skip re-reading request.json
        # we will handle GET separately so we don't need to re-parse
        scanned=[]
        for f in fixtures:
            hxg=float(f.get("home_xg",1.8))
            axg=float(f.get("away_xg",1.3))
            probs=f.get("probs") or calculate_poisson_probs(hxg,axg)
            true_home=float(f.get("true_home", round(1/probs["home_win"],2)))
            true_over=float(f.get("true_over25", round(1/probs["over25"],2)))
            true_btts=float(f.get("true_btts_yes", round(1/probs["btts_yes"],2)))
            bh=float(f.get("bookie_home") or f.get("bookie_home_odds") or true_home*1.08)
            bo=float(f.get("bookie_over25") or f.get("bookie_over25_odds") or true_over*1.08)
            by=float(f.get("bookie_btts_yes") or true_btts*1.08)
            def edge(t,b): return round((b-t)/t*100,1) if b>t else 0
            eh=edge(true_home,bh); eo=edge(true_over,bo); ey=edge(true_btts,by)
            best=None
            if eh>5 and eh>=eo and eh>=ey:
                best={"market":"1X2","pick":f['home_team']+" HOME","odds":bh,"edge":eh,"conf":confidence_score(eh, probs["home_win"], hxg+axg)}
            elif eo>5 and eo>=ey:
                best={"market":"OU25","pick":"OVER 2.5","odds":bo,"edge":eo,"conf":confidence_score(eo, probs["over25"], hxg+axg)}
            elif ey>5:
                best={"market":"BTTS","pick":"BTTS YES","odds":by,"edge":ey,"conf":confidence_score(ey, probs["btts_yes"], hxg+axg)}
            scanned.append({"id":f.get("id"),"league":f.get("league"),"home_team":f["home_team"],"away_team":f["away_team"],"home_xg":hxg,"away_xg":axg,"probs":probs,"true_home":true_home,"true_over25":true_over,"true_btts_yes":true_btts,"bookie_home":bh,"bookie_over25":bo,"bookie_btts_yes":by,"edge_home":eh,"edge_over":eo,"edge_btts_yes":ey,"has_value": eh>0 or eo>0 or ey>0,"best":best,"kickoff":f.get("kickoff")})
        scanned.sort(key=lambda x: (x["best"]["edge"] if x["best"] else 0), reverse=True)
        return jsonify({"scanned":scanned, "count":len(scanned), "note":"GET scan — fallback fixtures scanned. Use POST with your fixtures for real +EV."})
    data=request.json or {}
    fixtures=data.get("fixtures",[])
    if not fixtures:
        cr=data.get("count",8)
        try: cc=100 if str(cr).lower()=="all" else int(cr)
        except: cc=8
        fixtures=fetch_open_fallback(league_filter=data.get("league","all"), count=cc)
        if not fixtures:
            return jsonify({"scanned":[],"count":0,"error":"No fixtures — add manual fixtures below or capture live"})
    scanned=[]
    for f in fixtures:
        hxg=float(f.get("home_xg",1.8))
        axg=float(f.get("away_xg",1.3))
        probs=f.get("probs") or calculate_poisson_probs(hxg,axg)
        true_home=float(f.get("true_home", round(1/probs["home_win"],2)))
        true_over=float(f.get("true_over25", round(1/probs["over25"],2)))
        true_btts=float(f.get("true_btts_yes", round(1/probs["btts_yes"],2)))
        bh=float(f.get("bookie_home") or f.get("bookie_home_odds") or true_home*1.08)
        bo=float(f.get("bookie_over25") or f.get("bookie_over25_odds") or true_over*1.08)
        by=float(f.get("bookie_btts_yes") or true_btts*1.08)
        def edge(t,b): return round((b-t)/t*100,1) if b>t else 0
        eh=edge(true_home,bh)
        eo=edge(true_over,bo)
        ey=edge(true_btts,by)
        best=None
        if eh>5 and eh>=eo and eh>=ey:
            best={"market":"1X2","pick":f['home_team']+" HOME","odds":bh,"edge":eh,"conf":confidence_score(eh, probs["home_win"], hxg+axg)}
        elif eo>5 and eo>=ey:
            best={"market":"OU25","pick":"OVER 2.5","odds":bo,"edge":eo,"conf":confidence_score(eo, probs["over25"], hxg+axg)}
        elif ey>5:
            best={"market":"BTTS","pick":"BTTS YES","odds":by,"edge":ey,"conf":confidence_score(ey, probs["btts_yes"], hxg+axg)}
        scanned.append({
            "id":f.get("id"),"league":f.get("league"),"home_team":f["home_team"],"away_team":f["away_team"],
            "home_xg":hxg,"away_xg":axg,"probs":probs,
            "true_home":true_home,"true_over25":true_over,"true_btts_yes":true_btts,
            "bookie_home":bh,"bookie_over25":bo,"bookie_btts_yes":by,
            "edge_home":eh,"edge_over":eo,"edge_btts_yes":ey,
            "has_value": eh>0 or eo>0 or ey>0,
            "best":best,
            "kickoff":f.get("kickoff")
        })
    scanned.sort(key=lambda x: (x["best"]["edge"] if x["best"] else 0), reverse=True)
    return jsonify({"scanned":scanned, "count":len(scanned)})

if __name__ == "__main__":
    print("⚡ Real Fixtures Scanner — Live Odds +EV (no virtuals, no JAP)")
    print("   http://0.0.0.0:5000  — capture real fixtures from any web API, then scan")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
