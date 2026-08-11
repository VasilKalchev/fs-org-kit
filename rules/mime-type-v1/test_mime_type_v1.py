"""
test_mime_type_v1.py - tests for the mime-type-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_mime_type_v1.py -v
Or, from the project root, every bundled rule's tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "mime-type-v1-check.py"

# Just enough of each format for the sniffer - it only ever reads 64 bytes.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 8
PDF = b"%PDF-1.7\n" + b"trailer"
ZIP = b"PK\x03\x04" + b"\x00" * 8
GZIP = b"\x1f\x8b\x08\x00" + b"\x00" * 8
ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 8
EXE = b"MZ\x90\x00" + b"\x00" * 8
FLAC = b"fLaC\x00\x00\x00\x22" + b"\x00" * 8
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 "
WAV = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"fmt "
MP4 = b"\x00\x00\x00\x20" + b"ftyp" + b"isom" + b"\x00" * 8
MP3 = b"ID3\x03\x00" + b"\x00" * 8
SQLITE = b"SQLite format 3\x00" + b"\x00" * 8


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def status(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["status"]


class TestSignatureDetection:
    """Each recognized magic number maps to the type it should."""

    @pytest.mark.parametrize("content, mime", [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (PDF, "application/pdf"),
        (ZIP, "application/zip"),
        (GZIP, "application/gzip"),
        (ELF, "application/x-executable"),
        (EXE, "application/x-msdownload"),
        (FLAC, "audio/flac"),
        (MP3, "audio/mpeg"),
        (SQLITE, "application/vnd.sqlite3"),
    ])
    def test_signature_at_offset_zero(self, tmp_path, content, mime):
        (tmp_path / "sample.bin").write_bytes(content)
        assert status(run_check({"allowed": [mime]}, tmp_path)) == "ok"

    @pytest.mark.parametrize("content, mime", [
        (WEBP, "image/webp"),
        (WAV, "audio/wav"),
    ])
    def test_riff_subtype_read_past_the_container_header(self, tmp_path, content, mime):
        """WEBP and WAV share the RIFF magic - the subtype at byte 8 separates them."""
        (tmp_path / "sample.bin").write_bytes(content)
        assert status(run_check({"allowed": [mime]}, tmp_path)) == "ok"

    def test_mp4_signature_is_not_at_offset_zero(self, tmp_path):
        (tmp_path / "clip.bin").write_bytes(MP4)
        assert status(run_check({"allowed": ["video/mp4"]}, tmp_path)) == "ok"

    def test_wav_is_not_mistaken_for_webp(self, tmp_path):
        (tmp_path / "sound.bin").write_bytes(WAV)
        assert status(run_check({"allowed": ["image/webp"]}, tmp_path)) == "violation"

    def test_text_fallback_for_plain_utf8(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello, world\n")
        assert status(run_check({"allowed": ["text/plain"]}, tmp_path)) == "ok"

    def test_null_byte_defeats_the_text_fallback(self, tmp_path):
        """The text heuristic is "valid UTF-8, no NULs" - a NUL means binary.
        Asserted via unknown_is_violation, so this can only pass if the
        file sniffed as nothing at all rather than as text."""
        (tmp_path / "data.bin").write_bytes(b"hello\x00world")
        result = run_check({"allowed": ["text/plain"], "unknown_is_violation": True}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "unrecognized" in payload["message"]

    def test_invalid_utf8_defeats_the_text_fallback(self, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"\xc3\x28\xa0\xa1")
        result = run_check({"allowed": ["text/plain"], "unknown_is_violation": True}, tmp_path)
        assert status(result) == "violation"

    def test_empty_file_is_unrecognized_not_text(self, tmp_path):
        (tmp_path / "empty.txt").touch()
        result = run_check({"allowed": ["text/plain"], "unknown_is_violation": True}, tmp_path)
        assert status(result) == "violation"


class TestExtensionMismatch:
    """The point of the rule: the name says one thing, the bytes another."""

    def test_png_named_txt_is_caught(self, tmp_path):
        (tmp_path / "innocent.txt").write_bytes(PNG)
        result = run_check({"allowed": ["text/plain"]}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "innocent.txt" in payload["message"]
        assert "image/png" in payload["message"]

    def test_executable_named_jpg_is_caught(self, tmp_path):
        (tmp_path / "holiday.jpg").write_bytes(ELF)
        result = run_check({"disallowed": ["application/x-executable"]}, tmp_path)
        assert status(result) == "violation"

    def test_the_extension_itself_is_never_consulted(self, tmp_path):
        """A correctly-named PNG and a PNG called .txt sniff identically."""
        (tmp_path / "a.png").write_bytes(PNG)
        (tmp_path / "b.txt").write_bytes(PNG)
        assert status(run_check({"allowed": ["image/png"]}, tmp_path)) == "ok"


class TestAllowedList:

    def test_all_allowed_is_ok(self, tmp_path):
        (tmp_path / "a.png").write_bytes(PNG)
        (tmp_path / "b.jpg").write_bytes(JPEG)
        assert status(run_check({"allowed": ["image/png", "image/jpeg"]}, tmp_path)) == "ok"

    def test_type_outside_the_list_is_violation(self, tmp_path):
        (tmp_path / "a.png").write_bytes(PNG)
        (tmp_path / "doc.pdf").write_bytes(PDF)
        result = run_check({"allowed": ["image/png"]}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "doc.pdf" in payload["message"]


class TestDisallowedList:

    def test_listed_type_is_violation(self, tmp_path):
        (tmp_path / "setup.exe").write_bytes(EXE)
        assert status(run_check({"disallowed": ["application/x-msdownload"]}, tmp_path)) == "violation"

    def test_unlisted_type_passes(self, tmp_path):
        (tmp_path / "a.png").write_bytes(PNG)
        assert status(run_check({"disallowed": ["application/x-msdownload"]}, tmp_path)) == "ok"


class TestUnknownHandling:

    def test_unrecognized_is_skipped_by_default(self, tmp_path):
        (tmp_path / "mystery.dat").write_bytes(b"\xde\xad\x00\xbe\xef")
        assert status(run_check({"allowed": ["image/png"]}, tmp_path)) == "ok"

    def test_unrecognized_counts_against_an_allowed_list_when_asked(self, tmp_path):
        (tmp_path / "mystery.dat").write_bytes(b"\xde\xad\x00\xbe\xef")
        result = run_check({"allowed": ["image/png"], "unknown_is_violation": True}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "unrecognized" in payload["message"]

    def test_unrecognized_never_counts_against_a_disallowed_list(self, tmp_path):
        """"Not on the forbidden list" can't be decided for a type you
        couldn't identify - the flag only makes sense with `allowed`."""
        (tmp_path / "mystery.dat").write_bytes(b"\xde\xad\x00\xbe\xef")
        result = run_check({"disallowed": ["image/png"], "unknown_is_violation": True}, tmp_path)
        assert status(result) == "ok"


