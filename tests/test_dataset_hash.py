"""Tests for the path-based dataset hashing in tools/maestro_cli/hashing.py.

A record locates its bytes by a `path:` field relative to `data/`; when absent the
path defaults to `raw/<name>[/<version>]`. These tests build a throwaway `data/` tree
under tmp_path and exercise resolve_base / hash_fileset / dataset_sha_rel / dataset_sha.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from maestro_cli.hashing import (  # noqa: E402
    dataset_sha,
    dataset_sha_rel,
    hash_fileset,
    resolve_base,
)


# --- resolve_base ----------------------------------------------------------

def test_resolve_base_path_wins(tmp_path):
    # When a path is given it wins outright — name/version are ignored.
    assert resolve_base(tmp_path, "ds", path="processed/foo/bar.csv") == tmp_path / "processed/foo/bar.csv"


def test_resolve_base_path_absent_defaults_to_raw_name(tmp_path):
    assert resolve_base(tmp_path, "ds") == tmp_path / "raw" / "ds"


def test_resolve_base_version_appends(tmp_path):
    assert resolve_base(tmp_path, "ds", version="v2") == tmp_path / "raw" / "ds" / "v2"


def test_resolve_base_path_wins_over_version(tmp_path):
    # path beats the raw/<name>/<version> default even when version is also given.
    got = resolve_base(tmp_path, "ds", version="v2", path="processed/x.csv")
    assert got == tmp_path / "processed/x.csv"


def test_resolve_base_clean_relative_path(tmp_path):
    # The dataset CLI strips leading/trailing slashes before calling; a clean relative path
    # joins straight under data_root.
    assert resolve_base(tmp_path, "ds", path="raw/ds/v1") == tmp_path / "raw" / "ds" / "v1"


# --- hash_fileset ----------------------------------------------------------

def test_hash_fileset_absent_is_empty(tmp_path):
    assert hash_fileset(tmp_path / "does_not_exist") == ""


def test_hash_fileset_single_file(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n")
    h = hash_fileset(f)
    assert h and isinstance(h, str)
    assert len(h) == 64  # sha256 hexdigest


def test_hash_fileset_dir_deterministic(tmp_path):
    d = tmp_path / "ds"
    (d / "sub").mkdir(parents=True)
    (d / "a.csv").write_text("alpha\n")
    (d / "sub" / "b.csv").write_text("beta\n")
    h1 = hash_fileset(d)
    h2 = hash_fileset(d)
    assert h1 == h2  # stable across recomputation
    assert len(h1) == 64


def test_hash_fileset_changes_on_drift(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    f = d / "a.csv"
    f.write_text("alpha\n")
    before = hash_fileset(d)
    f.write_text("ALPHA-edited\n")
    after = hash_fileset(d)
    assert before != after  # tracked bytes changed -> digest changes


def test_hash_fileset_stable_recompute_no_change(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "a.csv").write_text("alpha\n")
    assert hash_fileset(d) == hash_fileset(d)


# --- dataset_sha_rel -------------------------------------------------------

def test_dataset_sha_rel_by_path_hashes_right_bytes(tmp_path):
    target = tmp_path / "processed" / "foo"
    target.mkdir(parents=True)
    (target / "bar.csv").write_text("payload\n")
    via_rel = dataset_sha_rel(tmp_path, "anyname", path="processed/foo")
    via_fileset = hash_fileset(target)
    assert via_rel == via_fileset
    assert via_rel == dataset_sha_rel(tmp_path, "anyname", path="processed/foo")  # stable


def test_dataset_sha_rel_path_equals_legacy_when_raw_name(tmp_path):
    # A record whose explicit path is raw/<name> hashes identically to the legacy default.
    raw = tmp_path / "raw" / "ds"
    raw.mkdir(parents=True)
    (raw / "a.csv").write_text("data\n")
    by_path = dataset_sha_rel(tmp_path, "ds", path="raw/ds")
    by_default = dataset_sha_rel(tmp_path, "ds")
    assert by_path == by_default
    assert by_path != ""


# --- backward compatibility (dataset_sha_rel vs legacy dataset_sha) --------

def test_dataset_sha_rel_default_equals_legacy_dataset_sha(tmp_path):
    raw = tmp_path / "raw" / "ds"
    raw.mkdir(parents=True)
    (raw / "a.csv").write_text("data\n")
    (raw / "b.csv").write_text("more\n")
    assert dataset_sha_rel(tmp_path, "ds") == dataset_sha(tmp_path / "raw", "ds")


def test_dataset_sha_rel_default_with_version_equals_legacy(tmp_path):
    raw = tmp_path / "raw" / "ds" / "v2"
    raw.mkdir(parents=True)
    (raw / "a.csv").write_text("data\n")
    assert dataset_sha_rel(tmp_path, "ds", version="v2") == dataset_sha(tmp_path / "raw", "ds", version="v2")
