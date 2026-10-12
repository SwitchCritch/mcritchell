# The Critchell Journal — Midnight & Gold Edition

A **private, password-protected diary** for everyday memories, concerts, family events and trips. Add as many entries as you like, upload photos, edit/delete entries and photos, and search your memories by text, year and category.

## What it includes

- First screen is the password login. There is **no public sign-up** and no publicly readable journal page.
- Dates, titles, categories (Concert / Everyday / Family / Travel / Milestone / Other), locations, moods and rich-length diary text.
- **NEW — YouTube videos:** paste an optional YouTube link into any diary or concert entry. A responsive video player appears on the entry page when you press Play. Supports normal watch URLs, youtu.be links, Shorts and live video URLs; edit or remove the link at any time.
- Up to **12 photos per upload** and **60 photos per entry**; JPG, PNG, WEBP and GIF (GIFs use the first frame), max 12 MB each. Photos are automatically resized for storage and shown in a lightbox.
- Dark navy and gold design inspired by an elegant editorial journal: cinematic featured story, recent photo-led entries, archive-by-year, concert diary and a **dedicated photo gallery**.
- Works on desktop, tablets and phones, with a redesigned private password screen and entry editor.
- Edit/delete entries, add more photos, remove individual photos.
- SQLite database and local photo storage; everything persists on a mounted Railway volume.
- Mobile-friendly design, password attempt throttling, CSRF protections and protected photo URLs.

## Updating an existing Railway journal (without losing entries)

**If your original Critchell Journal is already online, update the existing project rather than creating a new one.**

1. Keep the **same Railway service**, persistent volume and existing Variables (`DIARY_PASSWORD`, `SESSION_SECRET`, `DATA_DIR=/data`, `COOKIE_SECURE=true`). Do not change your password or secret just for this update.
2. Back up your existing `/data/journal.sqlite3` database and `/data/uploads/` photos first. Do not delete or detach the `/data` volume.
3. Unzip this new version and **replace the application files in your existing private GitHub repository** with the files inside the `critchell-journal/` folder. Commit/push the changes to the same branch your Railway service deploys from.
4. Wait for Railway to deploy the update and show **Success**, then refresh the same website URL. You may need Ctrl+F5 to refresh the stylesheet.
5. Your original diary entries and uploaded photos should reappear automatically because this version uses **the same database and the same storage locations**. The server automatically adds one optional `youtube_id` column to the existing database on first startup; all existing posts and photos remain unchanged.

**Do not upload or commit `/data`, `.env`, passwords, secrets or photo uploads to GitHub.** If Railway was not already using a persistent `/data` volume, correct that before relying on your stored entries. Redeploying to a different service or mounting a new empty volume won't automatically transfer old data.

### Add a YouTube video to a diary entry

1. Sign in to your diary and choose **New entry** or open an existing entry and choose **Edit entry**.
2. Scroll to **03 — Add a YouTube video** and paste your link, for example `https://youtu.be/dQw4w9WgXcQ`.
3. Save the entry. Open the entry and press **Play video** to start the built-in player.
4. You can edit or delete the video link later without losing the text or photos in that entry.

Videos are streamed from YouTube rather than uploaded to Railway, so they do not use your persistent photo storage. YouTube must allow embedding for the video to play (private, certain age-restricted or embed-disabled videos may not work). Playback only contacts YouTube **after you press Play**, and YouTube may receive your website's domain and set cookies or process playback data. Keep videos unlisted (rather than public) on YouTube if you do not want them readily searchable; this does **not** make them accessible only through your journal, since anyone with an unlisted link can watch them on YouTube.

### What changed in this edition

- Midnight navy backgrounds with warm gold text, decorative imagery and editorial-style typography.
- Your newest entry becomes the homepage's featured story, with its own photo where available.
- Four photo-led recent stories, plus a visual empty state when your diary is brand new.
- Year-based journal archive and quick links to entries, concerts and photographs.
- **Photos** in the main navigation leads to the new password-protected gallery at `/gallery`.
- All original functions for adding, editing and deleting stories and uploading/removing photos are kept.
- Optional YouTube link on any entry, with playback right on the entry detail page.

The website ships **without sample diary entries**. The preview screenshots are illustrative only; your own content will appear after you sign in.

