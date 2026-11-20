"""The static replay site is a reproducible five-file export."""
import tempfile
import unittest
from pathlib import Path

from publish_report import ARCHIVE_LICENSE, ASSET_DIR, publish
from replay_compare import packet_bytes


class StaticReplaySite(unittest.TestCase):
    def test_new_directories_get_only_the_public_report_bytes(self):
        expected = {name: (ASSET_DIR / name).read_bytes()
                    for name in ("index.html", "style.css", "review.js")}
        expected["packet.json"] = packet_bytes()
        expected["archive-LICENSE.txt"] = ARCHIVE_LICENSE.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            for name in ("first", "second"):
                output = Path(folder) / name
                publish(output)
                self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, expected)

    def test_existing_directory_is_never_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with self.assertRaises(FileExistsError):
                publish(output)
            self.assertEqual(list(output.iterdir()), [])
            existing = output / "packet.json"
            existing.write_bytes(b"previous release")
            with self.assertRaises(FileExistsError):
                publish(output)
            self.assertEqual(list(output.iterdir()), [existing])
            self.assertEqual(existing.read_bytes(), b"previous release")
