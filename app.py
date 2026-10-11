"""A private, single-owner journal with photo galleries."""
from __future__ import annotations

import hmac
import io
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, g, redirect, render_template, request, send_from_directory,
    session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_DIR / "journal.sqlite3"

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
app.config.update(
    SECRET_KEY=os.environ.get("SESSION_SECRET", ""),
    MAX_CONTENT_LENGTH=160 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)
PASSWORD = os.environ.get("DIARY_PASSWORD", "")
# The password comes from the deployment environment; it is never kept in the database.
PASSWORD_HASH = generate_password_hash(PASSWORD) if PASSWORD else ""
SITE_TITLE = os.environ.get("SITE_TITLE", "The Critchell Journal").strip() or "My Journal"
CATEGORIES = {
    "diary": ("Everyday", "Everyday moments"),
    "concert": ("Concert", "Music & live shows"),
    "family": ("Family", "Family memories"),
    "trip": ("Travel", "Places & adventures"),
    "milestone": ("Milestone", "Big moments"),
    "other": ("Other", "All the rest"),
}
ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
ATTEMPTS_LOCK = threading.Lock()
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PHOTOS_PER_UPLOAD = 12
MAX_PHOTOS_PER_ENTRY = 60
Image.MAX_IMAGE_PIXELS = 35_000_000