class TestTraversal:

    def test_recursive_by_default(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "doc.pdf").write_bytes(PDF)
        assert status(run_check({"allowed": ["image/png"]}, tmp_path)) == "violation"

    def test_recursive_false_stays_at_the_top(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "doc.pdf").write_bytes(PDF)
        assert status(run_check({"allowed": ["image/png"], "recursive": False}, tmp_path)) == "ok"

    def test_folders_are_not_sniffed(self, tmp_path):
        (tmp_path / "sub").mkdir()
        assert status(run_check({"allowed": ["image/png"], "unknown_is_violation": True}, tmp_path)) == "ok"

    def test_exclude_by_name(self, tmp_path):
        (tmp_path / "a.png").write_bytes(PNG)
        (tmp_path / "doc.pdf").write_bytes(PDF)
        result = run_check({"allowed": ["image/png"], "exclude": ["doc.pdf"]}, tmp_path)
        assert status(result) == "ok"

    def test_exclude_glob_matches_a_nested_path(self, tmp_path):
        nested = tmp_path / "vendor"
        nested.mkdir()
        (nested / "doc.pdf").write_bytes(PDF)
        result = run_check({"allowed": ["image/png"], "exclude": ["vendor/*"]}, tmp_path)
        assert status(result) == "ok"

    def test_excluded_file_is_not_sniffed_even_when_unknown_counts(self, tmp_path):
        (tmp_path / "mystery.dat").write_bytes(b"\xde\xad\x00\xbe\xef")
        result = run_check(
            {"allowed": ["image/png"], "unknown_is_violation": True, "exclude": ["mystery.dat"]},
            tmp_path,
        )
        assert status(result) == "ok"


class TestMessage:

    def test_truncates_past_ten_with_a_count(self, tmp_path):
        for i in range(14):
            (tmp_path / f"f{i:02d}.pdf").write_bytes(PDF)
        payload = json.loads(run_check({"allowed": ["image/png"]}, tmp_path).stdout)
        assert payload["message"].startswith("14 file(s)")
        assert "and 4 more" in payload["message"]


class TestArguments:

    def test_rejects_fix_flag(self, tmp_path):
        """This rule has no fixer - --fix must be refused, not silently ignored."""
        assert run_check({"allowed": ["image/png"]}, tmp_path, fix=True).returncode != 0

    def test_neither_list_set_is_broken(self, tmp_path):
        assert run_check({}, tmp_path).returncode != 0

    def test_both_lists_set_is_broken(self, tmp_path):
        assert run_check({"allowed": ["image/png"], "disallowed": ["application/pdf"]}, tmp_path).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        assert run_check({"allowed": ["image/png"], "exclude": "doc.pdf"}, tmp_path).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"allowed": ["image/png"]}, tmp_path / "nope").returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
