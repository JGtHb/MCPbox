"""Stdlib detector - determines if a module is part of Python's standard library."""

import sys
from functools import lru_cache


@lru_cache(maxsize=512)
def is_stdlib_module(module_name: str) -> bool:
    """Check if a module is part of Python's standard library.

    Uses sys.stdlib_module_names (Python 3.10+) for accurate detection.
    Handles dotted module names by checking the top-level package.

    Args:
        module_name: The module name to check (e.g., "json", "xml.etree.ElementTree")

    Returns:
        True if the module is part of stdlib, False otherwise
    """
    # Get the top-level module name for dotted paths
    top_level = module_name.split(".")[0]

    return top_level in sys.stdlib_module_names


def classify_modules(module_names: list[str]) -> dict[str, list[str]]:
    """Classify a list of modules into stdlib and third-party.

    Args:
        module_names: List of module names to classify

    Returns:
        Dict with "stdlib" and "third_party" keys containing lists of modules
    """
    result = {"stdlib": [], "third_party": []}

    for module_name in module_names:
        if is_stdlib_module(module_name):
            result["stdlib"].append(module_name)
        else:
            result["third_party"].append(module_name)

    return result
