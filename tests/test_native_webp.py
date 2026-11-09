from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from importer.conversion import fit_webp
from importer.native_webp import NativeEncodingError, native_fit, run_encoder
from importer.resources import choose_workers


class NativeEncoderTests(unittest.TestCase):
    def test_native_failure_falls_back_to_valid_pillow_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "image.webp"
            messages = []
            with patch("importer.conversion.native_available", return_value=True), patch("importer.conversion.native_fit", side_effect=NativeEncodingError("fixture")):
                quality, lossless = fit_webp(Image.new("RGB", (80, 40), "red"), output, 5242880, True, Event(), messages.append)
            self.assertTrue(lossless)
            self.assertIsNone(quality)
            self.assertTrue(any("Pillow" in message for message in messages))
            with Image.open(output) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (80, 40))

    def test_target_size_output_is_verified_and_retried_before_accepting(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "image.webp"
            calls = []
            def encode(arguments, _cancel):
                calls.append(arguments)
                target = Path(arguments[arguments.index("-o") + 1])
                target.write_bytes(b"0" * (6000 if len(calls) == 1 else 4000))
            with patch("importer.native_webp.run_encoder", side_effect=encode):
                result = native_fit(Image.new("RGB", (80, 40)), output, 5000, False, Event(), lambda _text: None)
            self.assertEqual(result, (None, False))
            self.assertEqual(output.stat().st_size, 4000)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("-mt" in arguments and "-size" in arguments for arguments in calls))
            self.assertFalse(list(Path(directory).glob("*.png")))

    def test_cancel_terminates_native_child_immediately(self):
        cancel = Event()
        cancel.set()
        process = Mock()
        process.poll.return_value = None
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        with patch("importer.native_webp.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(ValueError, "หยุด"):
                run_encoder([], cancel)
        process.terminate.assert_called_once()
        process.wait.assert_called()

    def test_native_worker_budget_accounts_for_two_threads_per_image(self):
        with patch("importer.resources.os.cpu_count", return_value=12), patch("importer.resources.native_available", return_value=True), patch("importer.resources.available_memory", return_value=None):
            self.assertEqual(choose_workers(250, 5328 * 4000), 5)


if __name__ == "__main__":
    unittest.main()
