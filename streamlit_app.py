import streamlit as st
import streamlit.components.v1 as components
import requests
import json
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

# ---------------------------------------------------------------------------
# Python-прокси к Rightech
# ---------------------------------------------------------------------------
def api_get(path):
    try:
        r = requests.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
            timeout=25,
        )
    except Exception as e:
        return None, f"connection error: {e}"
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


def to_num(x):
    if x is None or x == "":
        return None
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def fetch_current():
    data, err = api_get(f"/api/v1/objects/{OBJECT_ID}")
    if err:
        return None, err
    packet = data.get("state") if isinstance(data, dict) and "state" in data else data
    return {
        "dir": to_num(find_deep(packet, PARAM_DIR)),
        "speed": to_num(find_deep(packet, PARAM_SPEED)),
        "temp": to_num(find_deep(packet, PARAM_TEMP)),
        "press": to_num(find_deep(packet, PARAM_PRESS)),
        "hum": to_num(find_deep(packet, PARAM_HUM)),
    }, None


def packet_time_ms(p):
    for k in ("time", "_ts", "timestamp", "ts", "t"):
        if k in p and p[k] is not None:
            v = p[k]
            if isinstance(v, (int, float)):
                return int(v if v > 1e11 else v * 1000)
            try:
                return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                pass
    return None


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
        t_ms = packet_time_ms(p)
        if t_ms is None:
            continue
        rows.append({
            "t": t_ms,
            "temp": to_num(find_deep(p, PARAM_TEMP)),
            "dir": to_num(find_deep(p, PARAM_DIR)),
            "speed": to_num(find_deep(p, PARAM_SPEED)),
            "press": to_num(find_deep(p, PARAM_PRESS)),
            "hum": to_num(find_deep(p, PARAM_HUM)),
        })
    rows.sort(key=lambda r: r["t"])
    return rows
