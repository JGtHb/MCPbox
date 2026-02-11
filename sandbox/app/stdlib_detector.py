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

    # Python 3.10+ has sys.stdlib_module_names
    if hasattr(sys, "stdlib_module_names"):
        return top_level in sys.stdlib_module_names

    # Fallback for older Python versions (shouldn't happen with Python 3.12)
    # This is a conservative list of known stdlib modules
    KNOWN_STDLIB = {
        "abc",
        "aifc",
        "argparse",
        "array",
        "ast",
        "asyncio",
        "atexit",
        "base64",
        "bdb",
        "binascii",
        "binhex",
        "bisect",
        "builtins",
        "bz2",
        "calendar",
        "cgi",
        "cgitb",
        "chunk",
        "cmath",
        "cmd",
        "code",
        "codecs",
        "codeop",
        "collections",
        "colorsys",
        "compileall",
        "concurrent",
        "configparser",
        "contextlib",
        "contextvars",
        "copy",
        "copyreg",
        "cProfile",
        "crypt",
        "csv",
        "ctypes",
        "curses",
        "dataclasses",
        "datetime",
        "dbm",
        "decimal",
        "difflib",
        "dis",
        "distutils",
        "doctest",
        "email",
        "encodings",
        "enum",
        "errno",
        "faulthandler",
        "fcntl",
        "filecmp",
        "fileinput",
        "fnmatch",
        "fractions",
        "ftplib",
        "functools",
        "gc",
        "getopt",
        "getpass",
        "gettext",
        "glob",
        "graphlib",
        "grp",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "idlelib",
        "imaplib",
        "imghdr",
        "imp",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "mailbox",
        "mailcap",
        "marshal",
        "math",
        "mimetypes",
        "mmap",
        "modulefinder",
        "multiprocessing",
        "netrc",
        "nis",
        "nntplib",
        "numbers",
        "operator",
        "optparse",
        "os",
        "ossaudiodev",
        "pathlib",
        "pdb",
        "pickle",
        "pickletools",
        "pipes",
        "pkgutil",
        "platform",
        "plistlib",
        "poplib",
        "posix",
        "posixpath",
        "pprint",
        "profile",
        "pstats",
        "pty",
        "pwd",
        "py_compile",
        "pyclbr",
        "pydoc",
        "queue",
        "quopri",
        "random",
        "re",
        "readline",
        "reprlib",
        "resource",
        "rlcompleter",
        "runpy",
        "sched",
        "secrets",
        "select",
        "selectors",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "site",
        "smtpd",
        "smtplib",
        "sndhdr",
        "socket",
        "socketserver",
        "spwd",
        "sqlite3",
        "ssl",
        "stat",
        "statistics",
        "string",
        "stringprep",
        "struct",
        "subprocess",
        "sunau",
        "symtable",
        "sys",
        "sysconfig",
        "syslog",
        "tabnanny",
        "tarfile",
        "telnetlib",
        "tempfile",
        "termios",
        "test",
        "textwrap",
        "threading",
        "time",
        "timeit",
        "tkinter",
        "token",
        "tokenize",
        "tomllib",
        "trace",
        "traceback",
        "tracemalloc",
        "tty",
        "turtle",
        "turtledemo",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uu",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "weakref",
        "webbrowser",
        "winreg",
        "winsound",
        "wsgiref",
        "xdrlib",
        "xml",
        "xmlrpc",
        "zipapp",
        "zipfile",
        "zipimport",
        "zlib",
        "zoneinfo",
        # Built-in modules
        "_thread",
        "_abc",
        "_asyncio",
        "_bisect",
        "_blake2",
        "_bz2",
        "_codecs",
        "_collections",
        "_contextvars",
        "_csv",
        "_ctypes",
        "_datetime",
        "_decimal",
        "_functools",
        "_hashlib",
        "_heapq",
        "_io",
        "_json",
        "_locale",
        "_lzma",
        "_md5",
        "_multiprocessing",
        "_opcode",
        "_operator",
        "_pickle",
        "_posixsubprocess",
        "_queue",
        "_random",
        "_sha1",
        "_sha256",
        "_sha3",
        "_sha512",
        "_signal",
        "_socket",
        "_sqlite3",
        "_sre",
        "_ssl",
        "_stat",
        "_statistics",
        "_string",
        "_struct",
        "_symtable",
        "_thread",
        "_tracemalloc",
        "_warnings",
        "_weakref",
        "_zoneinfo",
    }
    return top_level in KNOWN_STDLIB


def get_all_stdlib_modules() -> set[str]:
    """Get the complete set of stdlib module names.

    Returns:
        Set of all stdlib module names
    """
    if hasattr(sys, "stdlib_module_names"):
        return set(sys.stdlib_module_names)

    # Fallback - return empty set, meaning all modules will be treated as third-party
    return set()


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
