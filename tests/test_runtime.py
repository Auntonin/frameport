from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from importer.runtime import initialize_data, read_preferences, save_preferences

class RuntimeTests(unittest.TestCase):
    def test_preferences_keep_choices_without_credentials(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            save_preferences(directory, {"url": "https://example.test", "header": False, "email": "private", "password": "secret", "cookie": "secret"})
            self.assertEqual(read_preferences(directory), {"url": "https://example.test", "header": False})

    def test_corrupt_preferences_are_rejected(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for value in ([], {"header": "false"}, {"images": 12}):
                (directory / "preferences.json").write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    read_preferences(directory)

    def test_migration_preserves_receipts_and_does_not_overwrite_existing_history(self):
        with TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            directory = Path(temporary)
            legacy = directory / "legacy"
            legacy.mkdir()
            with closing(sqlite3.connect(legacy / "history.sqlite3")) as connection:
                connection.execute("CREATE TABLE receipts (id TEXT)")
                connection.execute("INSERT INTO receipts VALUES ('already-uploaded')")
                connection.commit()
            destination = directory / "new"
            initialize_data(destination, [legacy])
            with closing(sqlite3.connect(destination / "history.sqlite3")) as connection:
                self.assertEqual(connection.execute("SELECT id FROM receipts").fetchone()[0], "already-uploaded")
                connection.execute("INSERT INTO receipts VALUES ('newer')")
                connection.commit()
            initialize_data(destination, [legacy])
            with closing(sqlite3.connect(destination / "history.sqlite3")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 2)

    def test_isolated_data_does_not_copy_user_history(self):
        with TemporaryDirectory() as temporary, patch.dict(os.environ, {"FRAMEPORT_DATA_DIR": "isolated"}):
            initialize_data(Path(temporary) / "new", [Path(temporary)])
            self.assertFalse((Path(temporary) / "new/history.sqlite3").exists())

    def test_release_selfcheck_cannot_touch_normal_user_data(self):
        import app
        import sys
        with TemporaryDirectory() as temporary:
            real_data = Path(temporary) / "real-data"
            def inspect(_application, _report):
                self.assertNotEqual(app.DATA, real_data)
                self.assertTrue(app.DATA.parent.is_dir())
                app.DATA.mkdir()
                (app.DATA / "preferences.json").write_text("{}")
            with patch.object(app, "DATA", real_data), patch.object(sys, "argv", ["app", "--self-check", str(Path(temporary) / "report.json")]), patch("importer.selfcheck.run_selfcheck", side_effect=inspect) as check:
                app.main()
                check.assert_called_once()
            self.assertFalse(real_data.exists())
