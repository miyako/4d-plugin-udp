"""Authorize only the exact advertised migration branch update."""

import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import repository


REF = "refs/heads/miyako-simplify-udp-workflows"
HOOK = Path(".github/migration-hooks/pre-push")


def main(updates):
    old, new = (os.environ[key] for key in ("MIGRATION_OLD_SHA", "MIGRATION_NEW_SHA"))
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (old, new)):
        raise ValueError("Invalid migration SHA")
    repository.verify_checkout(new)
    entry = repository.entries(repository.run(
        "git", "ls-tree", "-z", new, "--", str(HOOK))).get(str(HOOK))
    if HOOK.is_symlink() or not HOOK.is_file() or not os.access(HOOK, os.X_OK) \
            or entry is None or entry[0] != "100755" or repository.actual_blob(HOOK) != entry:
        raise ValueError("Migration hook must match its committed executable blob")
    if new == old or updates.splitlines() != [f"{new} {new} {REF} {old}"]:
        raise ValueError("Expected one literal new SHA and exact advertised old migration ref")
    message = repository.run("git", "log", "-1", "--format=%B", new)
    if not message.rstrip().endswith(
            "Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"):
        raise ValueError("Migration commit requires literal ending co-author trailer")


if __name__ == "__main__":
    try:
        main(sys.stdin.read())
    except (ValueError, KeyError, OSError) as error:
        print(f"Migration push stopped: {error}", file=sys.stderr)
        sys.exit(1)
