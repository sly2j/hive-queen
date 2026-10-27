"""Helpers every hive module may use: messages, exits, argparse types. Imports nothing from hive."""

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path


class ConfigError(Exception):
    """config.toml is unusable; the message names the file and the key."""


def die(message, code=2):
    print(f"hive: error: {message}", file=sys.stderr)
    sys.exit(code)


def warn(message):
    print(f"hive: warning: {message}", file=sys.stderr)


def quote(text):
    return json.dumps(text, ensure_ascii=False)


def get_version():
    try:
        return pkg_version("hive")
    except PackageNotFoundError:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()


def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: '{text}'")
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value
