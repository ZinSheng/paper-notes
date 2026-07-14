"""Shared utilities for the paper-notes skill.

Provides a minimal Zotero Web API v3 client (config, requests with retry,
pagination) extracted from the zotero skill's zotero.py conventions, plus
HTML placeholder replacement helpers. Zero external dependencies — stdlib only.

This module is imported by fetch_annotations.py, manage_reading_list.py,
build_paper_html.py and build_dashboard.py.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ─── Constants ──────────────────────────────────────────────────────────────

API_BASE = "https://api.zotero.org"
API_VERSION = "3"
PAGE_LIMIT = 100
_MAX_RETRIES = 2          # retries on 429 / 503
_RETRY_BACKOFFS = [2, 4]  # seconds

# Output root, relative to the current working directory (overridable via env).
# Previously hardcoded to a specific project path, which broke when the skill
# was used from a different project. Now defaults to <cwd>/outputs/paper-notes.
_OUTPUT_ROOT = os.environ.get("LITERATURE_READER_OUTPUT_DIR")
OUTPUT_DIR = Path(_OUTPUT_ROOT) if _OUTPUT_ROOT else Path.cwd() / "outputs" / "paper-notes"
PAPERS_DIR = OUTPUT_DIR / "papers"
MANIFEST_PATH = OUTPUT_DIR / "reading-list.json"
DASHBOARD_PATH = OUTPUT_DIR / "dashboard.html"
# Per-deployment settings (language, default accent, Zotero connection toggle).
# Written by `manage_reading_list.py init`; read by the build scripts so that
# every generated page honors the user's first-call choices.
CONFIG_PATH = OUTPUT_DIR / "litreader.config.json"

PAPER_KEY_RE = re.compile(r"(?:[A-Z0-9]{8}|local-[a-f0-9]{8})\Z")


def validate_paper_key(key):
    """Validate keys before using them in output paths."""
    if not isinstance(key, str) or not PAPER_KEY_RE.fullmatch(key):
        raise ValueError("invalid paper key: expected 8-char Zotero key or local-XXXXXXXX")
    return key

DEFAULT_CONFIG = {
    "initialized": False,
    "language": "zh",          # "zh" | "en"
    "default_accent": "blue",  # "rose" | "green" | "blue"
    "connect_zotero": True,    # False → no heatmap, manual PDF, hide Zotero sections
}

# Self-hosted web fonts (woff2) shipped with the skill. Copied into the output
# dir on every build so generated pages render offline / where Google Fonts is
# blocked. Source = <skill>/assets/fonts; destination = <output>/fonts.
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_SRC = ASSETS_DIR / "fonts"
FONTS_DST = OUTPUT_DIR / "fonts"

# The companion zotero skill's executable.
ZOTERO_PY = Path.cwd() / ".codex" / "skills" / "zotero" / "scripts" / "zotero.py"


# ─── Config ─────────────────────────────────────────────────────────────────

def _load_zotero_env_from_rc():
    """Best-effort fallback: read Zotero vars from shell rc files.

    The Bash tool's non-interactive shell does NOT auto-source ~/.zshrc, so the
    ZOTERO_API_KEY / ZOTERO_USER_ID exported there may be absent from os.environ.
    Parse a few common rc files so the skill still works without an explicit
    `source ~/.zshrc` beforehand. Only fills vars that are not already set.
    """
    rc_candidates = (
        os.path.expanduser("~/.zshrc"),
        os.path.expanduser("~/.bashrc"),
        os.path.expanduser("~/.zprofile"),
        os.path.expanduser("~/.bash_profile"),
    )
    wanted = ("ZOTERO_API_KEY", "ZOTERO_USER_ID", "ZOTERO_GROUP_ID")
    found = {}
    for rc in rc_candidates:
        try:
            with open(rc, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    s = line.strip()
                    # Match both `export NAME=value` and bare `NAME=value`.
                    m = re.match(r"(?:export\s+)?(ZOTERO_\w+)=(.*)", s)
                    if not m:
                        continue
                    name, val = m.group(1), m.group(2).strip()
                    if name not in wanted or name in found:
                        continue
                    # Strip surrounding quotes.
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                        val = val[1:-1]
                    found[name] = val
        except OSError:
            continue
    for name, val in found.items():
        if name not in os.environ or not os.environ[name].strip():
            os.environ[name] = val
    return found


def get_zotero_config():
    """Return (api_key, prefix) from environment.

    prefix is '/users/<id>' or '/groups/<id>'. Exits with an error message if
    the required environment variables are not set. If they are missing from the
    process environment, an attempt is made to load them from shell rc files
    (see _load_zotero_env_from_rc).
    """
    # Fallback: non-interactive shells may not have sourced ~/.zshrc.
    if not os.environ.get("ZOTERO_API_KEY", "").strip() or not (
        os.environ.get("ZOTERO_USER_ID", "").strip()
        or os.environ.get("ZOTERO_GROUP_ID", "").strip()
    ):
        _load_zotero_env_from_rc()

    api_key = os.environ.get("ZOTERO_API_KEY", "").strip()
    if not api_key:
        sys.stderr.write(
            "Error: ZOTERO_API_KEY environment variable is not set.\n"
            "Create a key at https://www.zotero.org/settings/keys and export it.\n"
        )
        sys.exit(1)

    user_id = os.environ.get("ZOTERO_USER_ID", "").strip()
    group_id = os.environ.get("ZOTERO_GROUP_ID", "").strip()
    if user_id:
        prefix = "/users/" + user_id
    elif group_id:
        prefix = "/groups/" + group_id
    else:
        sys.stderr.write(
            "Error: either ZOTERO_USER_ID or ZOTERO_GROUP_ID must be set.\n"
        )
        sys.exit(1)

    return api_key, prefix


# ─── HTTP ───────────────────────────────────────────────────────────────────

def _request(url, api_key, params=None):
    """Perform a single GET. Returns (body_str, headers_dict). Raises on non-2xx."""
    if params:
        qs = urllib.parse.urlencode(params, doseq=True)
        url = url + ("&" if "?" in url else "?") + qs

    req = urllib.request.Request(url)
    req.add_header("Zotero-API-Key", api_key)
    req.add_header("Zotero-API-Version", API_VERSION)
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            headers = {k: v for k, v in resp.headers.items()}
            return body, headers
    except urllib.error.HTTPError as e:
        # Re-raise with status so callers can decide on retry.
        raise _HttpError(e.code, e.reason, e.headers)


class _HttpError(Exception):
    def __init__(self, code, reason, headers):
        self.code = code
        self.reason = reason
        self.headers = headers or {}
        super().__init__("HTTP %s %s" % (code, reason))


def api_request(path, api_key, params=None):
    """GET a Zotero API path with retry on 429/503.

    Returns (body_str, headers_dict).
    """
    url = API_BASE + path if path.startswith("/") else API_BASE + "/" + path
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return _request(url, api_key, params)
        except _HttpError as e:
            last_err = e
            if e.code in (429, 503) and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
                sys.stderr.write(
                    "Rate limited (%s). Retrying in %ds (attempt %d/%d)...\n"
                    % (e.code, wait, attempt + 1, _MAX_RETRIES)
                )
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
                sys.stderr.write(
                    "Network error (%s). Retrying in %ds (attempt %d/%d)...\n"
                    % (e.reason, wait, attempt + 1, _MAX_RETRIES)
                )
                time.sleep(wait)
                continue
            raise
    raise last_err  # pragma: no cover


def api_get_json(path, api_key, params=None):
    """GET a path and return (parsed_json, headers_dict)."""
    body, headers = api_request(path, api_key, params)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = []
    return data, headers


def api_get_bytes(path, api_key, params=None):
    """GET a path and return raw bytes (for binary downloads like PDF files).

    Uses the same retry/backoff as api_request. Returns bytes.
    """
    url = API_BASE + path if path.startswith("/") else API_BASE + "/" + path
    if params:
        qs = urllib.parse.urlencode(params, doseq=True)
        url = url + ("&" if "?" in url else "?") + qs
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        req = urllib.request.Request(url)
        req.add_header("Zotero-API-Key", api_key)
        req.add_header("Zotero-API-Version", API_VERSION)
        req.add_header("Accept", "application/pdf")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = _HttpError(e.code, e.reason, e.headers)
            if e.code in (429, 503) and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
                time.sleep(wait)
                continue
            raise last_err
        except urllib.error.URLError as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
                time.sleep(wait)
                continue
            raise
    raise last_err  # pragma: no cover


def paginate_all(path, api_key, extra_params=None):
    """Fetch all pages of a collection endpoint.

    Uses limit=100 + start offset, driven by the Total-Results header.
    Returns a flat list of item dicts.
    """
    results = []
    start = 0
    while True:
        params = {"limit": PAGE_LIMIT, "start": start}
        if extra_params:
            params.update(extra_params)
        data, headers = api_get_json(path, api_key, params)
        if isinstance(data, list):
            results.extend(data)
        elif isinstance(data, dict) and "results" in data:
            results.extend(data["results"])
        else:
            results.append(data)

        total = headers.get("Total-Results") or headers.get("total-results")
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = len(results)
        if len(results) >= total or not data:
            break
        start += PAGE_LIMIT
    return results


def fetch_collection_tree():
    """Fetch the full Zotero collection tree.

    Returns a flat list of {key, name, parent} where `parent` is the parent
    collection key (or None for top-level). Used to reconstruct nested
    collection hierarchies in the dashboard. Returns [] on any failure so
    callers can fall back to per-paper stored collection data.
    """
    try:
        api_key, prefix = get_zotero_config()
    except SystemExit:
        return []
    try:
        data = paginate_all(prefix + "/collections", api_key)
    except Exception:
        return []
    out = []
    for c in (data or []):
        d = c.get("data", c)
        key = d.get("key")
        if not key:
            continue
        out.append({
            "key": key,
            "name": d.get("name", key),
            "parent": d.get("parentCollection"),
        })
    return out


# ─── HTML placeholder replacement ────────────────────────────────────────────

def apply_placeholders(template, replacements, registry):
    """Replace __TOKEN__ placeholders in template, then clean leftovers.

    Args:
        template: the HTML template string.
        replacements: {__TOKEN__: value} dict. Values are str()-ified.
        registry: list of all known __TOKEN__ strings; any not replaced are
            cleared to empty string (prevents stray markers in output).

    Returns the rendered HTML string.
    """
    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, str(value))
    for placeholder in registry:
        if placeholder in html:
            html = html.replace(placeholder, "")
    return html


# ─── Paths ──────────────────────────────────────────────────────────────────

def zotero_py_path():
    """Return the path to the companion zotero skill's executable."""
    return ZOTERO_PY


