
import json
import time
import threading
import requests

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent

DATA_FILE_CANDIDATES = [
    BASE_DIR.parent / "data" / "sites.json",
    BASE_DIR / "data" / "sites.json",
    Path.cwd() / "data" / "sites.json",
    Path.cwd().parent / "data" / "sites.json",
]

# ----------------------------
# CONFIGURATION
# ----------------------------

SITE_CACHE_TTL = 300
STATUS_CACHE_TTL = 120

BATCH_SIZE = 20
MAX_WORKERS = 5
REQUEST_TIMEOUT = 4

CACHE = {
    "sites": None,
    "timestamp": 0
}

STATUS_CACHE = {
    "data": {},
    "timestamp": 0,
    "next_index": 0
}

STATUS_LOCK = threading.Lock()


# ----------------------------
# DATA FILE
# ----------------------------

def find_data_file():
    for path in DATA_FILE_CANDIDATES:
        if path.is_file():
            print(f"[DATA] Found sites.json: {path}")
            return path

    print("[ERROR] sites.json not found!")
    return None


def get_primary_url(url):
    if isinstance(url, list):
        return url[0].strip() if url else None

    if isinstance(url, str):
        return url.strip()

    return None


def normalize_url(url):
    url = get_primary_url(url)

    if not url:
        return None

    url = url.lower().strip()
    url = url.replace("https://", "")
    url = url.replace("http://", "")
    url = url.removeprefix("www.")

    return url.split("#")[0].rstrip("/")


def remove_duplicates(sites):
    seen = set()
    result = []

    for site in sites:
        if not isinstance(site, dict):
            continue

        key = normalize_url(site.get("url"))

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(site)

    return result


def load_sites():
    now = time.time()

    if (
        CACHE["sites"] is not None
        and now - CACHE["timestamp"] < SITE_CACHE_TTL
    ):
        return CACHE["sites"]

    data_file = find_data_file()

    if data_file is None:
        return []

    try:
        with open(data_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            for key in ("sites", "results", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break

        if not isinstance(data, list):
            print("[ERROR] Invalid sites.json format")
            return []

        cleaned = remove_duplicates(data)

        CACHE["sites"] = cleaned
        CACHE["timestamp"] = now

        print(f"[LOAD] Sites loaded: {len(cleaned)}")

        return cleaned

    except Exception as error:
        print(f"[ERROR] Could not load sites.json: {error}")
        return []


# ----------------------------
# STATUS CHECK
# ----------------------------

def check_site(site):
    name = site.get("name", "Unknown")
    url = get_primary_url(site.get("url"))

    if not url:
        return {
            "name": name,
            "url": None,
            "status": "invalid",
            "status_code": None
        }

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 AnimeList/1.0"},
            allow_redirects=True,
            stream=True
        )

        code = response.status_code
        response.close()

        if code in (200, 301, 302, 304):
            result_status = "online"
        elif code in (403, 429, 503):
            result_status = "online (restricted)"
        else:
            result_status = "offline"

    except requests.RequestException:
        result_status = "offline"
        code = None

    return {
        "name": name,
        "url": url,
        "status": result_status,
        "status_code": code
    }


def update_status_batch():
    sites_list = load_sites()

    if not sites_list:
        return

    with STATUS_LOCK:
        start = STATUS_CACHE["next_index"]

        end = min(start + BATCH_SIZE, len(sites_list))

        batch = sites_list[start:end]

        if not batch:
            STATUS_CACHE["next_index"] = 0
            start = 0
            end = min(BATCH_SIZE, len(sites_list))
            batch = sites_list[start:end]

        STATUS_CACHE["next_index"] = (
            0 if end >= len(sites_list) else end
        )

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(check_site, batch))

        for result in results:
            key = normalize_url(result["url"])

            if key:
                STATUS_CACHE["data"][key] = result

        STATUS_CACHE["timestamp"] = time.time()

        print(
            f"[STATUS] Checked {len(results)} websites. "
            f"Cached: {len(STATUS_CACHE['data'])}"
        )


# ----------------------------
# ROUTES
# ----------------------------

@app.route("/")
def home():
    sites_list = load_sites()

    return jsonify({
        "message": "API running",
        "sites_count": len(sites_list)
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "sites_loaded": len(load_sites())
    })


@app.route("/sites")
def sites():
    sites_list = load_sites()

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(10000, max(1, int(request.args.get("limit", 100))))
    except ValueError:
        return jsonify({"error": "Invalid page or limit"}), 400

    start = (page - 1) * limit
    end = start + limit

    return jsonify({
        "page": page,
        "limit": limit,
        "total": len(sites_list),
        "results": sites_list[start:end]
    })


@app.route("/status")
def status():
    now = time.time()

    # Alleen een kleine groep controleren als de cache verlopen is.
    if now - STATUS_CACHE["timestamp"] >= STATUS_CACHE_TTL:
        update_status_batch()

    sites_list = load_sites()

    results = []

    for site in sites_list:
        key = normalize_url(site.get("url"))

        cached = STATUS_CACHE["data"].get(key)

        if cached:
            results.append(cached)
        else:
            results.append({
                "name": site.get("name", "Unknown"),
                "url": get_primary_url(site.get("url")),
                "status": "unchecked",
                "status_code": None
            })

    online = sum(
        1 for item in results
        if item["status"] in ("online", "online (restricted)")
    )

    return jsonify({
        "count": len(results),
        "online": online,
        "offline": sum(
            1 for item in results
            if item["status"] == "offline"
        ),
        "unchecked": sum(
            1 for item in results
            if item["status"] == "unchecked"
        ),
        "results": results
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True
    )