def local_today() -> str:
    return datetime.now(ZoneInfo("Europe/London")).date().isoformat()


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DATABASE, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def initialize_db():
    with sqlite3.connect(DATABASE, timeout=30) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'diary',
                location TEXT NOT NULL DEFAULT '',
                mood TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                thumb_filename TEXT NOT NULL,
                original_name TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS entries_by_date ON entries(entry_date DESC, id DESC);
            CREATE INDEX IF NOT EXISTS photos_by_entry ON photos(entry_id, sort_order, id);
        """)


initialize_db()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.context_processor
def inject_globals():
    return {
        "csrf_token": csrf_token,
        "site_title": SITE_TITLE,
        "categories": CATEGORIES,
        "today": local_today(),
    }


@app.before_request
def check_post_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        supplied = request.form.get("_csrf", "") or request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(str(supplied), str(session.get("csrf_token", ""))) or not supplied:
            abort(400, description="This form expired. Refresh the page and try again.")


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


def current_session_is_authenticated():
    if not session.get("authenticated") or not PASSWORD or not app.config["SECRET_KEY"]:
        return False
    expected = hmac.new(
        app.config["SECRET_KEY"].encode("utf-8"), PASSWORD.encode("utf-8"), "sha256"
    ).hexdigest()
    return hmac.compare_digest(session.get("password_version", ""), expected)


def login_required(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not current_session_is_authenticated():
            return redirect(url_for("login", next=request.path))
        return func(*args, **kwargs)
    return wrapped


def login_blocked(key: str) -> bool:
    now = time.monotonic()
    with ATTEMPTS_LOCK:
        attempts = ATTEMPTS[key]
        while attempts and now - attempts[0] > 900:
            attempts.popleft()
        return len(attempts) >= 8


def login_failure(key: str):
    with ATTEMPTS_LOCK:
        ATTEMPTS[key].append(time.monotonic())


def login_success(key: str):
    with ATTEMPTS_LOCK:
        ATTEMPTS.pop(key, None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_session_is_authenticated():
        return redirect(url_for("dashboard"))
    if not PASSWORD or not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 24:
        return render_template("setup.html"), 503
    if request.method == "POST":
        key = request.remote_addr or "unknown"
        if login_blocked(key):
            flash("Too many attempts. Please try again in 15 minutes.", "error")
        elif check_password_hash(PASSWORD_HASH, request.form.get("password", "")):
            login_success(key)
            session.clear()
            session["authenticated"] = True
            session["password_version"] = hmac.new(
                app.config["SECRET_KEY"].encode("utf-8"), PASSWORD.encode("utf-8"), "sha256"
            ).hexdigest()
            session.permanent = True
            session["csrf_token"] = secrets.token_urlsafe(32)
            # Only permit relative paths as return destinations.
            dest = request.args.get("next", "")
            if not dest.startswith("/") or dest.startswith("//") or "\\" in dest:
                dest = url_for("dashboard")
            return redirect(dest)
        else:
            login_failure(key)
            flash("That password isn't quite right. Please try again.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You've safely signed out.", "success")
    return redirect(url_for("login"))


def hydrate_entries(rows):
    entries = [dict(row) for row in rows]
    if not entries:
        return entries
    db = get_db()
    ids = [row["id"] for row in entries]
    qmarks = ",".join("?" for _ in ids)
    photos = db.execute(
        f"SELECT * FROM photos WHERE entry_id IN ({qmarks}) ORDER BY sort_order, id", ids
    ).fetchall()
    groups = defaultdict(list)
    for photo in photos:
        groups[photo["entry_id"]].append(dict(photo))
    for entry in entries:
        entry["photos"] = groups[entry["id"]]
        entry["cover"] = entry["photos"][0] if entry["photos"] else None
    return entries


@app.get("/")
@login_required
def dashboard():
    db = get_db()
    recent = hydrate_entries(db.execute(
        "SELECT * FROM entries ORDER BY entry_date DESC, id DESC LIMIT 6"
    ).fetchall())
    total = db.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]
    concerts = db.execute("SELECT COUNT(*) AS n FROM entries WHERE category='concert'").fetchone()["n"]
    photos = db.execute("SELECT COUNT(*) AS n FROM photos").fetchone()["n"]
    years = db.execute("SELECT COUNT(DISTINCT substr(entry_date,1,4)) AS n FROM entries").fetchone()["n"]
    available_years = [row[0] for row in db.execute(
        "SELECT DISTINCT substr(entry_date, 1, 4) AS year FROM entries ORDER BY year DESC"
    ).fetchall()]
    return render_template("dashboard.html", recent=recent, total=total, concerts=concerts,
                           photos=photos, years=years, available_years=available_years)


@app.get("/entries")
@login_required
def entries():
    db = get_db()
    query = request.args.get("q", "").strip()[:120]
    category = request.args.get("category", "")
    year = request.args.get("year", "")
    where = []
    params = []
    if query:
        where.append("(title LIKE ? OR body LIKE ? OR location LIKE ?)")
        params.extend([f"%{query}%"] * 3)
    if category in CATEGORIES:
        where.append("category = ?")
        params.append(category)
    else:
        category = ""
    available_years = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(entry_date,1,4) AS year FROM entries ORDER BY year DESC"
    ).fetchall()]
    if year in available_years:
        where.append("substr(entry_date,1,4) = ?")
        params.append(year)
    else:
        year = ""
    clause = " WHERE " + " AND ".join(where) if where else ""
    result = hydrate_entries(db.execute(
        "SELECT * FROM entries" + clause + " ORDER BY entry_date DESC, id DESC", params
    ).fetchall())
    return render_template("entries.html", entries=result, q=query, active_category=category,
                           active_year=year, available_years=available_years)


@app.get("/concerts")
@login_required
def concerts():
    return redirect(url_for("entries", category="concert"))


@app.get("/gallery")
@login_required
def gallery():
    photo_rows = get_db().execute("""
        SELECT p.id, p.entry_id, e.title, e.entry_date, e.category
        FROM photos AS p JOIN entries AS e ON e.id = p.entry_id
        ORDER BY e.entry_date DESC, p.id DESC LIMIT 300
    """).fetchall()
    return render_template("gallery.html", photo_rows=photo_rows)



def validate_entry(form):
    title = form.get("title", "").strip()
    date = form.get("entry_date", "").strip()
    category = form.get("category", "diary").strip()
    body = form.get("body", "").strip()
    location = form.get("location", "").strip()
    mood = form.get("mood", "").strip()
    if not title or len(title) > 140:
        raise ValueError("Please add a title (up to 140 characters).")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Please choose a valid date.") from exc
    if category not in CATEGORIES:
        raise ValueError("Please select a valid category.")
    if len(location) > 180 or len(mood) > 60 or len(body) > 40000:
        raise ValueError("One of the text fields is too long.")
    return dict(title=title, entry_date=date, category=category,
                body=body, location=location, mood=mood)


def _to_rgb(im):
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im.convert("RGBA"))
        return bg.convert("RGB")
    return im.convert("RGB")


def process_uploads(files):
    """Validate, transcode and strip metadata before any database changes."""
    files = [f for f in files if f and f.filename]
    if len(files) > MAX_PHOTOS_PER_UPLOAD:
        raise ValueError(f"Please upload no more than {MAX_PHOTOS_PER_UPLOAD} photos at once.")
    saved = []
    try:
        for file in files:
            raw = file.read(MAX_IMAGE_BYTES + 1)
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("Each photo must be 12 MB or smaller.")
            try:
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format not in ("JPEG", "PNG", "WEBP", "GIF"):
                        raise ValueError("Use JPG, PNG, WEBP or GIF images.")
                    source.seek(0)
                    image = _to_rgb(ImageOps.exif_transpose(source))
                    if image.width * image.height > 35_000_000:
                        raise ValueError("One of the photos is too large to process.")
                    image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                    thumb = ImageOps.fit(image, (740, 560), method=Image.Resampling.LANCZOS)
                    name = uuid.uuid4().hex
                    full_name, thumb_name = f"{name}.webp", f"{name}_thumb.webp"
                    saved.append(dict(filename=full_name, thumb_filename=thumb_name,
                                      original_name=file.filename[:220]))
                    image.save(UPLOAD_DIR / full_name, "WEBP", quality=88, method=5)
                    thumb.save(UPLOAD_DIR / thumb_name, "WEBP", quality=79, method=4)
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise ValueError("One of your files isn't a supported or valid image.") from exc
        return saved
    except Exception:
        cleanup_files(saved)
        raise


def cleanup_files(photos):
    for photo in photos:
        for name in (photo["filename"], photo["thumb_filename"]):
            try:
                (UPLOAD_DIR / name).unlink(missing_ok=True)
            except OSError:
                pass


def add_photo_rows(db, entry_id, saved):
    position = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1)+1 FROM photos WHERE entry_id=?", (entry_id,)
    ).fetchone()[0]
    for offset, photo in enumerate(saved):
        db.execute("INSERT INTO photos (entry_id,filename,thumb_filename,original_name,sort_order) "
                   "VALUES (?,?,?,?,?)", (entry_id, photo["filename"], photo["thumb_filename"],
                                       photo["original_name"], position + offset))


@app.route("/entries/new", methods=["GET", "POST"])
@login_required
def new_entry():
    if request.method == "POST":
        saved = []
        try:
            payload = validate_entry(request.form)
            saved = process_uploads(request.files.getlist("photos"))
            db = get_db()
            try:
                with db:
                    cur = db.execute(
                        "INSERT INTO entries(title,entry_date,category,body,location,mood) "
                        "VALUES (:title,:entry_date,:category,:body,:location,:mood)", payload)
                    add_photo_rows(db, cur.lastrowid, saved)
                flash("Your memory has been saved.", "success")
                return redirect(url_for("entry_detail", entry_id=cur.lastrowid))
            except Exception:
                cleanup_files(saved)
                raise
        except ValueError as exc:
            flash(str(exc), "error")
        return render_template("entry_form.html", entry=request.form, is_edit=False, existing_photos=[])
    category = request.args.get("category", "diary")
    if category not in CATEGORIES:
        category = "diary"
    return render_template("entry_form.html", entry={"entry_date":local_today(), "category":category},
                           is_edit=False, existing_photos=[])


@app.get("/entries/<int:entry_id>")
@login_required
def entry_detail(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    if row is None:
        abort(404)
    entry = hydrate_entries([row])[0]
    return render_template("entry_detail.html", entry=entry)


@app.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def edit_entry(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    if row is None:
        abort(404)
    existing_photos = db.execute(
        "SELECT * FROM photos WHERE entry_id=? ORDER BY sort_order,id", (entry_id,)
    ).fetchall()
    if request.method == "POST":
        saved = []
        try:
            payload = validate_entry(request.form)
            to_add = [f for f in request.files.getlist("photos") if f and f.filename]
            if len(existing_photos) + len(to_add) > MAX_PHOTOS_PER_ENTRY:
                raise ValueError(f"Each entry can have up to {MAX_PHOTOS_PER_ENTRY} photos.")
            saved = process_uploads(to_add)
            try:
                with db:
                    db.execute("UPDATE entries SET title=:title,entry_date=:entry_date,category=:category,"
                               "body=:body,location=:location,mood=:mood,updated_at=CURRENT_TIMESTAMP "
                               "WHERE id=:id", {**payload, "id":entry_id})
                    add_photo_rows(db, entry_id, saved)
                flash("Your entry has been updated.", "success")
                return redirect(url_for("entry_detail", entry_id=entry_id))
            except Exception:
                cleanup_files(saved)
                raise
        except ValueError as exc:
            flash(str(exc), "error")
        return render_template("entry_form.html", entry=request.form, is_edit=True,
                               existing_photos=existing_photos, entry_id=entry_id)
    return render_template("entry_form.html", entry=row, is_edit=True,
                           existing_photos=existing_photos, entry_id=entry_id)


@app.post("/entries/<int:entry_id>/delete")
@login_required
def delete_entry(entry_id):
    db = get_db()
    row = db.execute("SELECT id FROM entries WHERE id=?", (entry_id,)).fetchone()
    if row is None:
        abort(404)
    photos = db.execute("SELECT * FROM photos WHERE entry_id=?", (entry_id,)).fetchall()
    with db:
        db.execute("DELETE FROM entries WHERE id=?", (entry_id,))
    cleanup_files(photos)
    flash("The entry was deleted.", "success")
    return redirect(url_for("entries"))


@app.post("/photos/<int:photo_id>/delete")
@login_required
def delete_photo(photo_id):
    db = get_db()
    photo = db.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
    if photo is None:
        abort(404)
    with db:
        db.execute("DELETE FROM photos WHERE id=?", (photo_id,))
    cleanup_files([photo])
    flash("Photo removed.", "success")
    return redirect(url_for("edit_entry", entry_id=photo["entry_id"]))


@app.get("/photos/<int:photo_id>")
@login_required
def serve_photo(photo_id):
    photo = get_db().execute(
        "SELECT filename,thumb_filename FROM photos WHERE id=?", (photo_id,)
    ).fetchone()
    if photo is None:
        abort(404)
    name = photo["thumb_filename"] if request.args.get("thumb") == "1" else photo["filename"]
    return send_from_directory(UPLOAD_DIR, name, mimetype="image/webp", max_age=0)


@app.errorhandler(RequestEntityTooLarge)
def too_large(_exc):
    return render_template("error.html", code=413,
                           message="The upload is too big. Add fewer photos at a time."), 413


@app.errorhandler(404)
def not_found(_exc):
    if not current_session_is_authenticated():
        return redirect(url_for("login"))
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


@app.errorhandler(400)
def bad_request(exc):
    if not current_session_is_authenticated():
        return redirect(url_for("login"))
    return render_template("error.html", code=400,
                           message=getattr(exc, "description", "Please try again.")), 400



@app.template_filter("pretty_date")
def pretty_date(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return f"{parsed.day} {parsed.strftime('%B %Y')}"
    except (ValueError, TypeError):
        return value

if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", "5000")))
