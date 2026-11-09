from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
import requests

from importer.api import ApiError, WebsiteApi, load_profile
from importer.browser_login import AuthenticatedSession, browser_login
from importer.runner import destination_key

PROFILE = load_profile(Path(__file__).resolve().parents[1] / "profiles/example.json")


class BrowserSessionTests(unittest.TestCase):
    def test_localhost_browser_cookie_is_sent_by_http_client(self):
        session = AuthenticatedSession("http://localhost:3100", PROFILE, "admin@example.test", [
            {"name": "fixture_session", "value": "localhost-fixture", "domain": "localhost", "path": "/", "secure": False},
        ])
        api = WebsiteApi("http://localhost:3100", PROFILE)
        try:
            session.apply(api)
            request = api.session.prepare_request(requests.Request("GET", api.base_url + PROFILE["session_path"]))
            self.assertIn("localhost-fixture", request.headers.get("Cookie", ""))
        finally:
            api.close()

    def test_session_cannot_be_reused_for_another_site_or_contract(self):
        session = AuthenticatedSession("https://first.example", PROFILE, "admin@example.test", [])
        for target, profile in (("https://second.example", PROFILE), ("https://first.example", {**PROFILE, "create_path": "/example-api/v2/items"})):
            api = WebsiteApi(target, profile)
            try:
                with self.assertRaises(ApiError):
                    session.apply(api)
            finally:
                api.close()

    def test_adding_browser_login_page_preserves_existing_receipts(self):
        old_profile = {key: value for key, value in PROFILE.items() if key != "login_page"}
        before = WebsiteApi("https://site.example", old_profile)
        after = WebsiteApi("https://site.example", PROFILE)
        try:
            self.assertEqual(destination_key(before), destination_key(after))
        finally:
            before.close()
            after.close()

    def test_cookie_scope_flags_are_preserved(self):
        session = AuthenticatedSession("https://site.example", PROFILE, "admin@example.test", [
            {"name": "__Secure-fixture_session", "value": "fixture-token", "domain": "site.example", "path": "/", "secure": True, "expires": -1},
        ])
        api = WebsiteApi("https://site.example", PROFILE)
        try:
            session.apply(api)
            cookie = next(iter(api.session.cookies))
            self.assertEqual(cookie.domain, "site.example")
            self.assertTrue(cookie.secure)
        finally:
            api.close()


class BrowserFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", "fixture_session=fixture-admin; HttpOnly; Path=/")
            self.end_headers()
            self.wfile.write(b"<title>Importer local login test</title><p>Local test session established.</p>")
        elif self.path == "/example-api/session":
            authenticated = "fixture-admin" in self.headers.get("Cookie", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"user": {"role": "ADMIN", "email": "browser-admin@example.test"}} if authenticated else None).encode())
        else:
            self.send_response(404)
            self.end_headers()


@unittest.skipUnless(os.environ.get("RUN_BROWSER_LOGIN_TESTS") == "1", "Opt in to launching a local test browser")
class BrowserLoginTests(unittest.TestCase):
    def test_normal_browser_hands_httponly_session_to_http_client(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserFixture)
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with TemporaryDirectory() as directory:
                target = f"http://127.0.0.1:{server.server_port}"
                session = browser_login(target, PROFILE, Path(directory), Event(), lambda _text: None, timeout=30)
                self.assertEqual(session.email, "browser-admin@example.test")
                api = WebsiteApi(target, PROFILE)
                try:
                    session.apply(api)
                    self.assertEqual(api.check_admin(), "browser-admin@example.test")
                finally:
                    api.close()
        finally:
            server.shutdown()
            server.server_close()
