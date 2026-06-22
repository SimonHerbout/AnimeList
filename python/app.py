import json
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR.parent / "data" / "sites.json"

# ---------------------------
# CACHE
# ---------------------------
CACHE = {
    "sites": None,
    "timestamp": 0,
    "ttl": 60
}

STATUS_CACHE = {
    "data": None,
    "timestamp": 0,
    "ttl": 120
}

# ---------------------------
# URL HELPERS (CRITICAL FIX)
# ---------------------------
def get_primary_url(url):
    if isinstance(url, list):
        return url[0].strip() if url else None
    if isinstance(url, str):
        return url.strip()
    return None


def normalize_url(url):
    """
    IMPORTANT: must match frontend normalization OR status mapping breaks.
    """
    url = get_primary_url(url)
    if not url:
        return None

    url = url.lower().strip()
    url = url.replace("https://", "").replace("http://", "")
    url = url.replace("www.", "")
    url = url.split("#")[0]
    url = url.rstrip("/")

    return url


# ---------------------------
# LOAD + DEDUPE
# ---------------------------
def remove_duplicates(sites):
    seen = set()
    result = []

    for site in sites:
        key = normalize_url(site.get("url"))
        if not key:
            continue

        # ONLY exact duplicates removed
        if key in seen:
            continue

        seen.add(key)
        result.append(site)

    return result


def load_sites():
    now = time.time()

    if CACHE["sites"] and (now - CACHE["timestamp"] < CACHE["ttl"]):
        return CACHE["sites"]

    try:
        if not DATA_FILE.exists():
            return []

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            data = []

        cleaned = remove_duplicates(data)

        CACHE["sites"] = cleaned
        CACHE["timestamp"] = now

        print(f"[LOAD] sites loaded: {len(cleaned)}")

        return cleaned

    except Exception as e:
        print("Load error:", e)
        return []


# ---------------------------
# STATUS CHECK (FIXED REAL WORLD RELIABILITY)
# ---------------------------
def check_site(site):
    name = site.get("name", "Unknown")
    url = get_primary_url(site.get("url"))
    code = None

    if not url:
        return {"name": name, "url": None, "status": "invalid"}

    try:
        r = requests.get(
            url,
            timeout=8,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/xhtml+xml"
            },
            allow_redirects=True
        )

        code = r.status_code

        if code in [200, 301, 302, 304]:
            status = "online"
        elif code in [403, 429, 503]:
            status = "online (restricted)"
        else:
            status = "offline"

    except requests.RequestException:
        status = "offline"
        code = None

    return {
        "name": name,
        "url": url,
        "status": status,
        "status_code": code
    }


# ---------------------------
# ROUTES
# ---------------------------
@app.route("/")
def home():
    return jsonify({
        "message": "API running",
        "sites_count": len(load_sites())
    })


# ---------------------------
# SITES
@app.route("/sites")
def sites():
    sites_list = load_sites()

    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 10000))  # allow ALL by default

    start = (page - 1) * limit
    end = start + limit

    return jsonify({
        "page": page,
        "limit": limit,
        "total": len(sites_list),
        "results": sites_list[start:end]
    })


# ---------------------------
# STATUS (FAST + CONSISTENT)
# ---------------------------
@app.route("/status")
def status():
    now = time.time()

    if STATUS_CACHE["data"] and (now - STATUS_CACHE["timestamp"] < STATUS_CACHE["ttl"]):
        return jsonify(STATUS_CACHE["data"])

    sites_list = load_sites()

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(check_site, sites_list))

    # 🔥 COUNT STATS
    total = len(results)
    online = sum(1 for s in results if s["status"] == "online")
    offline = sum(1 for s in results if s["status"] != "online")

    payload = {
        "count": total,
        "online": online,
        "offline": offline,
        "results": results
    }

    STATUS_CACHE["data"] = payload
    STATUS_CACHE["timestamp"] = now

    return jsonify(payload)

# ---------------------------
# RUN
# ---------------------------
if __name__ == "__main__":
    print("Server running...")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False
    )