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
        return None, f"HTTP {r.status_code}"
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
    ts_ms = None
    t_raw = find_deep(packet, "time") or find_deep(packet, "_ts")
    if t_raw is not None:
        try:
            n = float(t_raw)
            ts_ms = int(n if n > 1e11 else n * 1000)
        except Exception:
            pass
    return {
        "value": to_num(find_deep(packet, PARAM_DIR)),
        "speed": to_num(find_deep(packet, PARAM_SPEED)),
        "temp": to_num(find_deep(packet, PARAM_TEMP)),
        "press": to_num(find_deep(packet, PARAM_PRESS)),
        "hum": to_num(find_deep(packet, PARAM_HUM)),
        "ts": ts_ms,
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
    """Возвращает список пакетов как есть (один пакет = одна строка)."""
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
    # сортировка по времени по возрастанию
    rows.sort(key=lambda r: r["t"])
    # фильтр: только пакеты, где есть хоть что-то
    rows = [r for r in rows if any(r[k] is not None for k in ("temp", "dir", "speed", "press", "hum"))]
    return rows


# ---------------------------------------------------------------------------
# HTML виджета — ваш полный дизайн (роза ветров, спидометр, сворачивающаяся
# таблица, график), данные приходят из Python через window.__CUR__ / __HIST__.
# ---------------------------------------------------------------------------
WIDGET_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
  :root{
    --bg:#0f1420;
    --panel:#161d2e;
    --panel-2:#1d2740;
    --line:#2a3550;
    --text:#e8edf7;
    --muted:#8b9ab8;
    --accent:#ffb020;
    --ok:#38d39f;
    --err:#ff6b6b;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{
    margin:0;
    background:radial-gradient(1400px 800px at 40% -10%, #1b2740 0%, var(--bg) 60%);
    color:var(--text);
    font:14px/1.45 "Segoe UI", Roboto, Arial, sans-serif;
    overflow-x:hidden;
  }
  .stage{display:flex;flex-direction:column;gap:14px;padding:12px}
  .head{display:flex;align-items:center;justify-content:space-between;gap:12px}
  .head h1{font-size:16px;font-weight:600;margin:0}
  .badge{font-size:11px;color:var(--muted);border:1px solid var(--line);padding:2px 8px;border-radius:999px;margin-left:8px}

  .row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .gauge{
    display:flex;flex-direction:column;gap:8px;min-width:0;
    background:linear-gradient(180deg,#141b2b 0%,#0e1421 100%);
    border-radius:18px;
    box-shadow:0 16px 44px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.05);
    padding:12px;
  }
  .gauge__title{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}

  .dir-wrap{position:relative;width:100%;aspect-ratio:400/330}
  .dir-wrap svg{position:absolute;inset:0;width:100%;height:100%;display:block}
  #dirPointer{transform-origin:200px 165px;transition:transform .9s cubic-bezier(.22,.68,.24,1)}

  .speed-wrap{position:relative;width:100%;aspect-ratio:400/330}
  .speed-wrap svg{position:absolute;inset:0;width:100%;height:100%;display:block}
  .speed-value{position:absolute;left:50%;top:66%;transform:translate(-50%,-50%);text-align:center;pointer-events:none}
  .speed-value__num{font-size:clamp(24px,5vh,52px);font-weight:700;color:var(--accent);line-height:1;font-variant-numeric:tabular-nums}
  .speed-value__num small{font-size:.42em;font-weight:600;margin-left:4px;color:var(--muted)}
  .speed-value__cap{margin-top:4px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}

  .chart-card{
    background:linear-gradient(180deg,#141b2b 0%,#0e1421 100%);
    border-radius:18px;
    box-shadow:0 16px 44px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.05);
    padding:12px 14px 8px;
  }
  .chart-card__head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:6px;flex-wrap:wrap}
  .chart-card__head h2{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0;font-weight:600}
  .chart-card__last{font-size:22px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums}
  .chart-card__last small{font-size:.55em;color:var(--muted);margin-left:4px;font-weight:600}
  .chart-wrap{position:relative;width:100%;aspect-ratio:1000/260}
  .chart-wrap svg{position:absolute;inset:0;width:100%;height:100%;display:block}

  .table-card{
    background:linear-gradient(180deg,#141b2b 0%,#0e1421 100%);
    border-radius:18px;
    box-shadow:0 16px 44px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.05);
    padding:12px 14px 10px;
  }
  .table-ctl{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
  .table-ctl label{margin:0;white-space:nowrap}
  .table-ctl select{width:auto;padding:5px 8px;font-size:12px;background:var(--panel-2);border:1px solid var(--line);color:var(--text);border-radius:9px}
  .table-scroll{max-height:380px;overflow:auto;border-radius:10px;box-shadow:0 0 0 1px rgba(255,255,255,.06)}
  .table-toggle{
    display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none;
    width:100%;background:none;border:none;padding:0;color:inherit;text-align:left;
    font:inherit;
  }
  .table-arrow{margin-left:auto;flex-shrink:0;width:20px;height:20px;opacity:.55;transition:transform .25s}
  .table-card.open .table-arrow{transform:rotate(180deg);opacity:.9}
  .table-body-wrap{display:grid;grid-template-rows:0fr;transition:grid-template-rows .28s ease}
  .table-body-wrap>div{overflow:hidden}
  .table-card.open .table-body-wrap{grid-template-rows:1fr}

  .data-table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}
  .data-table th{
    position:sticky;top:0;background:#182036;color:var(--muted);
    font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:600;
    text-align:right;padding:8px 12px;white-space:nowrap;
  }
  .data-table th:first-child,.data-table td:first-child{text-align:left}
  .data-table td{text-align:right;padding:6px 12px;border-top:1px solid rgba(255,255,255,.05);color:#e8edf7}
  .data-table td.t-time{color:var(--muted)}
  .data-table td.t-time small{margin-left:6px;opacity:.7}
  .data-table td.t-temp,.data-table td.t-speed{color:var(--accent);font-weight:600}
  .data-table td.t-dir small{color:var(--muted);margin-left:6px}
  .data-table td.t-press,.data-table td.t-hum{color:#a0b4d8}
  .data-table td.empty{text-align:center;color:var(--muted);padding:22px}

  .status{text-align:center;font-size:12px;color:var(--muted);min-height:18px}
  .status.is-ok{color:var(--ok)}
  .status.is-err{color:var(--err)}
</style>
</head>
<body>
<div class="stage">
  <div class="head">
    <div>
      <h1>Метеостанция<span class="badge" id="modeBadge">онлайн</span></h1>
    </div>
  </div>

  <div class="row">
    <div class="gauge">
      <div class="gauge__title">Направление ветра</div>
      <div class="dir-wrap" id="dialWrap">
        <svg id="needleSvg" viewBox="0 0 400 330" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
    </div>

    <div class="gauge">
      <div class="gauge__title">Скорость ветра</div>
      <div class="speed-wrap" id="speedWrap">
        <svg id="speedSvg" viewBox="0 0 400 330" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="speed-value">
          <div class="speed-value__num" id="speedNum">—<small>м/с</small></div>
          <div class="speed-value__cap">скорость ветра</div>
        </div>
      </div>
    </div>
  </div>

  <div class="chart-card">
    <div class="chart-card__head">
      <h2>Температура · последние <span id="chartPointsLabel">120</span> точек</h2>
      <div class="chart-card__last" id="chartLast">—<small>°C</small></div>
    </div>
    <div class="chart-wrap">
      <svg id="tempSvg" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg>
    </div>
    <div class="status" id="status">Данные Rightech</div>
  </div>

  <div class="table-card" id="tableCard">
    <button class="table-toggle" id="tableToggle" aria-expanded="false">
      <span>ДАННЫЕ ЗА 6 ЧАСОВ · <span id="tableInfo">нет данных</span></span>
      <div class="table-ctl" onclick="event.stopPropagation()">
        <label for="tableStep">Шаг</label>
        <select id="tableStep">
          <option value="0">все записи</option>
          <option value="1">1 мин</option>
          <option value="5">5 мин</option>
          <option value="10">10 мин</option>
          <option value="30">30 мин</option>
        </select>
      </div>
      <svg class="table-arrow" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
        <polyline points="4,7 10,13 16,7"/>
      </svg>
    </button>
    <div class="table-body-wrap">
      <div>
        <div class="table-scroll" style="margin-top:10px">
          <table class="data-table">
            <thead><tr>
              <th>Время</th><th>Темп., °C</th><th>Направление</th><th>Скор., м/с</th><th>Давл., гПа</th><th>Влажность, %</th>
            </tr></thead>
            <tbody id="tableBody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
"use strict";
const CUR = window.__CUR__ || {};
const HIST = window.__HIST__ || [];
const RU = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"];

const el = (id) => document.getElementById(id);
const ui = {
  svg: el("needleSvg"), status: el("status"), badge: el("modeBadge"),
  speedSvg: el("speedSvg"), speedNum: el("speedNum"),
  tempSvg: el("tempSvg"), chartLast: el("chartLast"), chartPointsLabel: el("chartPointsLabel"),
  tableToggle: el("tableToggle"), tableCard: el("tableCard"),
  tableBody: el("tableBody"), tableInfo: el("tableInfo"), tableStep: el("tableStep"),
};

let cumulativeRotation = 0;
let currentAngle = null;
let historyPoints = [];
let tableRows = [];

function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }

/* ---------------- КОМПАС ---------------- */
const DIR = { cx: 200, cy: 165, R: 155 };
function dirPolar(deg, r) {
  const a = (deg - 90) * Math.PI / 180;
  return [DIR.cx + r * Math.cos(a), DIR.cy + r * Math.sin(a)];
}
function buildNeedle() {
  const { cx, cy, R } = DIR;
  const f = (n) => n.toFixed(2);
  let ticks = "";
  for (let d = 0; d < 360; d += 10) {
    const major = d % 90 === 0, mid = !major && d % 30 === 0;
    const r1 = R - (major ? 15 : (mid ? 11 : 7));
    const [x1, y1] = dirPolar(d, r1), [x2, y2] = dirPolar(d, R);
    const stroke = d === 0 ? "#ff6b6b" : "#8b9ab8";
    const width = major ? 2.4 : (mid ? 1.6 : 1.1);
    ticks += `<line x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round"/>`;
  }
  const names = [["С",0],["СВ",45],["В",90],["ЮВ",135],["Ю",180],["ЮЗ",225],["З",270],["СЗ",315]];
  let labels = "";
  for (const [n, d] of names) {
    const card = n.length === 1;
    const [tx, ty] = dirPolar(d, R - 32);
    const fill = n === "С" ? "#ff6b6b" : (card ? "#e8edf7" : "#8b9ab8");
    labels += `<text x="${f(tx)}" y="${f(ty)}" fill="${fill}" font-size="${card ? 20 : 14}" font-weight="${card ? 700 : 500}" text-anchor="middle" dominant-baseline="middle">${n}</text>`;
  }
  const tipY = cy - R - 6, baseY = cy - R + 16, hw = 10;
  const pointer = `<g id="dirPointer">
      <line x1="${cx}" y1="${cy - 59}" x2="${cx}" y2="${baseY}" stroke="#ffb020" stroke-width="2" stroke-linecap="round" opacity="0.4"/>
      <polygon points="${cx},${tipY} ${cx + hw},${baseY} ${cx},${baseY - 4} ${cx - hw},${baseY}" fill="#ffb020" stroke="#0e1421" stroke-width="1.4" stroke-linejoin="round"/>
    </g>`;
  ui.svg.innerHTML = `
    <defs><linearGradient id="dirGrad" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#38d39f"/><stop offset="0.6" stop-color="#ffb020"/><stop offset="1" stop-color="#ff6b6b"/>
    </linearGradient></defs>
    <circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="#2a3550" stroke-width="10"/>
    <circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="url(#dirGrad)" stroke-width="4" opacity="0.55"/>
    ${ticks}${labels}
    <circle cx="${cx}" cy="${cy}" r="58" fill="#141b2b" stroke="#2a3550" stroke-width="1.5"/>
    <text id="dirNum" x="${cx}" y="${cy - 5}" fill="#ffb020" font-size="46" font-weight="700" text-anchor="middle" dominant-baseline="middle">—</text>
    <text id="dirCap" x="${cx}" y="${cy + 30}" fill="#8b9ab8" font-size="16" letter-spacing="1.5" text-anchor="middle">—</text>
    ${pointer}`;
  const g = ui.svg.querySelector("#dirPointer");
  if (g) g.style.transform = `rotate(${cumulativeRotation}deg)`;
  if (currentAngle !== null) setDirText(currentAngle);
}
function setDirText(a) {
  const grad = Math.round(a) % 360;
  const idx = Math.round(a / 22.5) % 16;
  const num = ui.svg.querySelector("#dirNum"), cap = ui.svg.querySelector("#dirCap");
  if (num) num.textContent = `${grad}°`;
  if (cap) cap.textContent = RU[idx];
}
function drawCompass(angle) {
  if (angle === null || !Number.isFinite(angle)) return;
  const delta = ((angle - cumulativeRotation) % 360 + 540) % 360 - 180;
  cumulativeRotation += delta;
  currentAngle = angle;
  const g = ui.svg.querySelector("#dirPointer");
  if (g) g.style.transform = `rotate(${cumulativeRotation}deg)`;
  setDirText(angle);
}

/* ---------------- СПИДОМЕТР ---------------- */
function buildSpeedometer() {
  const W = 400, H = 330, cx = W/2, cy = H*0.78, R = 155, START = -110, END = 110;
  const polar = (d, r) => { const a = (d-90)*Math.PI/180; return [cx + r*Math.cos(a), cy + r*Math.sin(a)]; };
  const arcPath = (a, b, r) => {
    const [x1, y1] = polar(a, r), [x2, y2] = polar(b, r);
    const large = Math.abs(b-a) > 180 ? 1 : 0;
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r.toFixed(2)} ${r.toFixed(2)} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };
  let ticks = "";
  for (let v = 0; v <= 50; v += 5) {
    const d = START + (v/50)*(END-START), major = v % 10 === 0;
    const r1 = R - (major ? 14 : 8), [x1, y1] = polar(d, r1), [x2, y2] = polar(d, R);
    const stroke = v >= 30 ? "#ff6b6b" : "#8b9ab8";
    const width = major ? 2.2 : 1.1;
    ticks += `<line x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round"/>`;
    if (major) {
      const [tx, ty] = polar(d, R - 30);
      ticks += `<text x="${tx.toFixed(2)}" y="${ty.toFixed(2)}" fill="#c9d2e0" font-size="14" text-anchor="middle" dominant-baseline="middle">${v}</text>`;
    }
  }
  const redFrom = START + (30/50)*(END-START);
  const redArc = `<path d="${arcPath(redFrom, END, R - 3)}" fill="none" stroke="#ff6b6b" stroke-width="6" stroke-linecap="round" opacity="0.85"/>`;
  ui.speedSvg.innerHTML = `
    <defs><linearGradient id="spdGrad" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#38d39f"/><stop offset="0.6" stop-color="#ffb020"/><stop offset="1" stop-color="#ff6b6b"/>
    </linearGradient></defs>
    <path d="${arcPath(START, END, R)}" fill="none" stroke="#2a3550" stroke-width="10" stroke-linecap="round"/>
    <path d="${arcPath(START, END, R)}" fill="none" stroke="url(#spdGrad)" stroke-width="4" stroke-linecap="round" opacity="0.55"/>
    ${redArc}${ticks}
    <circle cx="${cx}" cy="${cy}" r="10" fill="#1d2740" stroke="#4a6ea8" stroke-width="1.6"/>
    <circle cx="${cx}" cy="${cy}" r="3.4" fill="#ffb020"/>`;
}
function drawSpeed(value) {
  const W = 400, H = 330, cx = W/2, cy = H*0.78, R = 155, START = -110, END = 110;
  let needle = ui.speedSvg.querySelector("#speedNeedle");
  if (value === null || !Number.isFinite(value)) {
    if (needle) needle.remove();
    ui.speedNum.innerHTML = `—<small>м/с</small>`;
    return;
  }
  const v = clamp(value, 0, 50);
  const deg = START + (v/50)*(END-START);
  const rad = (deg-90)*Math.PI/180;
  const len = R - 34;
  const x = cx + len*Math.cos(rad), y = cy + len*Math.sin(rad);
  const backLen = 16;
  const bx = cx - backLen*Math.cos(rad), by = cy - backLen*Math.sin(rad);
  if (!needle) {
    needle = document.createElementNS("http://www.w3.org/2000/svg", "g");
    needle.setAttribute("id", "speedNeedle");
    needle.innerHTML = `<line x1="${bx}" y1="${by}" x2="${x}" y2="${y}" stroke="#ffb020" stroke-width="4.2" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="6.5" fill="#ffb020"/>`;
    ui.speedSvg.appendChild(needle);
  } else {
    const line = needle.querySelector("line");
    line.setAttribute("x1", bx); line.setAttribute("y1", by);
    line.setAttribute("x2", x); line.setAttribute("y2", y);
  }
  const shown = value;
  const decimals = shown < 10 ? 1 : 0;
  ui.speedNum.innerHTML = `${shown.toFixed(decimals)}<small>м/с</small>`;
}

/* ---------------- ГРАФИК ---------------- */
function buildTemperatureChart() {
  const W = 1000, H = 260, padL = 44, padR = 16, padT = 16, padB = 30;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const pts = historyPoints;
  const hasData = pts.length >= 2;
  let vmin = -10, vmax = 30;
  if (hasData) {
    vmin = Infinity; vmax = -Infinity;
    for (const p of pts) { if (p.v < vmin) vmin = p.v; if (p.v > vmax) vmax = p.v; }
    if (vmax - vmin < 1) { vmax += .5; vmin -= .5; }
    const pad = (vmax - vmin) * 0.12; vmin -= pad; vmax += pad;
  }
  let tmin = 0, tmax = 1;
  if (hasData) { tmin = pts[0].t; tmax = pts[pts.length-1].t; if (tmax - tmin < 1000) tmax = tmin + 1000; }
  const xOf = (t) => padL + ((t - tmin)/(tmax - tmin))*plotW;
  const yOf = (v) => padT + (1 - (v - vmin)/(vmax - vmin))*plotH;
  let svg = "";
  for (let i = 0; i <= 5; i++) {
    const v = vmin + (i/5)*(vmax-vmin), y = yOf(v);
    svg += `<line x1="${padL}" y1="${y.toFixed(2)}" x2="${W-padR}" y2="${y.toFixed(2)}" stroke="#233052" stroke-width="1"/>`;
    svg += `<text x="${padL-8}" y="${y.toFixed(2)}" fill="#8b9ab8" font-size="12" text-anchor="end" dominant-baseline="middle">${v.toFixed((vmax-vmin) < 6 ? 1 : 0)}°</text>`;
  }
  svg += `<line x1="${padL}" y1="${padT}" x2="${padL}" y2="${H-padB}" stroke="#3b4d78" stroke-width="1.2"/>`;
  svg += `<line x1="${padL}" y1="${H-padB}" x2="${W-padR}" y2="${H-padB}" stroke="#3b4d78" stroke-width="1.2"/>`;
  if (hasData) {
    const line = pts.map(p => `${xOf(p.t).toFixed(2)},${yOf(p.v).toFixed(2)}`).join(" ");
    const area = `${padL},${H-padB} ` + line + ` ${W-padR},${H-padB}`;
    svg += `<defs><linearGradient id="tf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff6b6b" stop-opacity="0.38"/><stop offset="1" stop-color="#ff6b6b" stop-opacity="0"/></linearGradient></defs>`;
    svg += `<polygon points="${area}" fill="url(#tf)"/>`;
    svg += `<polyline points="${line}" fill="none" stroke="#ff6b6b" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
    const last = pts[pts.length-1];
    svg += `<circle cx="${xOf(last.t).toFixed(2)}" cy="${yOf(last.v).toFixed(2)}" r="4" fill="#ff6b6b" stroke="#0e1421" stroke-width="1.5"/>`;
    const fmtT = (t) => { const d = new Date(t); return d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"}); };
    svg += `<text x="${padL}" y="${H-8}" fill="#8b9ab8" font-size="12" text-anchor="start">${fmtT(tmin)}</text>`;
    svg += `<text x="${(padL+W-padR)/2}" y="${H-8}" fill="#8b9ab8" font-size="12" text-anchor="middle">${fmtT((tmin+tmax)/2)}</text>`;
    svg += `<text x="${W-padR}" y="${H-8}" fill="#8b9ab8" font-size="12" text-anchor="end">${fmtT(tmax)}</text>`;
  } else {
    svg += `<text x="${W/2}" y="${H/2}" fill="#5b6b8e" font-size="16" text-anchor="middle">нет данных для графика</text>`;
  }
  ui.tempSvg.innerHTML = svg;
  if (hasData) {
    const last = pts[pts.length-1];
    ui.chartLast.style.color = "#ff6b6b";
    ui.chartLast.innerHTML = `${last.v.toFixed(1)}<small>°C</small>`;
  } else {
    ui.chartLast.innerHTML = `—<small>°C</small>`;
  }
}

/* ---------------- ТАБЛИЦА ---------------- */
function renderTable() {
  const stepMin = Number(ui.tableStep.value) || 0;
  const stepMs = stepMin > 0 ? stepMin * 60000 : 10000;
  let rows = tableRows;
  const seen = new Map();
  rows = rows.filter((r) => {
    const k = Math.floor(r.t / stepMs);
    if (seen.has(k)) return false;
    seen.set(k, true);
    return true;
  });
  if (!rows.length) {
    ui.tableBody.innerHTML = '<tr><td class="empty" colspan="6">Нет данных за последние 6 часов</td></tr>';
    ui.tableInfo.textContent = "нет данных";
    return;
  }
  const today = new Date().toDateString();
  const pad = (n) => String(n).padStart(2, "0");
  const hms = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const out = [];
  for (const r of rows) {
    const d = new Date(r.t);
    const date = d.toDateString() === today ? "" : `<small>${pad(d.getDate())}.${pad(d.getMonth()+1)}</small>`;
    const temp = r.temp === null ? "—" : r.temp.toFixed(1);
    const speed = r.speed === null ? "—" : r.speed.toFixed(1);
    const dir = r.dir === null ? "—" : `${Math.round(r.dir)%360}°<small>${RU[Math.round(r.dir/22.5)%16]}</small>`;
    const press = r.press === null ? "—" : r.press.toFixed(1);
    const hum = r.hum === null ? "—" : r.hum.toFixed(1) + "%";
    out.push(`<tr><td class="t-time">${hms(d)}${date}</td><td class="t-temp">${temp}</td><td class="t-dir">${dir}</td><td class="t-speed">${speed}</td><td class="t-press">${press}</td><td class="t-hum">${hum}</td></tr>`);
  }
  ui.tableBody.innerHTML = out.join("");
  const hm = (t) => { const d = new Date(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  ui.tableInfo.textContent = `с ${hm(rows[rows.length-1].t)} по ${hm(rows[0].t)} · записей: ${rows.length}`;
}

/* ---------------- ИНИЦИАЛИЗАЦИЯ ---------------- */
buildNeedle();
buildSpeedometer();
if (CUR.value !== undefined && CUR.value !== null) {
  drawCompass(Number(CUR.value));
  ui.badge.textContent = "онлайн";
}
if (CUR.speed !== undefined && CUR.speed !== null) {
  drawSpeed(Number(CUR.speed));
}
// история для графика (по возрастанию t)
historyPoints = HIST.filter(r => r.temp !== null).map(r => ({ t: r.t, v: r.temp }));
buildTemperatureChart();
// история для таблицы — новые сверху
tableRows = HIST.slice().reverse();
renderTable();

if (CUR.ts) {
  const t = new Date(CUR.ts).toLocaleTimeString("ru-RU");
  ui.status.textContent = `Rightech API · windDirection = ${CUR.value} · ${CUR.speed} м/с · ${CUR.temp}°C · ${t}`;
  ui.status.className = "status is-ok";
}

/* ---------------- СОБЫТИЯ ---------------- */
ui.tableToggle.addEventListener("click", () => {
  ui.tableCard.classList.toggle("open");
  ui.tableToggle.setAttribute("aria-expanded", String(ui.tableCard.classList.contains("open")));
});
ui.tableStep.addEventListener("change", renderTable);
</script>
</body>
</html>
"""


def build_widget_html(cur, hist):
    cur_json = json.dumps(cur or {}, ensure_ascii=False)
    hist_json = json.dumps(hist or [], ensure_ascii=False)
    inject = f"<script>window.__CUR__ = {cur_json}; window.__HIST__ = {hist_json};</script>"
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
components.html(html, height=1450, scrolling=True)

import time as _time
if "wind_compass_tick" not in st.session_state:
    st.session_state.wind_compass_tick = _time.time()
if _time.time() - st.session_state.wind_compass_tick >= REFRESH_SEC:
    st.session_state.wind_compass_tick = _time.time()
_time.sleep(REFRESH_SEC)
st.rerun()
