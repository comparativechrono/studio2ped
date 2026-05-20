"""Command-line interface for studio2ped."""

from __future__ import annotations

import argparse
import sys

from .converter import convert_file


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
        help="Base name for output files (default: input filename stem)",
    )
    parser.add_argument(
        "-d", "--output-dir",
        default=None,
        dest="output_dir",
        help="Directory for output files (default: same as input file)",
    )

    args = parser.parse_args(argv)

    try:
        result = convert_file(
            args.input,
            output_prefix=args.output_prefix,
            output_dir=args.output_dir,
        )
        print(result.summary)
        for filepath, _ in result.files:
            print(f"  Written: {filepath}")
        return 0
    except FileNotFoundError:
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
