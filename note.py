#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="CLI unificata per post_note.py e post_simple.py."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--post-note",
        action="store_true",
        help="Esegue il flusso di post_note.py",
    )
    mode.add_argument(
        "--post-simple",
        action="store_true",
        help="Esegue il flusso di post_simple.py",
    )
    return parser.parse_known_args()


def main() -> int:
    args, extra = parse_args()
    repo_path = Path(__file__).resolve().parent

    if args.post_note:
        script = repo_path / "post_note.py"
    else:
        script = repo_path / "post_simple.py"

    result = subprocess.run([sys.executable, str(script), *extra], cwd=repo_path, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
