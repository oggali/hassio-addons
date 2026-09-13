#!/usr/bin/env python3
"""Tests for add-on CI helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from addon_ci import Addon, addon_for_path, parse_top_field  # noqa: E402


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


class DiscoverAddonsTests(unittest.TestCase):
    def test_discovers_repo_addons(self) -> None:
        from addon_ci import discover_addons, repo_root

        names = {addon.dirname: addon for addon in discover_addons()}
        self.assertIn("training_coach", names)
        self.assertTrue(names["training_coach"].version)
        self.assertTrue((repo_root() / names["training_coach"].config_rel).is_file())


if __name__ == "__main__":
    unittest.main()
