"""End-to-end checks using Flask's test client. Run: python -m unittest discover -s tests -v"""
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

TEST_DATA_DIR = tempfile.mkdtemp(prefix="critchell-journal-test-")
os.environ["DATA_DIR"] = TEST_DATA_DIR
os.environ["DIARY_PASSWORD"] = "a-strong-demo-password-only-for-tests"
os.environ["SESSION_SECRET"] = "this-is-a-long-test-secret-not-for-production-use"
os.environ["COOKIE_SECURE"] = "false"

import app as journal  # noqa: E402: variables must be set before importing


def jpeg_file():
    output = io.BytesIO()
    Image.new("RGB", (180, 120), "#7b9c9a").save(output, format="JPEG")
    output.seek(0)
    return output


class JournalTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)

    def setUp(self):
        journal.app.config["TESTING"] = True
        self.client = journal.app.test_client()

    def token(self):
        with self.client.session_transaction() as sess:
            return sess["csrf_token"]

    def sign_in(self):
        self.client.get("/login")
        response = self.client.post("/login", data={
            "_csrf": self.token(), "password": os.environ["DIARY_PASSWORD"]
        })
        self.assertEqual(response.status_code, 302)

    def test_private_pages_and_photo_urls(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertIn("/login", self.client.get("/entries").location)
        self.assertIn("/login", self.client.get("/photos/123").location)
        self.assertIn("/login", self.client.get("/gallery").location)
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_login_and_csrf(self):
        self.client.get("/login")
        self.assertEqual(self.client.post("/login", data={
            "_csrf": self.token(), "password": "wrong"
        }).status_code, 200)
        self.sign_in()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/logout", data={}).status_code, 400)
        self.assertEqual(self.client.post("/logout", data={"_csrf": self.token()}).status_code, 302)
        self.assertIn("/login", self.client.get("/").location)

    def test_youtube_links_play_inline_and_can_be_changed(self):
        self.sign_in()
        new_form = self.client.get("/entries/new")
        self.assertIn(b'name="youtube_url"', new_form.data)
        self.assertNotIn(b"www.youtube-nocookie.com/embed/", new_form.data)
        created = self.client.post("/entries/new", data={
            "_csrf": self.token(), "title": "A gig with a video",
            "entry_date": "2026-10-12", "category": "concert", "body": "Great night!",
            "youtube_url": "https://youtu.be/dQw4w9WgXcQ?si=example"
        })
        self.assertEqual(created.status_code, 302)
        detail = created.location
        page = self.client.get(detail)
        self.assertIn(b"Watch the video", page.data)
        self.assertIn(b"https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", page.data)
        self.assertNotIn(b"<iframe", page.data)  # Loaded only after clicking Play
        self.assertIn(b"frame-src https://www.youtube-nocookie.com", page.headers["Content-Security-Policy"].encode())
        self.assertEqual(page.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn(b"Video", self.client.get("/entries").data)
        entry_id = int(detail.rstrip("/").split("/")[-1])
        edit_form = self.client.get(f"/entries/{entry_id}/edit")
        self.assertIn(b"https://www.youtube.com/watch?v=dQw4w9WgXcQ", edit_form.data)
        edited = self.client.post(f"/entries/{entry_id}/edit", data={
            "_csrf": self.token(), "title": "A gig with a video",
            "entry_date": "2026-10-12", "category": "concert",
            "youtube_url": "https://www.youtube.com/shorts/jfKfPfyJRdk"
        })
        self.assertEqual(edited.status_code, 302)
        self.assertIn(b"/embed/jfKfPfyJRdk", self.client.get(detail).data)
        bad = self.client.post(f"/entries/{entry_id}/edit", data={
            "_csrf": self.token(), "title": "A gig with a video",
            "entry_date": "2026-10-12", "category": "concert",
            "youtube_url": "https://www.youtube.com.evil.example/watch?v=jfKfPfyJRdk"
        })
        self.assertEqual(bad.status_code, 200)
        self.assertIn(b"valid YouTube video link", bad.data)
        self.assertIn(b"/embed/jfKfPfyJRdk", self.client.get(detail).data)
        cleared = self.client.post(f"/entries/{entry_id}/edit", data={
            "_csrf": self.token(), "title": "A gig with a video",
            "entry_date": "2026-10-12", "category": "concert", "youtube_url": ""
        })
        self.assertEqual(cleared.status_code, 302)
        self.assertNotIn(b"Watch the video", self.client.get(detail).data)
        self.assertEqual(self.client.get(detail).headers["Referrer-Policy"], "no-referrer")
        self.assertIn("/login", journal.app.test_client().get(detail).location)

    def test_write_edit_search_photos_and_delete(self):
        self.sign_in()
        response = self.client.post("/entries/new", data={
            "_csrf": self.token(), "title": "A memorable concert",
            "entry_date": "2026-10-10", "category": "concert", "location": "London",
            "body": "Wonderful songs and a great audience.",
            "photos": (jpeg_file(), "concert.jpg")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        detail_url = response.location
        self.assertIn("/entries/", detail_url)
        with journal.app.app_context():
            photo = journal.get_db().execute("SELECT id FROM photos ORDER BY id DESC LIMIT 1").fetchone()
            photo_id = photo["id"]
        self.assertEqual(self.client.get(f"/photos/{photo_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/photos/{photo_id}?thumb=1").mimetype, "image/webp")
        self.assertIn(b"A memorable concert", self.client.get(detail_url).data)
        self.assertIn(b"A memorable concert", self.client.get("/").data)
        self.assertIn(b"A memorable concert", self.client.get("/gallery").data)
        self.assertIn(b"A memorable concert", self.client.get("/entries?q=memorable").data)
        self.assertIn(b"A memorable concert", self.client.get("/entries?category=concert").data)
        entry_id = int(detail_url.rstrip("/").split("/")[-1])
        updated = self.client.post(f"/entries/{entry_id}/edit", data={
            "_csrf": self.token(), "title": "An amazing concert",
            "entry_date": "2026-10-10", "category": "concert", "location": "London",
            "body": "Even more wonderful than I remembered."
        })
        self.assertEqual(updated.status_code, 302)
        self.assertIn(b"An amazing concert", self.client.get(detail_url).data)
        self.assertEqual(self.client.post(f"/photos/{photo_id}/delete",
                                          data={"_csrf": self.token()}).status_code, 302)
        self.assertEqual(self.client.get(f"/photos/{photo_id}").status_code, 404)
        self.assertEqual(self.client.post(f"/entries/{entry_id}/delete",
                                          data={"_csrf": self.token()}).status_code, 302)
        self.assertEqual(self.client.get(detail_url).status_code, 404)


if __name__ == "__main__":
    unittest.main()
