"""
Tests for link-integrity-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

The .lnk fixtures are assembled byte by byte rather than checked in as
binaries: a shell link is parsed by offset, so a test that can't vary the
offsets can't show the bounds checks work.
"""

import json
import plistlib
import struct
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "link-integrity-v1-check.py"

LNK_CLSID = bytes([0x01, 0x14, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
                   0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])


def run_check(params: dict, path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params)]
    argv += ["--path", str(path)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def make_lnk(local_path: str, *, has_local: bool = True, clsid: bytes = LNK_CLSID) -> bytes:
    """A minimal but structurally valid shell link carrying one
    LocalBasePath. Only the fields this rule reads are populated; the rest
    of the 76-byte header stays zero, which is what a real parser has to
    tolerate anyway."""
    header = bytearray(0x4C)
    struct.pack_into("<I", header, 0, 0x4C)
    header[4:20] = clsid
    struct.pack_into("<I", header, 20, 0x02)  # HasLinkInfo, no target id list

    encoded = local_path.encode("latin-1") + b"\x00"
    header_size = 28
    local_offset = header_size
    suffix_offset = local_offset + len(encoded)
    body = bytearray(suffix_offset + 1)
    struct.pack_into("<III", body, 0, len(body), header_size, 0x01 if has_local else 0x00)
    struct.pack_into("<I", body, 12, 0)               # VolumeIDOffset
    struct.pack_into("<I", body, 16, local_offset)
    struct.pack_into("<I", body, 20, 0)               # CommonNetworkRelativeLinkOffset
    struct.pack_into("<I", body, 24, suffix_offset)
    body[local_offset:local_offset + len(encoded)] = encoded
    return bytes(header) + bytes(body)


def desktop_entry(**fields) -> str:
    body = "\n".join(f"{k}={v}" for k, v in fields.items())
    return f"[Desktop Entry]\n{body}\n"


class TestSymlinks:

    def test_dangling_symlink_is_reported(self, tmp_path):
        (tmp_path / "link").symlink_to(tmp_path / "gone.txt")
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "link" in result["message"]

    def test_intact_symlink_is_ok(self, tmp_path):
        (tmp_path / "real.txt").write_text("x")
        (tmp_path / "link").symlink_to(tmp_path / "real.txt")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_relative_symlink_resolves_against_its_own_directory(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "real.txt").write_text("x")
        (sub / "link").symlink_to("real.txt")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_symlink_to_a_directory_is_ok(self, tmp_path):
        (tmp_path / "target").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "target")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_chain_ending_in_a_dangling_link_is_reported(self, tmp_path):
        """The first hop resolves, so a naive existence check calls this
        fine while opening it still fails."""
        (tmp_path / "second").symlink_to(tmp_path / "gone.txt")
        (tmp_path / "first").symlink_to(tmp_path / "second")
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"

    def test_symlink_cycle_is_reported(self, tmp_path):
        (tmp_path / "a").symlink_to(tmp_path / "b")
        (tmp_path / "b").symlink_to(tmp_path / "a")
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "cycle" in result["message"]

    def test_symlink_kind_can_be_switched_off(self, tmp_path):
        (tmp_path / "link").symlink_to(tmp_path / "gone.txt")
        assert verdict(run_check({"kinds": ["desktop"]}, tmp_path))["status"] == "ok"

    def test_a_symlink_named_like_another_kind_is_still_a_symlink(self, tmp_path):
        """Classification is by filesystem type first, suffix second."""
        (tmp_path / "x.desktop").symlink_to(tmp_path / "gone")
        assert verdict(run_check({"kinds": ["desktop"]}, tmp_path))["status"] == "ok"
        assert verdict(run_check({"kinds": ["symlink"]}, tmp_path))["status"] == "violation"


