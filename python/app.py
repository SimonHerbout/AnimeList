
import json
import time
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

# Sta verzoeken toe vanaf je Netlify-website
CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                "https://aniquest-hub.netlify.app"
            ]
        }
    }
)

BASE_DIR = Path(__file__).resolve().parent

DATA_FILE_CANDIDATES = [
    BASE_DIR.parent / "data" / "sites.json",
    BASE_DIR / "data" / "sites.json",
    Path.cwd() / "data" / "sites.json",
    Path.cwd().parent / "data" / "sites.json",
]

CACHE = {
    "sites": None,
    "timestamp": 0,
    "ttl": 300
}


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
        return url[0].strip() if url and isinstance(url[0], str) else None

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
    # Geen externe websites controleren tijdens een API-verzoek.
    # Dit voorkomt lange wachttijden en Render worker timeouts.
    sites_list = load_sites()

    results = []

    for site in sites_list:
        results.append({
            "name": site.get("name", "Unknown"),
            "url": get_primary_url(site.get("url")),
            "status": "unchecked",
            "status_code": None
        })

    return jsonify({
        "count": len(results),
        "online": 0,
        "offline": 0,
        "unchecked": len(results),
        "results": results
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True
    )
