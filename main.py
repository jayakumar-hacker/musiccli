#!/usr/bin/env python3
"""
MusiCLI – Main Entry Point
===========================
Run this file to start the interactive CLI music player.

    python main.py           # normal mode
    python main.py --debug   # verbose logging to stderr
    python main.py --version # print version and exit
"""

import argparse
import sys
import os

# Ensure project root is on sys.path when run directly
sys.path.insert(0, os.path.dirname(__file__))

from logger import setup_logging, get_logger
from cli.controller import CLIController

__version__ = "2.0.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="musicli",
        description="MusiCLI – terminal music streaming via yt-dlp + ffplay",
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable verbose debug logging to stderr",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"MusiCLI {__version__}",
    )
    return parser.parse_args()


def check_dependencies() -> bool:
    """Warn if required external tools are missing."""
    import shutil
    ok = True
    for tool in ("ffplay", "yt-dlp"):
        if shutil.which(tool) is None:
            print(f"  ✗  '{tool}' not found in PATH – please install it.", file=sys.stderr)
            ok = False
    return ok


def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.debug)
    log = get_logger("main")

    log.info("MusiCLI v%s starting", __version__)

    if not check_dependencies():
        sys.exit(1)

    try:
        controller = CLIController()
        controller.run()
    except Exception as exc:
        log.critical("Fatal error: %s", exc, exc_info=True)
        print(f"\n  Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