## Deploy to Railway (recommended)

This is a ready-to-deploy **Python/Flask** project. Your diary needs a running server for a real password and safe photo storage. **Do not use GitHub Pages or a static-only host:** they can't run this secure login.

1. Unzip this folder and put its contents in a **private GitHub repository**. Keep `.env` and `data/` out of Git (already in `.gitignore`). You can also use Railway's preferred supported source deployment workflow.
2. In [Railway](https://railway.com), choose **New Project → Deploy from GitHub repo** and connect the private repository. Railway will install the packages and use the provided `railway.json` command.
3. In your Railway service choose **Variables → New Variable**, and enter:
   - `DIARY_PASSWORD` = your own strong, unique password (don't share it or put it in a file you upload).
   - `SESSION_SECRET` = a long, random secret of at least 32 characters. You can generate one on your own computer with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - `DATA_DIR` = `/data`
   - `COOKIE_SECURE` = `true`
   - `SITE_TITLE` = `The Critchell Journal` (or any name you like)
4. Go to Railway **Volumes** and add a **persistent volume** mounted to **`/data`** on **this same service**. Without a volume, entries and photos can disappear when Railway redeploys. The volume must be writable by the service.
5. In **Settings → Networking**, **Generate Domain**. Railway provides HTTPS on its hosted domain. Open the link and your password screen will appear.
6. Test by adding a diary entry with a photo, redeploying, and checking it is still there. Also test logging out and visiting a photo URL (it should demand your password).

**Important:** Set up the `/data` volume before adding real memories, and back up the volume regularly. A Railway volume protects against ordinary redeployments, not accidental deletion or permanent storage failure. Keep the password and `SESSION_SECRET` private. Changing `DIARY_PASSWORD` or `SESSION_SECRET` in Railway requires a new deployment; changing the session secret signs everyone out. Do not upload real photos before your persistent volume is attached.

### Backups

Both `journal.sqlite3` and `uploads/` inside `/data` are needed. Take a consistent SQLite backup (SQLite online backup API) rather than copying a live database file, and back up the uploads folder as well. Keep backups private. If you lose the password, edit the `DIARY_PASSWORD` Railway environment variable to replace it with a new one and redeploy.

### Privacy note

Your entries and photos are authenticated on the server, not merely hidden with JavaScript. Visitors who don't know your password are redirected to the login screen; even direct photo URLs require a login. Railway and its infrastructure still operate the hosting platform; this is private access control, not end-to-end encryption. For highly sensitive material, consider encryption and independent backups.

## Run on your own computer

Requires Python 3.12+.

```bash
python -m venv .venv
# On Windows: .venv\Scripts\activate
# On macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, fill in a **long, unique** `DIARY_PASSWORD`, and make a separate random `SESSION_SECRET`. Use `COOKIE_SECURE=false` **only while testing at `http://localhost`**. Then:

```bash
python app.py
```

Open `http://127.0.0.1:5000`. Your entries/photos go into the local `data/` directory and stay there between local restarts. Don't publish `.env` or `data/` publicly.

## Technical notes

- Requires exactly one owner password from the environment; no weak default password and no exposed password setup endpoint.
- Behind HTTPS, keep `COOKIE_SECURE=true`. All POST forms use session-bound anti-CSRF tokens. Journal pages and photos are sent with `Cache-Control: no-store`.
- The login screen is public, as it must be to accept a password; journal content isn't.
- Initial rate limiting (8 failed logins per IP per 15 minutes) is in memory and resets when the server restarts. For an internet-exposed personal journal, consider Railway network restrictions or extra protection if you need stronger abuse defense.
- Uploaded image files are re-encoded as WEBP and stripped of their source metadata to avoid serving untrusted raw file formats.

## Editing the design

Colours, layout and responsive styles are in `static/style.css`. Decorative background photos are bundled in `static/media/` so they do not depend on external image hosts. Website name can be changed with `SITE_TITLE` without editing code.

## Run automated checks

After installing the dependencies, from the project folder run:

```bash
python -m unittest discover -s tests -v
```

The tests use a temporary database and test-only login credentials, and check the protected pages, CSRF validation, entry creation/editing/search/deletion, video linking, and photo uploads.
