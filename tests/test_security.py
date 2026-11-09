from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from importer.api import ApiError, WebsiteApi, load_profile

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("repository_policy", ROOT / "scripts/check-repository.py")
policy = module_from_spec(spec)
spec.loader.exec_module(policy)

class PublicationTests(unittest.TestCase):
    def test_private_profiles_datasets_history_and_binaries_are_rejected(self):
        for name in (".private/active-profile.json", "profiles/live.json", "data/history.sqlite3", "tests/real.csv", "release/program.exe", "importer/secret.env", "reference/server.py"):
            with self.subTest(name=name):
                self.assertTrue(policy.audit({name: b"private"}))

    def test_source_and_synthetic_profile_are_allowed(self):
        self.assertEqual(policy.audit({"app.py": b"print('hello')", "profiles/example.json": b"{}"}), [])

    def test_detected_credentials_do_not_appear_in_diagnostics(self):
        candidate = b"gh" + b"p_" + b"x" * 36
        result = policy.audit({"importer/example.py": candidate})
        self.assertTrue(result)
        self.assertNotIn(candidate.decode(), str(result))

class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api = WebsiteApi("https://service.example", load_profile(ROOT / "profiles/example.json"))
        self.addCleanup(self.api.close)

    def test_malformed_or_non_admin_user_is_rejected(self):
        for user in (None, [], "ADMIN", {"role": "USER"}):
            with self.subTest(user=user), patch.object(self.api, "_request", return_value=Mock(status_code=200, json=lambda: {"user": user})):
                with self.assertRaises(ApiError):
                    self.api.check_admin()

    def test_authenticated_http_does_not_follow_redirects(self):
        with patch.object(self.api.session, "request") as request:
            self.api._request("GET", "/example-api/session")
            self.assertFalse(request.call_args.kwargs["allow_redirects"])
            self.assertTrue(self.api.session.verify)
