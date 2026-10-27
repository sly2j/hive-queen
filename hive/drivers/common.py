"""Helpers shared by the drivers: screen matching and version probing."""

import re
import subprocess

VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def match_waiting(kinds, screen):
    """The first kind whose phrase occurs in the whitespace-normalised, lower-cased screen."""
    text = " ".join(screen.lower().split())
    for kind, phrases in kinds:
        if any(phrase in text for phrase in phrases):
            return kind
    return None


def version_tuple(version):
    """"2.1.311" -> (2, 1, 311)."""
    return tuple(int(part) for part in version.split("."))


def probe_version(binary):
    """`binary --version` parsed to "X.Y.Z"; None when missing, timed out or unparseable."""
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for text in (out.stdout, out.stderr):
        m = VERSION_RE.search(text or "")
        if m:
            return ".".join(m.groups())
    return None
