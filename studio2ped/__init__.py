"""studio2ped — Convert Pedigree Studio session JSON to PED/MPED pedigree files."""

__version__ = "0.1.0"

from .converter import convert, convert_file, parse_session, ConversionResult

__all__ = ["convert", "convert_file", "parse_session", "ConversionResult"]