def local_pdf_path(attachment_key):
    """Return path to a locally-stored Zotero PDF if present, else None.

    Zotero desktop stores files under <dataDir>/storage/<attachmentKey>/.
    The Web API returns 404 for these when file sync hasn't pushed them to
    the cloud (common with large libraries over the 300MB free quota). This
    fallback lets figure extraction / full-text reading work offline.

    dataDir defaults to ~/Zotero (Zotero's default); override with the
    ZOTERO_DATA_DIR environment variable.
    """
    data_dir = os.environ.get("ZOTERO_DATA_DIR", "").strip()
    if not data_dir:
        data_dir = str(Path.home() / "Zotero")
    storage_dir = Path(data_dir) / "storage" / attachment_key
    if not storage_dir.is_dir():
        return None
    pdfs = sorted(storage_dir.glob("*.pdf"))
    return str(pdfs[0]) if pdfs else None


def local_fulltext_path(attachment_key):
    """Return path to Zotero's extracted full-text cache if present, else None.

    Zotero writes <dataDir>/storage/<attachmentKey>/.zotero-ft-cache containing
    the PDF's extracted plain text (used for full-text search). Handy for
    summary generation when the PDF itself isn't downloadable via the API.
    """
    data_dir = os.environ.get("ZOTERO_DATA_DIR", "").strip()
    if not data_dir:
        data_dir = str(Path.home() / "Zotero")
    ft = Path(data_dir) / "storage" / attachment_key / ".zotero-ft-cache"
    return str(ft) if ft.is_file() else None


