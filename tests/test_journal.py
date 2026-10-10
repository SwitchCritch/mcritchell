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
