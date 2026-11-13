#!/usr/bin/env python3
"""Tests for add-on CI helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from addon_ci import (  # noqa: E402
    Addon,
    addon_for_path,
    closed_without_merge,
    merged_release_env,
    parse_top_field,
    repo_root,
    run_addon_tests,
)


class ParseTopFieldTests(unittest.TestCase):
    def test_quoted_version_with_comment(self) -> None:
        text = 'version: "2026.09.13.1" #calendar versioning\n'
        self.assertEqual(parse_top_field(text, "version"), "2026.09.13.1")

    def test_unquoted_name(self) -> None:
        text = "name: Training Coach\n"
        self.assertEqual(parse_top_field(text, "name"), "Training Coach")

    def test_single_quoted(self) -> None:
        text = "slug: 'training_coach'\n"
        self.assertEqual(parse_top_field(text, "slug"), "training_coach")


class AddonPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addons = [
            Addon(
                dirname="training_coach",
                name="Training Coach",
                slug="training_coach",
                version="2026.09.13.1",
                config_rel="training_coach/config.yaml",
            ),
            Addon(
                dirname="ruuvibridge",
                name="RuuviBridge",
                slug="ruuvibridge",
                version="25.10.28.4",
                config_rel="ruuvibridge/config.yaml",
            ),
        ]

    def test_nested_path(self) -> None:
        addon = addon_for_path("training_coach/app/main.py", self.addons)
        assert addon is not None
        self.assertEqual(addon.dirname, "training_coach")

    def test_root_file_is_not_an_addon(self) -> None:
        self.assertIsNone(addon_for_path("repository.yaml", self.addons))

    def test_does_not_match_prefix_of_other_name(self) -> None:
        self.assertIsNone(addon_for_path("training_coach_extra/foo", self.addons))


class MergedReleaseEnvTests(unittest.TestCase):
    def test_open_pull_request_waits(self) -> None:
        payload = {"state": "OPEN", "number": 14, "title": "fix", "mergedAt": None, "mergeCommit": None}
        self.assertIsNone(merged_release_env(payload))
        self.assertFalse(closed_without_merge(payload))

    def test_merged_pull_request_uses_merge_commit(self) -> None:
        payload = {
            "state": "MERGED",
            "number": 14,
            "title": "fix(notification): point the effort card at the session they did",
            "body": "notes",
            "url": "https://github.com/oggali/hassio-addons/pull/14",
            "mergedAt": "2026-11-05T19:54:23Z",
            "mergeCommit": {"oid": "a7a180ee47c14fe9be57350e41a6aa0dd855000f"},
        }
        env = merged_release_env(payload)
        assert env is not None
        self.assertEqual(env["HEAD_SHA"], payload["mergeCommit"]["oid"])
        self.assertEqual(env["PR_NUMBER"], "14")
        self.assertEqual(env["PR_TITLE"], payload["title"])
        self.assertFalse(closed_without_merge(payload))

    def test_closed_without_merge_is_skipped(self) -> None:
        payload = {"state": "CLOSED", "mergedAt": None, "mergeCommit": None}
        self.assertIsNone(merged_release_env(payload))
        self.assertTrue(closed_without_merge(payload))


class RequirementsInstallTests(unittest.TestCase):
    def test_relative_core_path_is_installed_from_the_app_directory(self) -> None:
        addon = Addon(
            dirname="training_coach",
            name="Training Coach",
            slug="training_coach",
            version="2026.11.13.1",
            config_rel="training_coach/config.yaml",
        )
        calls: list[tuple[list[str], Path | None]] = []

        def fake_run(cmd, check=False, cwd=None, **_kwargs):
            calls.append((list(cmd), None if cwd is None else Path(cwd)))
            return mock.Mock(returncode=0)

        with mock.patch("addon_ci.subprocess.run", side_effect=fake_run):
            run_addon_tests(addon)

        installs = [call for call in calls if "install" in call[0] and "-r" in call[0]]
        self.assertEqual(len(installs), 1)
        requirements = Path(installs[0][0][-1])
        self.assertEqual(installs[0][1], requirements.parent)
        self.assertTrue((requirements.parent / ".." / "core" / "pyproject.toml").resolve().is_file())
        discovers = [call for call in calls if "unittest" in call[0]]
        self.assertEqual(discovers[0][1], repo_root())


class DiscoverAddonsTests(unittest.TestCase):
    def test_discovers_repo_addons(self) -> None:
        from addon_ci import discover_addons, repo_root

        names = {addon.dirname: addon for addon in discover_addons()}
        self.assertIn("training_coach", names)
        self.assertTrue(names["training_coach"].version)
        self.assertTrue((repo_root() / names["training_coach"].config_rel).is_file())


if __name__ == "__main__":
    unittest.main()
