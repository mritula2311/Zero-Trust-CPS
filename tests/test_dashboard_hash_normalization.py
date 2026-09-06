"""Regression coverage for the dashboard verification hash CRLF/LF gap: an LF
file and its byte-identical-but-CRLF twin must canonicalize to the same
verification hash, while a genuine content edit must still change it."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HASH_LIB = ROOT / "design" / "hash_lib.mjs"


def canonical_hash(path):
    result = subprocess.run(["node", str(HASH_LIB), str(path)],
                             capture_output=True, text=True, check=True)
    return result.stdout.strip()


class TestDashboardHashNormalization(unittest.TestCase):
    def setUp(self):
        if not HASH_LIB.exists():
            self.skipTest("design/hash_lib.mjs not present")

    def test_lf_and_crlf_versions_of_identical_content_hash_the_same(self):
        content = "line one\nline two\nline three\n"
        with tempfile.TemporaryDirectory() as tmp:
            lf_path = Path(tmp) / "lf.txt"
            crlf_path = Path(tmp) / "crlf.txt"
            lf_path.write_bytes(content.encode("utf-8"))
            crlf_path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
            self.assertNotEqual(lf_path.read_bytes(), crlf_path.read_bytes(),
                                 "fixture setup error: files must differ at the byte level")
            self.assertEqual(canonical_hash(lf_path), canonical_hash(crlf_path))

    def test_substantive_content_change_still_changes_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "original.txt"
            edited = Path(tmp) / "edited.txt"
            original.write_bytes(b"line one\r\nline two\r\n")
            edited.write_bytes(b"line one\r\nline TWO (changed)\r\n")
            self.assertNotEqual(canonical_hash(original), canonical_hash(edited))

    def test_mixed_line_endings_normalize_consistently(self):
        # A file with some CRLF and some bare LF lines (e.g. from a partial
        # manual edit) must canonicalize identically to an all-LF file with
        # the same logical lines.
        with tempfile.TemporaryDirectory() as tmp:
            mixed = Path(tmp) / "mixed.txt"
            all_lf = Path(tmp) / "all_lf.txt"
            mixed.write_bytes(b"alpha\r\nbeta\ngamma\r\n")
            all_lf.write_bytes(b"alpha\nbeta\ngamma\n")
            self.assertEqual(canonical_hash(mixed), canonical_hash(all_lf))


if __name__ == "__main__":
    unittest.main()
