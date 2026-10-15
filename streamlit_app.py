import streamlit as st
import streamlit.components.v1 as components
import requests
import time
from datetime import datetime, timezone, timedelta

st.set_page_config(
    page_title="Метеостанция — Роза ветров",
    layout="wide",
    initial_sidebar_state="collapsed",
)

API_BASE = "https://dev.rightech.io"
TOKEN = st.secrets.get("RIGHTECH_TOKEN", "")
OBJECT_ID = st.secrets.get("OBJECT_ID", "")
PARAM_DIR = "windDirection"
PARAM_SPEED = "windSpeed"
PARAM_TEMP = "temperature"
PARAM_PRESS = "pressure"
PARAM_HUM = "humidity"
REFRESH_SEC = 10


def api_get(path):
    r = requests.get(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
        timeout=25,
    )
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    try:
        return r.json(), None
    except Exception as e:
        return None, f"bad json: {e}"


def find_deep(obj, key, depth=0):
    if obj is None or depth > 8:
        return None
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                import json
                return find_deep(json.loads(s), key, depth + 1)
            except Exception:
                return None
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_deep(v, key, depth + 1)
            if r is not None:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = find_deep(v, key, depth + 1)
            if r is not None:
                return r
    return None


def fetch_current():
    data, err = api_get(f"/api/v1/objects/{OBJECT_ID}")
    if err:
        return None, err
    packet = data.get("state") if isinstance(data, dict) and "state" in data else data
    return {
        "dir": find_deep(packet, PARAM_DIR),
        "speed": find_deep(packet, PARAM_SPEED),
        "temp": find_deep(packet, PARAM_TEMP),
        "press": find_deep(packet, PARAM_PRESS),
        "hum": find_deep(packet, PARAM_HUM),
    }, None


