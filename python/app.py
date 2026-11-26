
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import requests

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, g, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

ALLOWED_ORIGINS = [
    "https://aniquest-hub.netlify.app",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
]

CORS(
    app,
    resources={
        r"/*": {
            "origins": ALLOWED_ORIGINS,
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type"]
        }
    }
)
# ---------------------------------------------------------------- auth config
#
# AUTH_USERS holds the allowed logins. Set it on Render as either
#   AUTH_USERS=simon:password1,friend:password2
# or a JSON map: {"simon": "password1", "friend": "password2"}.
# When it is missing a random password is generated and printed to the logs so
# the deployment can never lock itself out.
#
# Sessions are stateless signed tokens (HMAC-SHA256) so they keep working when
# the UI and the API live on different domains.

def load_users():
    raw = os.environ.get("AUTH_USERS", "").strip()
    users = {}

    if not raw:
        return users

    if raw.startswith(("{", "[")):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            users = {
                str(name).strip().lower(): str(password)
                for name, password in parsed.items()
                if str(name).strip() and str(password)
            }
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    name = str(item.get("username", "")).strip().lower()
                    password = str(item.get("password", ""))
                    if name and password:
                        users[name] = password
        return users

    for pair in raw.replace("\n", ",").split(","):
        if ":" not in pair:
            continue
        name, _, password = pair.partition(":")
        name = name.strip().lower()
        if name and password:
            users[name] = password

    return users


USERS = load_users()


# Optional hashed credentials live in python/users.json so the board works
# without any dashboard setup. Only scrypt hashes are stored, never passwords.
# Entries in AUTH_USERS take precedence over the file for the same username.

def load_hashed_users():
    path = Path(__file__).resolve().parent / "users.json"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    users = {}

    for name, record in data.items():
        if isinstance(record, dict) and record.get("salt") and record.get("hash"):
            users[str(name).strip().lower()] = record

    return users


HASHED_USERS = load_hashed_users()


def default_users():
    password = secrets.token_urlsafe(9)
    print(
        "[AUTH] No credentials configured. Temporary login -> "
        f"simon / {password}  (set AUTH_USERS on Render to change it)",
        flush=True
    )
    return {"simon": password}


if not USERS and not HASHED_USERS:
    USERS = default_users()


def known_user(username):
    return username in USERS or username in HASHED_USERS


def verify_password(username, password):
    record = HASHED_USERS.get(username) if username not in USERS else None

    if record:
        try:
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(record["salt"]),
                n=int(record.get("n", 16384)),
                r=int(record.get("r", 8)),
                p=int(record.get("p", 1)),
                dklen=32
            )
        except (ValueError, TypeError):
            return False

        return hmac.compare_digest(digest.hex(), str(record["hash"]))

    expected = USERS.get(username)

    return bool(expected) and hmac.compare_digest(expected, password)


if USERS or HASHED_USERS:
    print(
        "[AUTH] Enabled for: " + ", ".join(sorted(set(USERS) | set(HASHED_USERS))),
        flush=True
    )

SECRET = (
    os.environ.get("SECRET_KEY")
    or hashlib.sha256(
        (
            "animelist-session::"
            + "::".join(sorted(set(USERS) | set(HASHED_USERS)))
            + "::"
            + "::".join(sorted(str(r.get("hash")) for r in HASHED_USERS.values()))
        ).encode("utf-8")
    ).hexdigest()
)
SECRET_BYTES = SECRET.encode("utf-8")

TOKEN_DAYS = int(os.environ.get("TOKEN_DAYS", "30"))


def _b64encode(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload):
    return _b64encode(hmac.new(SECRET_BYTES, payload.encode("ascii"), hashlib.sha256).digest())


def issue_token(username):
    payload = _b64encode(
        json.dumps(
            {"u": username, "exp": int(time.time()) + TOKEN_DAYS * 86400},
            separators=(",", ":")
        ).encode("utf-8")
    )

    return payload + "." + _sign(payload)


