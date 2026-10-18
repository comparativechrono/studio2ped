"""Command-line interface for studio2ped."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .converter import ID_CHOICES, convert_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="studio2ped",
        description="Convert Pedigree Studio session JSON to PED/MPED pedigree files.",
    )
    parser.add_argument(
        "input",
        help="Path to the input Pedigree Studio session .json file",
    )
    parser.add_argument(
        "-o", "--output-prefix",
        default=None,
        dest="output_prefix",
        help="Base name for output files (default: the input file's name without .studio.json)",
    )
    parser.add_argument(
        "-d", "--output-dir",
        default=None,
        dest="output_dir",
        help="Directory for output files (default: same as input file)",
    )
    parser.add_argument(
        "--ids",
        choices=ID_CHOICES,
        default="numbers",
        help="How people are identified: pedigree numbers such as II-3 (numbers, the default), the labels "
             "the drawing shows (drawing), Pedigree Studio's own ids (studio), or version 0.1.0's "
             "identifiers taken from the text under each symbol, which are often names (text)",
    )
    parser.add_argument("--version", action="version", version=f"studio2ped {__version__}")

    args = parser.parse_args(argv)

    try:
        result = convert_file(
            args.input,
            output_prefix=args.output_prefix,
            output_dir=args.output_dir,
            ids=args.ids,
        )
        print(result.summary)
        for filepath, _ in result.files:
            print(f"  Written: {filepath}")
        for note in result.notes:
            print(f"  Note: {note}")
        return 0
    except FileNotFoundError as e:
        print(f"Error: file not found: {e.filename or args.input}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