# ---------------------------------------------------------------------------
# HTML виджета (тот же дизайн, но данные вшиты Python'ом)
# ---------------------------------------------------------------------------
WIDGET_HTML = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
  body{margin:0;background:#0f1420;color:#e8edf7;font:14px "Segoe UI",Roboto,Arial,sans-serif}
  .wrap{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:12px}
  .card{background:linear-gradient(180deg,#141b2b 0%,#0e1421 100%);border-radius:16px;
        box-shadow:0 16px 44px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.05);padding:12px}
  .card.full{grid-column:1/-1}
  .title{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#8b9ab8;margin-bottom:6px}
  .last{font-size:22px;font-weight:700;color:#ffb020;text-align:right;margin-top:-30px}
  .chart-wrap{position:relative;width:100%;aspect-ratio:1000/260}
  .chart-wrap svg{position:absolute;inset:0;width:100%;height:100%}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
  th{position:sticky;top:0;background:#182036;color:#8b9ab8;font-size:10px;letter-spacing:.1em;
     text-transform:uppercase;text-align:right;padding:8px 10px;white-space:nowrap}
  td{text-align:right;padding:6px 10px;border-top:1px solid rgba(255,255,255,.05)}
  th:first-child,td:first-child{text-align:left}
  td.temp,td.speed{color:#ffb020;font-weight:600}
  .scroll{max-height:340px;overflow:auto;border-radius:10px;box-shadow:0 0 0 1px rgba(255,255,255,.06)}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="title">Направление ветра</div>
    <div id="c" style="position:relative;width:100%;aspect-ratio:1"></div>
  </div>
  <div class="card">
    <div class="title">Скорость ветра</div>
    <div id="s" style="position:relative;width:100%;aspect-ratio:1"></div>
  </div>
  <div class="card full">
    <div class="title">Температура · последние 6 часов</div>
    <div class="chart-wrap"><svg id="chart" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg></div>
    <div class="last" id="tlast">—<small style="font-size:.55em;color:#8b9ab8">°C</small></div>
  </div>
  <div class="card full">
    <div class="title">Данные за 6 часов · <span id="info">нет данных</span></div>
    <div class="scroll"><table>
      <thead><tr>
        <th>Время</th><th>Темп., °C</th><th>Направление</th><th>Скор., м/с</th><th>Давл., гПа</th><th>Влажность, %</th>
      </tr></thead>
      <tbody id="tb"></tbody>
    </table></div>
  </div>
</div>
<script>
const CUR = window.__CUR__ || {};
const HIST = window.__HIST__ || [];
const RU = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"];

function drawCompass(a) {
  const el = document.getElementById("c");
  const W = 400, H = 400, cx = 200, cy = 200, R = 160;
  const deg = ((a||0) - 90) * Math.PI/180;
  const x = cx + (R-40) * Math.cos(deg);
  const y = cy + (R-40) * Math.sin(deg);
  let ticks = "";
  for (let d = 0; d < 360; d += 10) {
    const major = d % 90 === 0;
    const rad = (d-90)*Math.PI/180;
    const r1 = R - (major ? 16 : 8), r2 = R;
    const x1 = cx + r1*Math.cos(rad), y1 = cy + r1*Math.sin(rad);
    const x2 = cx + r2*Math.cos(rad), y2 = cy + r2*Math.sin(rad);
    const stroke = d===0 ? "#ff6b6b" : "#8b9ab8";
    const w = major ? 2.5 : 1.2;
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${stroke}" stroke-width="${w}" stroke-linecap="round"/>`;
  }
  const dirs = [["С",0],["СВ",45],["В",90],["ЮВ",135],["Ю",180],["ЮЗ",225],["З",270],["СЗ",315]];
  let labs = "";
  for (const [n, d] of dirs) {
    const rad = (d-90)*Math.PI/180;
    const tx = cx + (R-38)*Math.cos(rad);
    const ty = cy + (R-38)*Math.sin(rad);
    const single = n.length === 1;
    const fill = n === "С" ? "#ff6b6b" : (single ? "#e8edf7" : "#8b9ab8");
    labs += `<text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" fill="${fill}" font-size="${single?20:13}" font-weight="${single?700:500}" text-anchor="middle" dominant-baseline="middle">${n}</text>`;
  }
  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:100%">
      <defs>
        <linearGradient id="grad" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stop-color="#38d39f"/>
          <stop offset="0.6" stop-color="#ffb020"/>
          <stop offset="1" stop-color="#ff6b6b"/>
        </linearGradient>
      </defs>
      <circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="#2a3550" stroke-width="10"/>
      <circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="url(#grad)" stroke-width="4" opacity="0.55"/>
      ${ticks}${labs}
      <line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#ffb020" stroke-width="6" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="10" fill="#ffb020"/>
      <text x="${cx}" y="${cy-25}" fill="#ffb020" font-size="46" font-weight="700" text-anchor="middle">${Math.round(a||0)}°</text>
      <text x="${cx}" y="${cy+45}" fill="#8b9ab8" font-size="20" text-anchor="middle">${RU[Math.round((a||0)/22.5)%16]}</text>
    </svg>`;
}

function drawSpeed(v) {
  const el = document.getElementById("s");
  const W = 400, H = 400, cx = 200, cy = 300, R = 170;
  const max = 50, val = Math.max(0, Math.min(max, Number(v)||0));
  const START = -110, END = 110;
  const polar = (d, r) => { const rad = (d-90)*Math.PI/180; return [cx + r*Math.cos(rad), cy + r*Math.sin(rad)]; };
  const valToDeg = x => START + (x/max)*(END-START);
  let ticks = "";
  for (let t = 0; t <= max; t += 5) {
    const d = valToDeg(t), major = t % 10 === 0;
    const [x1, y1] = polar(d, R - (major?16:8));
    const [x2, y2] = polar(d, R);
    const stroke = t >= 30 ? "#ff6b6b" : "#8b9ab8";
    const w = major ? 2.4 : 1.2;
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${stroke}" stroke-width="${w}" stroke-linecap="round"/>`;
    if (major) {
      const [tx, ty] = polar(d, R-34);
      ticks += `<text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" fill="#c9d2e0" font-size="14" text-anchor="middle" dominant-baseline="middle">${t}</text>`;
    }
  }
  const [arc1x, arc1y] = polar(START, R);
  const [arc2x, arc2y] = polar(END, R);
  const [rx1, ry1] = polar(valToDeg(30), R-4);
  const [rx2, ry2] = polar(END, R-4);
  const [nx, ny] = polar(valToDeg(val), R-34);
  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:100%">
      <path d="M ${arc1x.toFixed(1)} ${arc1y.toFixed(1)} A ${R} ${R} 0 1 1 ${arc2x.toFixed(1)} ${arc2y.toFixed(1)}" fill="none" stroke="#2a3550" stroke-width="12" stroke-linecap="round"/>
      <path d="M ${rx1.toFixed(1)} ${ry1.toFixed(1)} A ${R-4} ${R-4} 0 0 1 ${rx2.toFixed(1)} ${ry2.toFixed(1)}" fill="none" stroke="#ff6b6b" stroke-width="6" stroke-linecap="round" opacity="0.85"/>
      ${ticks}
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="#ffb020" stroke-width="5" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="10" fill="#ffb020"/>
      <text x="${cx}" y="${cy-40}" fill="#ffb020" font-size="54" font-weight="700" text-anchor="middle">${val.toFixed(1)}</text>
      <text x="${cx}" y="${cy+28}" fill="#8b9ab8" font-size="18" text-anchor="middle">м/с</text>
    </svg>`;
}

function drawChart(rows) {
  const svg = document.getElementById("chart");
  const pts = rows.filter(r => r.temp !== null && r.temp !== undefined);
  if (pts.length < 2) {
    svg.innerHTML = '<text x="500" y="130" fill="#5b6b8e" font-size="16" text-anchor="middle">нет данных для графика</text>';
    document.getElementById("tlast").innerHTML = '—<small style="font-size:.55em;color:#8b9ab8">°C</small>';
    return;
  }
  const W = 1000, H = 260, padL = 50, padR = 20, padT = 20, padB = 30;
  const plotW = W-padL-padR, plotH = H-padT-padB;
  let vmin = Math.min(...pts.map(p=>+p.temp));
  let vmax = Math.max(...pts.map(p=>+p.temp));
  if (vmax - vmin < 1) { vmax += .5; vmin -= .5; }
  const pad = (vmax-vmin)*0.12; vmin -= pad; vmax += pad;
  const tmin = pts[0].t, tmax = pts[pts.length-1].t;
  const xOf = t => padL + (t-tmin)/(tmax-tmin)*plotW;
  const yOf = v => padT + (1-(v-vmin)/(vmax-vmin))*plotH;
  let grid = "";
  for (let i = 0; i <= 5; i++) {
    const v = vmin + i/5*(vmax-vmin);
    const y = yOf(v);
    grid += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W-padR}" y2="${y.toFixed(1)}" stroke="#233052"/>`;
    grid += `<text x="${padL-8}" y="${y.toFixed(1)}" fill="#8b9ab8" font-size="12" text-anchor="end" dominant-baseline="middle">${v.toFixed(1)}°</text>`;
  }
  const line = pts.map(p => `${xOf(p.t).toFixed(1)},${yOf(+p.temp).toFixed(1)}`).join(" ");
  const area = `${padL},${H-padB} ` + line + ` ${W-padR},${H-padB}`;
  const fmtT = t => { const d = new Date(t); return d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"}); };
  svg.innerHTML = `
    <defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ff6b6b" stop-opacity="0.4"/>
      <stop offset="1" stop-color="#ff6b6b" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}
    <polygon points="${area}" fill="url(#tg)"/>
    <polyline points="${line}" fill="none" stroke="#ff6b6b" stroke-width="2.5" stroke-linejoin="round"/>
    <line x1="${padL}" y1="${H-padB}" x2="${W-padR}" y2="${H-padB}" stroke="#3b4d78"/>
    <text x="${padL}" y="${H-8}" fill="#8b9ab8" font-size="12" text-anchor="start">${fmtT(tmin)}</text>
    <text x="${(padL+W-padR)/2}" y="${H-8}" fill="#8b9ab8" font-size="12" text-anchor="middle">${fmtT((tmin+tmax)/2)}</text>
    <text x="${W-padR}" y="${H-8}" fill="#8b9ab8" font-size="12" text-anchor="end">${fmtT(tmax)}</text>`;
  const last = pts[pts.length-1];
  document.getElementById("tlast").innerHTML = `${(+last.temp).toFixed(1)}<small style="font-size:.55em;color:#8b9ab8">°C</small>`;
}

function drawTable(rows) {
  const tb = document.getElementById("tb");
  const info = document.getElementById("info");
  const pts = rows.filter(r => r.temp !== null || r.dir !== null || r.speed !== null);
  if (!pts.length) {
    tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8b9ab8;padding:20px">нет данных</td></tr>';
    info.textContent = "нет данных";
    return;
  }
  const pad2 = n => String(n).padStart(2,"0");
  const hms = d => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  const today = new Date().toDateString();
  let html = "";
  const showRows = pts.slice().reverse();
  for (const r of showRows) {
    const d = new Date(r.t);
    const date = d.toDateString() === today ? "" : ` ${pad2(d.getDate())}.${pad2(d.getMonth()+1)}`;
    const temp = r.temp === null ? "—" : r.temp.toFixed(1);
    const speed = r.speed === null ? "—" : r.speed.toFixed(1);
    const dir = r.dir === null ? "—" : `${Math.round(r.dir)}° <small style="color:#8b9ab8">${RU[Math.round(r.dir/22.5)%16]}</small>`;
    const press = r.press === null ? "—" : r.press.toFixed(1);
    const hum = r.hum === null ? "—" : r.hum.toFixed(1) + "%";
    html += `<tr><td>${hms(d)}${date}</td><td class="temp">${temp}</td><td>${dir}</td><td class="speed">${speed}</td><td>${press}</td><td>${hum}</td></tr>`;
  }
  tb.innerHTML = html;
  const first = pts[0].t, last = pts[pts.length-1].t;
  info.textContent = `с ${hms(new Date(first))} по ${hms(new Date(last))} · записей: ${pts.length}`;
}

drawCompass(CUR.dir);
drawSpeed(CUR.speed);
drawChart(HIST);
drawTable(HIST);
</script>
</body>
</html>
"""
# ---------------------------------------------------------------------------
# Сборка страницы и отдача в Streamlit
# ---------------------------------------------------------------------------
def build_widget_html(cur, hist):
    cur_json = json.dumps(cur or {}, ensure_ascii=False)
    hist_json = json.dumps(hist or [], ensure_ascii=False)
    inject = (
        f"<script>window.__CUR__ = {cur_json}; window.__HIST__ = {hist_json};</script>"
    )
    return WIDGET_HTML.replace("</head>", inject + "</head>")


st.markdown(
    """
    <style>
      .block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; max-width: 100%; }
      header[data-testid="stHeader"] { display: none; }
      #MainMenu { visibility: hidden; }
      footer { visibility: hidden; }
      iframe { width: 100% !important; }
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

html = build_widget_html(cur, hist)
components.html(html, height=1400, scrolling=True)

# Авто-обновление раз в REFRESH_SEC секунд
import time as _time
if "wind_compass_tick" not in st.session_state:
    st.session_state.wind_compass_tick = _time.time()
if _time.time() - st.session_state.wind_compass_tick >= REFRESH_SEC:
    st.session_state.wind_compass_tick = _time.time()
_time.sleep(REFRESH_SEC)
st.rerun()