def ensure_output_dirs():
    """Create the output directory tree if it does not exist."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)


def copy_fonts():
    """Copy self-hosted web fonts into the output dir (no-op if absent).

    Generated pages reference ./fonts/fonts.css (or ../fonts/fonts.css from
    papers/). Copying the woff2 files + fonts.css here keeps pages
    offline-capable and removes any dependency on the Google Fonts CDN
    (which is blocked/unreliable in some regions).
    """
    if not FONTS_SRC.is_dir():
        return
    import shutil
    FONTS_DST.mkdir(parents=True, exist_ok=True)
    for item in FONTS_SRC.iterdir():
        if item.is_file():
            shutil.copy2(item, FONTS_DST / item.name)


# ─── Manifest I/O ────────────────────────────────────────────────────────────

def load_manifest():
    """Load reading-list.json. Returns the manifest dict, or an empty skeleton."""
    ensure_output_dirs()
    if MANIFEST_PATH.exists():
        try:
            with MANIFEST_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "generated_at": now_iso(), "papers": []}


def save_manifest(manifest):
    """Write the manifest atomically."""
    ensure_output_dirs()
    manifest["generated_at"] = now_iso()
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    tmp.replace(MANIFEST_PATH)


# ─── Skill config (first-call preferences) ──────────────────────────────────

def load_config():
    """Load litreader.config.json merged over DEFAULT_CONFIG.

    Returns a dict with keys: initialized, language, default_accent,
    connect_zotero. Missing or corrupt file → defaults (initialized=False).
    """
    cfg = dict(DEFAULT_CONFIG)
    ensure_output_dirs()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items()
                            if k in DEFAULT_CONFIG})
        except (json.JSONDecodeError, OSError):
            pass
    # Normalize / guard against typos.
    if cfg["language"] not in ("zh", "en"):
        cfg["language"] = "zh"
    if cfg["default_accent"] not in ("rose", "green", "blue"):
        cfg["default_accent"] = "blue"
    cfg["connect_zotero"] = bool(cfg["connect_zotero"])
    return cfg


def save_config(cfg):
    """Write the config atomically. Only persists known keys."""
    ensure_output_dirs()
    data = {k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG}
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(CONFIG_PATH)


# ─── Time helpers ───────────────────────────────────────────────────────────

def now_iso():
    """Return current time as an ISO 8601 string in the local timezone."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def html_escape(text):
    """Escape &, <, >, \", ' for safe HTML insertion."""
    if text is None:
        return ""
    text = str(text)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
