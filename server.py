#!/usr/bin/env python3
"""
Seifosphere Archive Server
Serves dashboard and API endpoints for the iMessage archive.

Start: python3 /Users/sizzle/imessage_export_IPHONE/server.py
"""

import os
import json
import shutil
import http.server
import socketserver
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.resolve()   # /Users/sizzle/imessage_export_IPHONE
DOWNLOADS   = Path.home() / "Downloads"
PORT        = 8765

# Maps folder names to category labels used in the dashboard
CATEGORY_MAP = {
    "Business":   "Business",
    "Deals":      "Deals",
    "Litigation": "Litigation",
    "Family":     "Family",
    "Friends":    "Friends",
    "Groups":     "Groups",
    "Personal":   "Personal",
    "_review":    "Review",
    "_unmatched": "Unmatched",
    "Codes":      "Codes",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def scan_files():
    """
    Recursively scans the archive folder structure and returns a list of
    file dicts:  { name, category, subfolder, path }
    path is relative to BASE_DIR so it can be used as a URL path.
    """
    files = []
    for folder, category in CATEGORY_MAP.items():
        folder_path = BASE_DIR / folder
        if not folder_path.exists():
            continue
        for item in sorted(folder_path.rglob("*.html")):
            rel = item.relative_to(BASE_DIR)
            parts = rel.parts  # e.g. ('Deals', 'Air_Experts', 'contact.html')
            subfolder = parts[1] if len(parts) > 2 else ""
            name = item.stem  # filename without .html
            files.append({
                "name":      name,
                "category":  category,
                "subfolder": subfolder,
                "path":      str(rel).replace("\\", "/"),   # Windows-safe
            })
    return files


def get_deals():
    """Returns list of deal subfolder names under Deals/."""
    deals_dir = BASE_DIR / "Deals"
    if not deals_dir.exists():
        return []
    return sorted([d.name for d in deals_dir.iterdir() if d.is_dir()])


def get_contact_map():
    """
    Builds a dict mapping phone number digits → contact name.
    First checks macOS AddressBook, then falls back to iMessage chat.db display names.
    """
    import glob
    contacts = {}

    # ── 1. AddressBook ────────────────────────────────────────────────────────
    patterns = [
        str(Path.home() / "Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb"),
        str(Path.home() / "Library/Application Support/AddressBook/AddressBook-v22.abcddb"),
    ]
    db_path = None
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            db_path = matches[0]
            break

    if db_path:
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT r.ZFIRSTNAME, r.ZLASTNAME, p.ZFULLNUMBER
                FROM ZABCDRECORD r
                JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
                WHERE p.ZFULLNUMBER IS NOT NULL
            """)
            for first, last, number in cur.fetchall():
                digits = ''.join(c for c in (number or '') if c.isdigit())
                if not digits:
                    continue
                name_parts = [x for x in [first, last] if x]
                name = ' '.join(name_parts) if name_parts else None
                if name:
                    contacts[digits] = name
                    if len(digits) > 10:
                        contacts[digits[-10:]] = name
            conn.close()
        except Exception:
            pass

    # ── 2. iMessage chat.db fallback ──────────────────────────────────────────
    chat_db = Path.home() / "Library/Messages/chat.db"
    if chat_db.exists():
        try:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(str(chat_db))
            cur = conn.cursor()
            # Get display names from chat table (group chats and named threads)
            cur.execute("""
                SELECT h.id, h.uncanonicalized_id
                FROM handle h
                WHERE h.id IS NOT NULL
            """)
            for handle_id, uncanon in cur.fetchall():
                digits = ''.join(c for c in (handle_id or '') if c.isdigit())
                if not digits or digits in contacts:
                    continue
                # Use uncanonicalized_id if it looks like a name (has letters)
                if uncanon and any(c.isalpha() for c in uncanon):
                    contacts[digits] = uncanon
                    if len(digits) > 10:
                        contacts[digits[-10:]] = uncanon

            # Also check chat display names
            cur.execute("""
                SELECT c.chat_identifier, c.display_name
                FROM chat c
                WHERE c.display_name IS NOT NULL AND c.display_name != ''
            """)
            for chat_id, display_name in cur.fetchall():
                digits = ''.join(c for c in (chat_id or '') if c.isdigit())
                if digits and digits not in contacts:
                    contacts[digits] = display_name
                    if len(digits) > 10:
                        contacts[digits[-10:]] = display_name

            conn.close()
        except Exception:
            pass

    return contacts


def resolve_filename(filename, contact_map):
    """
    Given a filename like '+12015625575.html', returns a display name
    by looking up the number in contact_map. Returns None if not found.
    """
    import re
    # Extract all phone-number-like sequences from filename
    stem = filename.replace('.html', '')
    # Find all digit sequences of 10-11 digits
    numbers = re.findall(r'\d{10,11}', stem)
    names = []
    for num in numbers:
        # Try full number and last 10 digits
        name = contact_map.get(num) or contact_map.get(num[-10:])
        if name and name not in names:
            names.append(name)
    return ', '.join(names) if names else None


def scan_new_files():
    """Scans ~/Downloads for HTML files not already in the archive."""
    existing = {f.name for f in BASE_DIR.rglob("*.html")}
    contact_map = get_contact_map()
    new_files = []
    for i, item in enumerate(sorted(DOWNLOADS.glob("*.html"))):
        if item.name not in existing:
            display = resolve_filename(item.name, contact_map)
            new_files.append({
                "id": str(i),
                "name": item.name,
                "display": display or item.stem,  # resolved name or raw filename
                "resolved": display is not None,
            })
    return new_files


def send_json(handler, data, status=200):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler, msg, status=400):
    send_json(handler, {"error": msg}, status)


# ── Request Handler ────────────────────────────────────────────────────────────

class ArchiveHandler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        # Quieter logs — only print API calls and errors
        try:
            if "/api/" in str(args[0] if args else "") or str(args[1]) not in ("200", "304"):
                super().log_message(format, *args)
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        # ── API: /api/preview ─────────────────────────────────────────────────
        if path == "/api/preview":
            from urllib.parse import parse_qs
            params = parse_qs(parsed.query)
            filename = params.get('file', [''])[0]
            if not filename:
                return send_error(self, "file required")
            src = DOWNLOADS / filename
            if not src.exists():
                return send_error(self, f"File not found: {filename}", 404)
            content = src.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)

        # ── API: /api/status ──────────────────────────────────────────────────
        elif path == "/api/status":
            send_json(self, {"status": "ok", "base_dir": str(BASE_DIR)})

        # ── API: /api/files ───────────────────────────────────────────────────
        elif path == "/api/files":
            files = scan_files()
            deals = get_deals()
            send_json(self, {
                "files": files,
                "deals": deals,
                "total": len(files),
            })

        # ── API: /api/new-files ───────────────────────────────────────────────
        elif path == "/api/new-files":
            send_json(self, {"files": scan_new_files()})

        # ── API: /api/deals ───────────────────────────────────────────────────
        elif path == "/api/deals":
            send_json(self, {"deals": get_deals()})

        # ── Static file serving (dashboard, HTML archives, indexes) ───────────
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        # ── API: /api/skip ────────────────────────────────────────────────────
        if path == "/api/skip":
            filename = body.get("file", "")
            if not filename:
                return send_error(self, "file required")
            src = DOWNLOADS / filename
            if src.exists():
                src.unlink()
            send_json(self, {"skipped": filename})

        # ── API: /api/move ────────────────────────────────────────────────────
        elif path == "/api/move":
            filename    = body.get("file", "")
            destination = body.get("destination", "")   # e.g. "Business" or "Deals/Air_Experts"

            if not filename or not destination:
                return send_error(self, "file and destination required")

            src = DOWNLOADS / filename
            if not src.exists():
                return send_error(self, f"Source file not found: {filename}", 404)

            dest_dir = BASE_DIR / destination
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest_dir / filename))
            send_json(self, {"moved": filename, "to": destination})

        # ── API: /api/create-deal ─────────────────────────────────────────────
        elif path == "/api/create-deal":
            name = body.get("name", "").strip()
            if not name:
                return send_error(self, "name required")
            # Sanitize: replace spaces with underscores, strip unsafe chars
            safe = "".join(c if c.isalnum() or c in "_-." else "_" for c in name)
            deal_dir = BASE_DIR / "Deals" / safe
            if deal_dir.exists():
                return send_error(self, f"Deal folder already exists: {safe}")
            deal_dir.mkdir(parents=True)
            send_json(self, {"created": safe, "path": str(deal_dir)})

        # ── API: /api/move-archived ───────────────────────────────────────────
        elif path == "/api/move-archived":
            rel_path    = body.get("path", "")       # e.g. "Business/John_Smith.html"
            destination = body.get("destination", "") # e.g. "Deals/Air_Experts"

            if not rel_path or not destination:
                return send_error(self, "path and destination required")

            src = BASE_DIR / rel_path
            if not src.exists():
                return send_error(self, f"Source file not found: {rel_path}", 404)

            dest_dir = BASE_DIR / destination
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / src.name

            # Avoid overwriting if a file with same name exists in dest
            if dest_file.exists() and dest_file != src:
                stem = src.stem
                dest_file = dest_dir / f"{stem}_moved.html"

            shutil.move(str(src), str(dest_file))
            send_json(self, {"moved": rel_path, "to": destination})

        else:
            send_error(self, "Not found", 404)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), ArchiveHandler) as httpd:
        httpd.allow_reuse_address = True
        print(f"──────────────────────────────────────────")
        print(f"  Seifosphere Archive Server")
        print(f"  http://localhost:{PORT}/dashboard.html")
        print(f"  Base: {BASE_DIR}")
        print(f"──────────────────────────────────────────")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
