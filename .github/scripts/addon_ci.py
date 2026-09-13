#!/usr/bin/env python3
"""Validate add-on version bumps, run tests, and tag merged releases."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TAG_PREFIX_SEP = "/"


@dataclass(frozen=True)
class Addon:
    dirname: str
    name: str
    slug: str
    version: str
    config_rel: str

    @property
    def tag(self) -> str:
        return f"{self.dirname}{TAG_PREFIX_SEP}{self.version}"


def repo_root() -> Path:
    explicit = os.environ.get("GITHUB_WORKSPACE")
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve()
    return here.parents[2]


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root(),
        text=True,
        capture_output=True,
        check=check,
    )


def parse_top_field(text: str, key: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+)$")
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def discover_addons(root: Path | None = None) -> list[Addon]:
    root = root or repo_root()
    addons: list[Addon] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        config = None
        for name in ("config.yaml", "config.yml"):
            candidate = child / name
            if candidate.is_file():
                config = candidate
                break
        if config is None:
            continue
        text = config.read_text(encoding="utf-8")
        version = parse_top_field(text, "version")
        if not version:
            raise SystemExit(f"Missing version in {config.relative_to(root)}")
        addons.append(
            Addon(
                dirname=child.name,
                name=parse_top_field(text, "name") or child.name,
                slug=parse_top_field(text, "slug") or child.name,
                version=version,
                config_rel=str(config.relative_to(root)).replace("\\", "/"),
            )
        )
    return addons


def ensure_commit(sha: str) -> None:
    probe = run_git(["cat-file", "-e", f"{sha}^{{commit}}"], check=False)
    if probe.returncode == 0:
        return
    fetched = run_git(["fetch", "--no-tags", "origin", sha], check=False)
    if fetched.returncode != 0:
        raise SystemExit(
            f"Could not fetch commit {sha}: {fetched.stderr.strip() or fetched.stdout.strip()}"
        )


def files_from_pr() -> list[str] | None:
    number = os.environ.get("PR_NUMBER", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", "")).strip()
    if not number or not repo or not token:
        return None
    result = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{number}/files",
            "--jq",
            ".[].filename",
        ],
        cwd=repo_root(),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "GH_TOKEN": token},
    )
    if result.returncode != 0:
        print(
            f"PR file list unavailable, falling back to git diff: {result.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_files(base_sha: str, head_sha: str) -> list[str]:
    pr_files = files_from_pr()
    if pr_files is not None:
        return pr_files
    ensure_commit(base_sha)
    ensure_commit(head_sha)
    result = run_git(["diff", "--name-only", f"{base_sha}...{head_sha}"])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def addon_for_path(path: str, addons: list[Addon]) -> Addon | None:
    for addon in addons:
        prefix = f"{addon.dirname}/"
        if path == addon.dirname or path.startswith(prefix):
            return addon
    return None


def changed_addons(base_sha: str, head_sha: str) -> list[Addon]:
    addons = discover_addons()
    found: dict[str, Addon] = {}
    for path in changed_files(base_sha, head_sha):
        addon = addon_for_path(path, addons)
        if addon is not None:
            found[addon.dirname] = addon
    return [found[name] for name in sorted(found)]


def require_range() -> tuple[str, str]:
    base = os.environ.get("BASE_SHA", "").strip()
    head = os.environ.get("HEAD_SHA", "").strip()
    if not base or not head:
        raise SystemExit("BASE_SHA and HEAD_SHA must be set")
    return base, head


def version_at_ref(relpath: str, sha: str) -> str | None:
    result = run_git(["show", f"{sha}:{relpath}"], check=False)
    if result.returncode != 0:
        return None
    return parse_top_field(result.stdout, "version")


def remote_tag_commits() -> dict[str, str]:
    result = run_git(["ls-remote", "--tags", "origin"], check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"Could not list remote tags: {result.stderr.strip() or result.stdout.strip()}"
        )
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        sha, ref = line.split("\t", 1)
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            tags[name] = sha
    tags.update(peeled)
    return tags


def current_commit() -> str:
    return run_git(["rev-parse", "HEAD"]).stdout.strip()


def version_bump_errors(changed: list[Addon], base_sha: str) -> list[str]:
    ensure_commit(base_sha)
    errors: list[str] = []
    for addon in changed:
        previous = version_at_ref(addon.config_rel, base_sha)
        if previous == addon.version:
            errors.append(
                f"{addon.dirname} changed but version is still {addon.version} "
                f"(same as main). Bump version in {addon.config_rel} "
                "(calendar: YYYY.MM.DD.N)."
            )
    return errors


def new_tag_errors(changed: list[Addon]) -> list[str]:
    tags = remote_tag_commits()
    errors: list[str] = []
    for addon in changed:
        if addon.tag in tags:
            errors.append(
                f"Tag {addon.tag} already exists. Bump version in {addon.config_rel}."
            )
    return errors


def print_errors(title: str, errors: list[str]) -> None:
    print(title, file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)


def cmd_check() -> int:
    base, head = require_range()
    changed = changed_addons(base, head)
    if not changed:
        print("No add-on directories changed.")
        return 0
    print("Changed add-ons:")
    for addon in changed:
        print(f"  - {addon.dirname} {addon.version} (tag {addon.tag})")
    errors = version_bump_errors(changed, base) + new_tag_errors(changed)
    if errors:
        print_errors("Version check failed:", errors)
        return 1
    print("Version check passed.")
    return 0


def has_tests(addon: Addon) -> bool:
    return (repo_root() / addon.dirname / "tests").is_dir()


def run_addon_tests(addon: Addon) -> None:
    root = repo_root()
    tests = root / addon.dirname / "tests"
    requirements = root / addon.dirname / "app" / "requirements.txt"
    venv = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / f"addon-venv-{addon.dirname}"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = venv / "bin" / "pip"
    python = venv / "bin" / "python"
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)
    if requirements.is_file():
        subprocess.run([str(pip), "install", "-r", str(requirements)], check=True)
    print(f"Running tests for {addon.dirname}")
    subprocess.run(
        [str(python), "-m", "unittest", "discover", "-s", str(tests), "-v"],
        cwd=root,
        check=True,
    )


def cmd_test() -> int:
    base, head = require_range()
    changed = [addon for addon in changed_addons(base, head) if has_tests(addon)]
    if not changed:
        print("No changed add-ons with tests.")
        return 0
    for addon in changed:
        run_addon_tests(addon)
    return 0


def release_notes(addon: Addon) -> str:
    title = os.environ.get("PR_TITLE", "").strip() or addon.tag
    body = os.environ.get("PR_BODY", "").strip()
    url = os.environ.get("PR_URL", "").strip()
    number = os.environ.get("PR_NUMBER", "").strip()
    lines = [f"{addon.name} {addon.version}", ""]
    if number:
        lines.append(f"Merged #{number}: {title}")
    elif title:
        lines.append(title)
    if url:
        lines.append(url)
    if body:
        lines.extend(["", body])
    return "\n".join(lines).strip() + "\n"


def create_tag(addon: Addon) -> None:
    message = f"{addon.name} {addon.version}"
    tagged = run_git(
        [
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "tag",
            "-a",
            addon.tag,
            "-m",
            message,
        ],
        check=False,
    )
    if tagged.returncode != 0:
        raise SystemExit(
            f"Failed to create tag {addon.tag}: {tagged.stderr.strip() or tagged.stdout.strip()}"
        )
    pushed = run_git(["push", "origin", f"refs/tags/{addon.tag}"], check=False)
    if pushed.returncode != 0:
        raise SystemExit(
            f"Failed to push tag {addon.tag}: {pushed.stderr.strip() or pushed.stdout.strip()}"
        )
    print(f"Pushed tag {addon.tag}")


def create_release(addon: Addon) -> None:
    notes = release_notes(addon)
    result = subprocess.run(
        [
            "gh",
            "release",
            "create",
            addon.tag,
            "--title",
            f"{addon.name} {addon.version}",
            "--notes",
            notes,
        ],
        cwd=repo_root(),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(f"Created GitHub Release {addon.tag}")
        return
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "already exists" in combined:
        print(f"GitHub Release {addon.tag} already exists")
        return
    raise SystemExit(
        f"Failed to create release {addon.tag}: {result.stderr.strip() or result.stdout.strip()}"
    )


def cmd_tag() -> int:
    base, head = require_range()
    changed = changed_addons(base, head)
    if not changed:
        print("No add-on directories changed; nothing to tag.")
        return 0
    errors = version_bump_errors(changed, base)
    if errors:
        print_errors("Refusing to tag:", errors)
        return 1
    head_sha = current_commit()
    tags = remote_tag_commits()
    for addon in changed:
        existing = tags.get(addon.tag)
        if existing == head_sha:
            print(f"Tag {addon.tag} already points at this commit")
        elif existing:
            raise SystemExit(
                f"Tag {addon.tag} already exists at {existing}, not {head_sha}"
            )
        else:
            create_tag(addon)
        create_release(addon)
    return 0


def cmd_list() -> int:
    for addon in discover_addons():
        print(f"{addon.dirname}\t{addon.version}\t{addon.tag}\t{addon.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "test", "tag", "list"))
    args = parser.parse_args()
    commands = {
        "check": cmd_check,
        "test": cmd_test,
        "tag": cmd_tag,
        "list": cmd_list,
    }
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
