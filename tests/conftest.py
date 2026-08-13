"""
tests/conftest.py - fixtures/helpers shared across the core package's
unit tests (tests/test_*.py). Not used by rules/ tests, which build a
standard-free environment and invoke rule scripts via subprocess.
"""

import tomllib
from pathlib import Path

from fs_org_kit.validator import Validator, _index_source


def minimal_meta(*, standard_version: str = "2.0") -> str:
    """The smallest valid [meta] block. `standard_version` is
    overridable for the handful of tests that specifically exercise its
    independence from schema_version - everything else uses the
    default."""
    return f'''[meta]
schema_version = "2.0"
standard_version = "{standard_version}"
schema_date = "2026-01-01"
standard_date = "2026-01-01"
'''


def validate(standard_toml: str, tmp_path: Path, **validator_kwargs):
    """Write standard_toml to tmp_path, parse it, and run the validator.
    Returns (issues, validator). Shared by test_validator.py and
    test_path_keys.py so each test body is just the fixture TOML plus
    assertions."""
    std_path = tmp_path / "test.toml"
    std_path.write_text(standard_toml)
    data = tomllib.loads(standard_toml)
    header_occurrences, key_lines = _index_source(standard_toml)
    validator = Validator(data, tmp_path, header_occurrences, key_lines, **validator_kwargs)
    return validator.run(), validator
