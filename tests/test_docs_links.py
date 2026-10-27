"""Relative links and anchors in README.md and docs/**/*.md resolve.

Each feature package creates its own docs page when it lands; until then a link to that page is
allowed to dangle (PENDING_PAGES). Everything else must resolve: the target file exists under the
repo, and a `#fragment` names a heading in it (GitHub's slug rules).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Pages owned by feature packages that may not have landed yet (docs ownership, plan D11).
PENDING_PAGES = {
    "docs/test-profile.md",
    "docs/idle-detection.md",
    "docs/resume.md",
    "docs/upgrade.md",
}
PENDING_DIRS = ("docs/systems/",)

FENCE = re.compile(r"^ {0,3}(```|~~~).*?^ {0,3}\1[^\n]*$", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)


def unfenced(text):
    """Markdown with fenced code blocks blanked out, line count preserved."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def prose(text):
    """Markdown with fenced blocks and inline code removed."""
    return INLINE_CODE.sub("", unfenced(text))


def slugs(text):
    """GitHub heading anchors: lower-case, punctuation dropped, spaces to hyphens, -N on repeats."""
    seen, out = {}, set()
    for heading in HEADING.findall(unfenced(text)):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        out.add(slug if n == 0 else f"{slug}-{n}")
    return out


def markdown_files(root):
    return [root / "README.md", *sorted((root / "docs").rglob("*.md"))]


def is_pending(rel):
    return rel in PENDING_PAGES or any(rel.startswith(d) for d in PENDING_DIRS)


def broken_links(root):
    """`file:line: target (reason)` for every relative link that does not resolve."""
    problems = []
    for md in markdown_files(root):
        text = md.read_text()
        for lineno, line in enumerate(prose(text).splitlines(), 1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, fragment = target.partition("#")
                dest = md if not path else (md.parent / path).resolve()
                rel = dest.relative_to(root).as_posix() if root in dest.parents else str(dest)
                where = f"{md.relative_to(root)}:{lineno}: {target}"
                if not dest.is_file():
                    if path and is_pending(rel):
                        continue
                    problems.append(f"{where} (no such file)")
                elif fragment and dest.suffix == ".md" and fragment not in slugs(dest.read_text()):
                    problems.append(f"{where} (no heading #{fragment} in {rel})")
    return problems


def test_docs_links_resolve():
    assert broken_links(ROOT) == []


def test_checker_detects_broken_links(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "# T\n\n```sh\n[fenced](#y)\n```\n\n## Two words\n\n[ok](#two-words) [ok](docs/a.md#part-b) "
        "[bad](docs/missing.md) [bad](docs/a.md#nope) [pending](docs/upgrade.md) "
        "[pending](docs/systems/codex.md) [ext](https://example.org) `[code](#x)`\n"
    )
    (tmp_path / "docs" / "a.md").write_text("# A\n\n## Part B\n\n[up](../README.md#two-words)\n")
    problems = broken_links(tmp_path)
    assert problems == [
        "README.md:9: docs/missing.md (no such file)",
        "README.md:9: docs/a.md#nope (no heading #nope in docs/a.md)",
    ]
