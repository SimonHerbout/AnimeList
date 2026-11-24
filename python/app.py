
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

# Zoek sites.json op verschillende mogelijke locaties
DATA_FILE_CANDIDATES = [
    BASE_DIR.parent / "data" / "sites.json",
    BASE_DIR / "data" / "sites.json",
    Path.cwd() / "data" / "sites.json",
    Path.cwd().parent / "data" / "sites.json",
]

CACHE = {"sites": None, "timestamp": 0, "ttl": 60}
STATUS_CACHE = {"data": None, "timestamp": 0, "ttl": 120}


def find_data_file():
    for path in DATA_FILE_CANDIDATES:
        if path.is_file():
            print(f"[DATA] Found sites.json: {path}")
            return path

    print("[ERROR] sites.json not found!")
    for path in DATA_FILE_CANDIDATES:
        print(f"[CHECKED] {path}")

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
    url = url.replace("https://", "").replace("http://", "")
    url = url.replace("www.", "")
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
        and now - CACHE["timestamp"] < CACHE["ttl"]
    ):
        return CACHE["sites"]

    data_file = find_data_file()

    if data_file is None:
        return []

    try:
        with open(data_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        # Ondersteun zowel een directe lijst als een JSON-object
        if isinstance(data, dict):
            for key in ("sites", "results", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break

        if not isinstance(data, list):
            print("[ERROR] sites.json does not contain a list")
            return []

        cleaned = remove_duplicates(data)

        CACHE["sites"] = cleaned
        CACHE["timestamp"] = now

        print(f"[LOAD] Sites loaded: {len(cleaned)}")
        print(f"[LOAD] Original entries: {len(data)}")

        return cleaned

    except Exception as error:
        print(f"[ERROR] Could not load sites.json: {error}")
        return []


def check_site(site):
    name = site.get("name", "Unknown")
    url = get_primary_url(site.get("url"))

    if not url:
        return {
            "name": name,
            "url": None,
            "status": "invalid"
        }

    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        response = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True
        )

        code = response.status_code

        if code in (200, 301, 302, 304):
            status = "online"
        elif code in (403, 429, 503):
            status = "online (restricted)"
        else:
            status = "offline"

    except requests.RequestException as error:
        print(f"[STATUS ERROR] {url}: {error}")
        status = "offline"
        code = None

    return {
        "name": name,
        "url": url,
        "status": status,
        "status_code": code
    }


@app.route("/")
def home():
    sites = load_sites()

    return jsonify({
        "message": "API running",
        "sites_count": len(sites),
        "data_file_found": find_data_file() is not None
    })


@app.route("/health")
def health():
    sites = load_sites()

    return jsonify({
        "status": "ok",
        "sites_loaded": len(sites)
    })


@app.route("/sites")
def sites():
    sites_list = load_sites()

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(10000, max(1, int(request.args.get("limit", 10000))))
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

    if (
        STATUS_CACHE["data"] is not None
        and now - STATUS_CACHE["timestamp"] < STATUS_CACHE["ttl"]
    ):
        return jsonify(STATUS_CACHE["data"])

    sites_list = load_sites()

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(check_site, sites_list))

    online = sum(
        1 for site in results
        if site["status"] == "online"
    )

    payload = {
        "count": len(results),
        "online": online,
        "offline": len(results) - online,
        "results": results
    }

    STATUS_CACHE["data"] = payload
    STATUS_CACHE["timestamp"] = now

    return jsonify(payload)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True
    )