class TestDesktopEntries:

    def test_type_link_to_a_missing_file_is_reported(self, tmp_path):
        (tmp_path / "x.desktop").write_text(
            desktop_entry(Type="Link", URL=f"file://{tmp_path}/gone.txt")
        )
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_type_link_to_an_existing_file_is_ok(self, tmp_path):
        (tmp_path / "real.txt").write_text("x")
        (tmp_path / "x.desktop").write_text(
            desktop_entry(Type="Link", URL=f"file://{tmp_path}/real.txt")
        )
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_percent_encoded_url_is_decoded(self, tmp_path):
        (tmp_path / "with space.txt").write_text("x")
        (tmp_path / "x.desktop").write_text(
            desktop_entry(Type="Link", URL=f"file://{tmp_path}/with%20space.txt")
        )
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_type_application_with_a_missing_program_is_reported(self, tmp_path):
        (tmp_path / "app.desktop").write_text(
            desktop_entry(Type="Application", Exec="/nonexistent/program %U")
        )
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_type_application_resolved_via_path_is_ok(self, tmp_path):
        (tmp_path / "app.desktop").write_text(desktop_entry(Type="Application", Exec="sh -c true"))
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_type_directory_has_nothing_to_break(self, tmp_path):
        (tmp_path / "d.desktop").write_text(desktop_entry(Type="Directory", Name="Folder"))
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_field_codes_do_not_break_parsing(self, tmp_path):
        """.desktop values routinely contain % and ;, which is why this
        isn't parsed with configparser."""
        (tmp_path / "app.desktop").write_text(
            desktop_entry(Type="Application", Exec="sh %F %U", Categories="A;B;C;", Comment="50% done")
        )
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_type_link_with_no_url_is_reported(self, tmp_path):
        (tmp_path / "x.desktop").write_text(desktop_entry(Type="Link", Name="Nowhere"))
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_http_url_is_counted_but_never_judged(self, tmp_path):
        """This rule stays offline by choice, not because it couldn't ask
        the sandbox for `network` - see the manifest for why."""
        (tmp_path / "x.desktop").write_text(
            desktop_entry(Type="Link", URL="https://example.com/page")
        )
        assert verdict(run_check({}, tmp_path))["status"] == "ok"


class TestWindowsShortcuts:

    def test_lnk_pointing_at_a_missing_local_file_is_reported(self, tmp_path):
        (tmp_path / "s.lnk").write_bytes(make_lnk(str(tmp_path / "gone.txt")))
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_lnk_pointing_at_an_existing_file_is_ok(self, tmp_path):
        (tmp_path / "real.txt").write_text("x")
        (tmp_path / "s.lnk").write_bytes(make_lnk(str(tmp_path / "real.txt")))
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_windows_path_is_skipped_by_default(self, tmp_path):
        """A C:\\ path means nothing here, and claiming it's broken would
        be a guess."""
        (tmp_path / "s.lnk").write_bytes(make_lnk(r"C:\Users\someone\file.txt"))
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_windows_path_is_reported_when_asked_for(self, tmp_path):
        (tmp_path / "s.lnk").write_bytes(make_lnk(r"C:\Users\someone\file.txt"))
        result = verdict(run_check({"foreign_links": "report"}, tmp_path))
        assert result["status"] == "violation"
        assert "another platform" in result["message"]

    def test_skipped_foreign_links_are_still_counted_in_the_message(self, tmp_path):
        (tmp_path / "broken").symlink_to(tmp_path / "gone")
        (tmp_path / "s.lnk").write_bytes(make_lnk(r"C:\Users\someone\file.txt"))
        result = verdict(run_check({}, tmp_path))
        assert "target another platform and were skipped" in result["message"]

    def test_a_file_that_is_not_a_shell_link_is_reported(self, tmp_path):
        (tmp_path / "s.lnk").write_bytes(b"this is not a shell link at all, but it is long enough" * 4)
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "not a shell link" in result["message"]

    def test_truncated_lnk_does_not_crash(self, tmp_path):
        (tmp_path / "s.lnk").write_bytes(b"\x4c\x00\x00\x00")
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "truncated" in result["message"]

    def test_lnk_with_a_wrong_class_id_is_rejected(self, tmp_path):
        (tmp_path / "s.lnk").write_bytes(make_lnk("/tmp/x", clsid=bytes(16)))
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_lnk_without_a_local_path_is_not_called_broken(self, tmp_path):
        """A shell link to a network share has a target this rule can't
        reach, which is not the same as a target that's gone."""
        (tmp_path / "s.lnk").write_bytes(make_lnk("/tmp/x", has_local=False))
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_url_file_pointing_at_a_missing_file_is_reported(self, tmp_path):
        (tmp_path / "s.url").write_text(f"[InternetShortcut]\nURL=file://{tmp_path}/gone.txt\n")
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_url_file_with_an_http_target_is_not_judged(self, tmp_path):
        (tmp_path / "s.url").write_text("[InternetShortcut]\nURL=https://example.com\n")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_url_file_with_no_url_line_is_reported(self, tmp_path):
        (tmp_path / "s.url").write_text("[InternetShortcut]\nIconIndex=0\n")
        assert verdict(run_check({}, tmp_path))["status"] == "violation"


