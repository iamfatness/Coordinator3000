"""Tests for the workspace path-containment guard."""
from __future__ import annotations

import os
import tempfile

import pytest

from app.tools.workspace import PathEscapeError, safe_join


def test_safe_join_within_workspace():
    with tempfile.TemporaryDirectory() as d:
        p = safe_join(d, "sub/dir/file.txt")
        assert p.startswith(os.path.realpath(d) + os.sep)


def test_safe_join_blocks_traversal():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(PathEscapeError):
            safe_join(d, "../../etc/passwd")


def test_safe_join_absolute_is_treated_relative():
    with tempfile.TemporaryDirectory() as d:
        p = safe_join(d, "/etc/passwd")
        # The leading slash is stripped; it resolves under the workspace.
        assert p.startswith(os.path.realpath(d))


def test_safe_join_root_itself():
    with tempfile.TemporaryDirectory() as d:
        assert safe_join(d, ".") == os.path.realpath(d)