def verify_token(token):
    if not token or "." not in token:
        return None

    payload, _, signature = token.partition(".")

    if not hmac.compare_digest(_sign(payload), signature):
        return None

    try:
        data = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    expires = data.get("exp")

    if not isinstance(expires, (int, float)) or time.time() > expires:
        return None

    user = str(data.get("u") or "").lower()

    return user if known_user(user) else None


def request_user():
    header = request.headers.get("Authorization", "")

    if header.lower().startswith("bearer "):
        return verify_token(header[7:].strip())

    return None


PUBLIC_ENDPOINTS = {"home", "health", "session_status", "login", "logout"}


@app.before_request
def require_token():
    if request.method == "OPTIONS":
        return None

    if request.endpoint in PUBLIC_ENDPOINTS:
        return None

    user = request_user()

    if not user:
        return jsonify({"error": "authentication required"}), 401

    g.user = user

    return None


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

BATCH_SIZE = 10
MAX_WORKERS = 5
REQUEST_TIMEOUT = 5


def find_data_file():
    for path in DATA_FILE_CANDIDATES:
        if path.is_file():
            print(f"[DATA] Found sites.json: {path}")
            return path

    print("[ERROR] sites.json not found!")
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


def check_site(index, site):
    original_url = get_primary_url(site.get("url"))

    if not original_url:
        return {
            "index": index,
            "name": site.get("name", "Unknown"),
            "url": None,
            "status": "unverified",
            "status_code": None
        }

    url = original_url

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AniQuestChecker/1.0)"
    }

    try:
        response = requests.head(
            url,
            timeout=REQUEST_TIMEOUT,
            headers=headers,
            allow_redirects=True
        )

        if response.status_code in (405, 501):
            response.close()

            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
                allow_redirects=True,
                stream=True
            )

        code = response.status_code
        response.close()

        if 200 <= code < 500:
            status = "online"
        else:
            status = "unverified"

    except requests.Timeout:
        status = "unverified"
        code = None

    except requests.RequestException as error:
        print(f"[CHECK ERROR] {url}: {error}")
        status = "offline"
        code = None

    return {
        "index": index,
        "name": site.get("name", "Unknown"),
        "url": original_url,
        "status": status,
        "status_code": code
    }


@app.route("/session")
def session_status():
    user = request_user()

    return jsonify({
        "authenticated": bool(user),
        "user": user,
        "token_days": TOKEN_DAYS
    })


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))

    if not known_user(username) or not verify_password(username, password):
        time.sleep(0.4)
        return jsonify({"error": "Invalid username or password"}), 401

    return jsonify({
        "authenticated": True,
        "user": username,
        "token": issue_token(username),
        "token_days": TOKEN_DAYS
    })


@app.route("/logout", methods=["POST"])
def logout():
    # Tokens are stateless; the client drops its copy. Endpoint kept so older
    # clients (and the UI) have a single sign-out call.
    return jsonify({"authenticated": False})


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
    return jsonify({
        "status": "ok",
        "sites_loaded": len(load_sites())
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


@app.route("/check-batch", methods=["POST"])
def check_batch():
    sites_list = load_sites()

    data = request.get_json(silent=True) or {}
    indices = data.get("indices")

    if not isinstance(indices, list) or not indices:
        return jsonify({"error": "Provide a non-empty indices list"}), 400

    if len(indices) > BATCH_SIZE:
        return jsonify({
            "error": f"Maximum {BATCH_SIZE} websites per batch"
        }), 400

    if any(
        not isinstance(index, int)
        or isinstance(index, bool)
        or index < 0
        or index >= len(sites_list)
        for index in indices
    ):
        return jsonify({"error": "Invalid site index"}), 400

    unique_indices = list(dict.fromkeys(indices))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(
            lambda index: check_site(index, sites_list[index]),
            unique_indices
        ))

    return jsonify({
        "count": len(results),
        "results": results
    })


@app.route("/status")
def status():
    sites_list = load_sites()

    results = [
        {
            "name": site.get("name", "Unknown"),
            "url": get_primary_url(site.get("url")),
            "status": "unverified",
            "status_code": None
        }
        for site in sites_list
    ]

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