class TestMacFormats:

    def test_webloc_pointing_at_a_missing_file_is_reported(self, tmp_path):
        (tmp_path / "b.webloc").write_bytes(
            plistlib.dumps({"URL": f"file://{tmp_path}/gone.txt"})
        )
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_webloc_with_a_web_url_is_not_judged(self, tmp_path):
        (tmp_path / "b.webloc").write_bytes(plistlib.dumps({"URL": "https://example.com"}))
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_binary_plist_is_read_too(self, tmp_path):
        (tmp_path / "b.webloc").write_bytes(
            plistlib.dumps({"URL": f"file://{tmp_path}/gone.txt"}, fmt=plistlib.FMT_BINARY)
        )
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_unreadable_webloc_is_reported(self, tmp_path):
        (tmp_path / "b.webloc").write_text("not a plist")
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_finder_alias_is_counted_not_guessed_at(self, tmp_path):
        """An alias stores an opaque bookmark blob; resolving it is a Cocoa
        call, not a path lookup."""
        (tmp_path / "broken").symlink_to(tmp_path / "gone")
        (tmp_path / "old.alias").write_bytes(b"\x00\x00\x00\x00book\x00\x00mark")
        result = verdict(run_check({}, tmp_path))
        assert "could not be verified" in result["message"]


class TestTraversal:

    def test_nested_links_found_when_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "link").symlink_to(sub / "gone")
        assert verdict(run_check({}, tmp_path))["status"] == "violation"

    def test_nested_links_ignored_when_not_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "link").symlink_to(sub / "gone")
        assert verdict(run_check({"recursive": False}, tmp_path))["status"] == "ok"

    def test_excluded_links_are_skipped(self, tmp_path):
        (tmp_path / "skip.desktop").write_text(desktop_entry(Type="Link", URL="file:///nonexistent"))
        assert verdict(run_check({"exclude": ["*.desktop"]}, tmp_path))["status"] == "ok"

    def test_a_symlinked_directory_is_not_descended_into(self, tmp_path):
        """It's checked as a link, not walked - otherwise a link to an
        ancestor would loop forever."""
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "inner").symlink_to(tmp_path / "gone")
        (tmp_path / "loop").symlink_to(tmp_path)
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "1 broken link(s)" in result["message"]


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({}, tmp_path, fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({}, tmp_path / "nope").returncode != 0

    def test_rejects_unknown_kind(self, tmp_path):
        result = run_check({"kinds": ["hardlink"]}, tmp_path)
        assert result.returncode != 0
        assert "hardlink" in result.stderr

    def test_rejects_empty_kinds(self, tmp_path):
        assert run_check({"kinds": []}, tmp_path).returncode != 0

    def test_rejects_unknown_foreign_mode(self, tmp_path):
        assert run_check({"foreign_links": "maybe"}, tmp_path).returncode != 0

    def test_rejects_non_list_exclude(self, tmp_path):
        assert run_check({"exclude": "*.lnk"}, tmp_path).returncode != 0
