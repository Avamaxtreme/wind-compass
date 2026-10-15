import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

st.set_page_config(
    page_title="Метеостанция — Роза ветров",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  #MainMenu, footer, header, [data-testid="stToolbar"] { display:none!important; }
  .block-container { padding:0!important; margin:0!important; max-width:100%!important; }
  body, .stApp { background:#0e1421!important; }
</style>
""", unsafe_allow_html=True)

API_BASE    = "https://dev.rightech.io"
TOKEN       = st.secrets.get("RIGHTECH_TOKEN", "")
OBJECT_ID   = st.secrets.get("OBJECT_ID", "")
PARAM_DIR   = st.secrets.get("PARAM_DIR",   "windDirection")
PARAM_SPD   = st.secrets.get("PARAM_SPEED", "windSpeed")
PARAM_TEMP  = st.secrets.get("PARAM_TEMP",  "temperature")
PARAM_PRESS = st.secrets.get("PARAM_PRESS", "pressure")
PARAM_HUM   = st.secrets.get("PARAM_HUM",   "humidity")
REFRESH_SEC = int(st.secrets.get("REFRESH_SEC", 10))


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
    """Регистронезависимый поиск значения по ключу на любой глубине."""
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
        lk = str(key).lower()
        # сначала точное совпадение без учёта регистра
        for k in obj.keys():
            if str(k).lower() == lk:
                v = obj[k]
                if v is not None and not isinstance(v, (dict, list)):
                    return v
        # потом рекурсивный обход
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
    for k in ("time", "_ts", "timestamp", "ts"):
        t_raw = find_deep(packet, k)
        if t_raw is not None:
            try:
                n = float(t_raw)
                ts_ms = int(n if n > 1e11 else n * 1000)
                break
            except Exception:
                pass
    return {
        "value": to_num(find_deep(packet, PARAM_DIR)),
        "speed": to_num(find_deep(packet, PARAM_SPD)),
        "temp":  to_num(find_deep(packet, PARAM_TEMP)),
        "press": to_num(find_deep(packet, PARAM_PRESS)),
        "hum":   to_num(find_deep(packet, PARAM_HUM)),
        "ts":    ts_ms,
    }, None


def packet_time_ms(p):
    for k in ("time", "_ts", "timestamp", "ts", "t"):
        if k in p and p[k] is not None:
            v = p[k]
            if isinstance(v, (int, float)):
                return int(v if v > 1e11 else v * 1000)
            try:
                return int(datetime.fromisoformat(
                    str(v).replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                pass
    return None


def fetch_history(hours=6, limit=1000):
    """Скачивает пакеты Rightech за последние N часов и склеивает их по времени
    (окно 2 секунды). В итоге в одной строке — все 5 параметров."""
    to_dt   = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=hours + 1)
    fmt = "%Y-%m-%dT%H:%M"
    path = (
        f"/api/v1/objects/{OBJECT_ID}/packets"
        f"?limit={limit}&from={from_dt.strftime(fmt)}&to={to_dt.strftime(fmt)}"
    )
    data, err = api_get(path)
    if err or not isinstance(data, list):
        return []

    merged = {}
    for p in data:
        if not isinstance(p, dict):
            continue
        t_ms = packet_time_ms(p)
        if t_ms is None:
            continue
        key = round(t_ms / 2000)
        if key not in merged:
            merged[key] = {
                "t": t_ms,
                "temp": None, "dir": None, "speed": None,
                "press": None, "hum": None,
            }
        row = merged[key]

        for field, pk in (
            ("temp",  PARAM_TEMP),
            ("dir",   PARAM_DIR),
            ("speed", PARAM_SPD),
            ("press", PARAM_PRESS),
            ("hum",   PARAM_HUM),
        ):
            if row[field] is None:
                v = to_num(find_deep(p, pk))
                if v is not None:
                    row[field] = v

    rows = list(merged.values())
    rows.sort(key=lambda r: r["t"])
    rows = [r for r in rows if any(
        r[k] is not None for k in ("temp", "dir", "speed", "press", "hum"))]

    if rows:
        cutoff = rows[-1]["t"] - hours * 3600 * 1000
        rows = [r for r in rows if r["t"] >= cutoff]
    return rows


WIDGET_HTML = (Path(__file__).parent / "widget.html").read_text(encoding="utf-8")


def build_html(cur, hist):
    cur_js  = json.dumps(cur  or {}, ensure_ascii=False)
    hist_js = json.dumps(hist or [], ensure_ascii=False)
    inject  = f"<script>window.__CUR__={cur_js};window.__HIST__={hist_js};</script>"
    return WIDGET_HTML.replace("</head>", inject + "\n</head>")


if not TOKEN or not OBJECT_ID:
    st.error(
        "Не заданы настройки. Откройте **Settings → Secrets** и добавьте:\n\n"
        "```\nRIGHTECH_TOKEN = \"eyJ...\"\nOBJECT_ID = \"6aa...\"\n```"
    )
    st.stop()

cur, err = fetch_current()
if err:
    st.warning(f"Ошибка текущих данных: {err}")
    cur = {}

hist = fetch_history(hours=6, limit=1000)

html = build_html(cur, hist)
components.html(html, height=1500, scrolling=True)

# авто-обновление
if "tick" not in st.session_state:
    st.session_state.tick = time.time()
if time.time() - st.session_state.tick >= REFRESH_SEC:
    st.session_state.tick = time.time()
time.sleep(REFRESH_SEC)
st.rerun()