def fetch_history(hours=6, limit=1000):
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=hours)
    fmt = "%Y-%m-%dT%H:%M"
    path = (
        f"/api/v1/objects/{OBJECT_ID}/packets"
        f"?limit={limit}&from={from_dt.strftime(fmt)}&to={to_dt.strftime(fmt)}"
    )
    data, err = api_get(path)
    if err or not isinstance(data, list):
        return []
    rows = []
    for p in data:
        if not isinstance(p, dict):
            continue
        t_raw = p.get("time") or p.get("_ts") or p.get("timestamp")
        t_ms = None
        if isinstance(t_raw, (int, float)):
            t_ms = int(t_raw if t_raw > 1e11 else t_raw * 1000)
        elif isinstance(t_raw, str):
            try:
                t_ms = int(datetime.fromisoformat(t_raw.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                pass
        if t_ms is None:
            continue
        rows.append({
            "t": t_ms,
            "temp": find_deep(p, PARAM_TEMP),
            "dir": find_deep(p, PARAM_DIR),
            "speed": find_deep(p, PARAM_SPEED),
            "press": find_deep(p, PARAM_PRESS),
            "hum": find_deep(p, PARAM_HUM),
        })
    rows.sort(key=lambda r: r["t"])
    return rows


def build_html(cur, hist):
    import json
    cur_json = json.dumps(cur or {})
    hist_json = json.dumps(hist or [])
    return f"""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
  body {{ margin:0; background:#0f1420; color:#e8edf7;
         font:14px "Segoe UI", Roboto, Arial, sans-serif; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; padding:14px; }}
  .card {{ background:linear-gradient(180deg,#141b2b,#0e1421); border-radius:16px;
          box-shadow:0 12px 32px rgba(0,0,0,.4), 0 0 0 1px rgba(255,255,255,.05);
          padding:14px; }}
  .title {{ font-size:11px; letter-spacing:.14em; text-transform:uppercase;
           color:#8b9ab8; margin-bottom:8px; }}
  .chart-wrap {{ position:relative; width:100%; aspect-ratio:1000/260; }}
  .chart-wrap svg {{ position:absolute; inset:0; width:100%; height:100%; }}
  .last {{ font-size:22px; font-weight:700; color:#ffb020; }}
  .status {{ text-align:center; color:#8b9ab8; font-size:12px; padding:6px; }}
</style>
</head>
<body>
<div class="grid">
  <div class="card">
    <div class="title">Направление ветра</div>
    <div id="compass" style="position:relative;width:100%;aspect-ratio:1/1;"></div>
  </div>
  <div class="card">
    <div class="title">Скорость ветра</div>
    <div id="speed" style="position:relative;width:100%;aspect-ratio:1/1;"></div>
  </div>
  <div class="card" style="grid-column:1/-1;">
    <div class="title">Температура · последние 6 часов</div>
    <div class="chart-wrap"><svg id="tempSvg" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg></div>
    <div class="last" id="tempLast" style="text-align:right">—<span style="font-size:.55em;color:#8b9ab8">°C</span></div>
  </div>
</div>
<div class="status" id="status">Данные Rightech</div>

<script>
const CUR = {cur_json};
const HIST = {hist_json};

function drawCompass(angle) {{
  const el = document.getElementById("compass");
  if (!el) return;
  const W = 400, H = 400, cx = 200, cy = 200, R = 160;
  const a = ((Number(angle) || 0) - 90) * Math.PI / 180;
  const x = cx + (R - 40) * Math.cos(a);
  const y = cy + (R - 40) * Math.sin(a);
  el.innerHTML = `
    <svg viewBox="0 0 ${{W}} ${{H}}" style="width:100%;height:100%">
      <circle cx="${{cx}}" cy="${{cy}}" r="${{R}}" fill="none" stroke="#2a3550" stroke-width="10"/>
      <text x="${{cx}}" y="40" fill="#ff6b6b" font-size="22" text-anchor="middle" font-weight="700">С</text>
      <text x="${{cx}}" y="${{H-20}}" fill="#e8edf7" font-size="22" text-anchor="middle" font-weight="700">Ю</text>
      <text x="30" y="${{cy+8}}" fill="#e8edf7" font-size="22" text-anchor="middle" font-weight="700">З</text>
      <text x="${{W-30}}" y="${{cy+8}}" fill="#e8edf7" font-size="22" text-anchor="middle" font-weight="700">В</text>
      <line x1="${{cx}}" y1="${{cy}}" x2="${{x}}" y2="${{y}}" stroke="#ffb020" stroke-width="6" stroke-linecap="round"/>
      <circle cx="${{cx}}" cy="${{cy}}" r="10" fill="#ffb020"/>
      <text x="${{cx}}" y="${{cy-25}}" fill="#ffb020" font-size="42" font-weight="700" text-anchor="middle">${{Math.round(Number(angle)||0)}}°</text>
    </svg>`;
}}

function drawSpeed(v) {{
  const el = document.getElementById("speed");
  if (!el) return;
  const W = 400, H = 400, cx = 200, cy = 280, R = 160;
  const max = 50;
  const val = Math.max(0, Math.min(max, Number(v) || 0));
  const start = -110, end = 110;
  const deg = start + (val / max) * (end - start);
  const polar = (d, r) => {{
    const a = (d - 90) * Math.PI / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }};
  const [x1, y1] = polar(start, R);
  const [x2, y2] = polar(end, R);
  const [nx, ny] = polar(deg, R - 20);
  el.innerHTML = `
    <svg viewBox="0 0 ${{W}} ${{H}}" style="width:100%;height:100%">
      <path d="M ${{x1}} ${{y1}} A ${{R}} ${{R}} 0 1 1 ${{x2}} ${{y2}}" fill="none" stroke="#2a3550" stroke-width="14" stroke-linecap="round"/>
      <line x1="${{cx}}" y1="${{cy}}" x2="${{nx}}" y2="${{ny}}" stroke="#ffb020" stroke-width="6" stroke-linecap="round"/>
      <circle cx="${{cx}}" cy="${{cy}}" r="12" fill="#ffb020"/>
      <text x="${{cx}}" y="${{cy-30}}" fill="#ffb020" font-size="54" font-weight="700" text-anchor="middle">${{val.toFixed(1)}}</text>
      <text x="${{cx}}" y="${{cy+30}}" fill="#8b9ab8" font-size="16" text-anchor="middle">м/с</text>
    </svg>`;
}}

function drawChart(rows) {{
  const svg = document.getElementById("tempSvg");
  if (!svg) return;
  if (!rows || rows.length < 2) {{
    svg.innerHTML = '<text x="500" y="130" fill="#5b6b8e" font-size="16" text-anchor="middle">нет данных</text>';
    return;
  }}
  const pts = rows.filter(r => r.temp !== null && r.temp !== undefined);
  if (pts.length < 2) {{
    svg.innerHTML = '<text x="500" y="130" fill="#5b6b8e" font-size="16" text-anchor="middle">нет данных</text>';
    return;
  }}
  const W = 1000, H = 260, padL = 50, padR = 20, padT = 20, padB = 30;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  let vmin = Math.min(...pts.map(p=>+p.temp));
  let vmax = Math.max(...pts.map(p=>+p.temp));
  if (vmax - vmin < 1) {{ vmax += .5; vmin -= .5; }}
  const tmin = pts[0].t, tmax = pts[pts.length-1].t;
  const xOf = t => padL + (t - tmin) / (tmax - tmin) * plotW;
  const yOf = v => padT + (1 - (v - vmin) / (vmax - vmin)) * plotH;
  let grid = "";
  for (let i = 0; i <= 5; i++) {{
    const v = vmin + i/5*(vmax-vmin);
    const y = yOf(v);
    grid += `<line x1="${{padL}}" y1="${{y}}" x2="${{W-padR}}" y2="${{y}}" stroke="#233052"/>`;
    grid += `<text x="${{padL-8}}" y="${{y}}" fill="#8b9ab8" font-size="12" text-anchor="end" dominant-baseline="middle">${{v.toFixed(1)}}°</text>`;
  }}
  const line = pts.map(p => `${{xOf(p.t).toFixed(1)}},${{yOf(+p.temp).toFixed(1)}}`).join(" ");
  const area = `${{padL}},${{H-padB}} ` + line + ` ${{W-padR}},${{H-padB}}`;
  svg.innerHTML = `
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ff6b6b" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#ff6b6b" stop-opacity="0"/>
    </linearGradient></defs>
    ${{grid}}
    <polygon points="${{area}}" fill="url(#g)"/>
    <polyline points="${{line}}" fill="none" stroke="#ff6b6b" stroke-width="2.5" stroke-linejoin="round"/>
    <line x1="${{padL}}" y1="${{H-padB}}" x2="${{W-padR}}" y2="${{H-padB}}" stroke="#3b4d78"/>
  `;
  const last = pts[pts.length-1];
  document.getElementById("tempLast").innerHTML = `${{(+last.temp).toFixed(1)}}<span style="font-size:.55em;color:#8b9ab8">°C</span>`;
}}

drawCompass(CUR.dir);
drawSpeed(CUR.speed);
drawChart(HIST);
document.getElementById("status").textContent =
  `Обновлено: ${{new Date().toLocaleTimeString("ru-RU")}} · направление: ${{CUR.dir ?? "—"}}° · скорость: ${{CUR.speed ?? "—"}} м/с · температура: ${{CUR.temp ?? "—"}}°C`;
</script>
</body>
</html>
"""


st.markdown(
    """
    <style>
      .block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; }
      header[data-testid="stHeader"] { display: none; }
      #MainMenu { visibility: hidden; }
      footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

if not TOKEN or not OBJECT_ID:
    st.error(
        "Не заданы настройки. Откройте **Settings → Secrets** в Streamlit Cloud "
        "и добавьте:\n\n"
        "```\n"
        'RIGHTECH_TOKEN = "eyJ..."\n'
        'OBJECT_ID = "6aa9044eda123b3639ae3b5d"\n'
        "```"
    )
    st.stop()

cur, err = fetch_current()
if err:
    st.warning(f"Ошибка получения текущих данных: {err}")
    cur = {}

hist = fetch_history(hours=6, limit=1000)

components.html(build_html(cur, hist), height=1000, scrolling=True)

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()
if time.time() - st.session_state.last_refresh >= REFRESH_SEC:
    st.session_state.last_refresh = time.time()

time.sleep(REFRESH_SEC)
st.rerun()
