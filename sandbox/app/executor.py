"""Python Executor - safely executes user-provided Python code."""

import asyncio
import json
import logging
import os
import resource
import time
import traceback
from dataclasses import dataclass
import datetime
from io import StringIO
from typing import Any, Optional

import httpx

from app.ssrf import SSRFProtectedAsyncHttpClient

logger = logging.getLogger(__name__)

# Maximum output size (configurable, default 1MB)
MAX_OUTPUT_SIZE = int(os.environ.get("SANDBOX_MAX_OUTPUT_SIZE", 1024 * 1024))

# Maximum memory per execution (configurable, default 256MB)
MAX_MEMORY_BYTES = int(os.environ.get("SANDBOX_MAX_MEMORY_BYTES", 256 * 1024 * 1024))

# Default execution timeout (30 seconds)
DEFAULT_TIMEOUT = 30.0

# Environment variable to require resource limits (default: true in production)
REQUIRE_RESOURCE_LIMITS = (
    os.environ.get("REQUIRE_RESOURCE_LIMITS", "true").lower() == "true"
)


@dataclass
class ResourceLimitStatus:
    """Track which resource limits were successfully applied."""

    memory_limit_set: bool = False
    cpu_limit_set: bool = False
    fd_limit_set: bool = False
    memory_limit_value: int | None = None
    cpu_limit_value: int | None = None
    fd_limit_value: int | None = None

    @property
    def all_limits_set(self) -> bool:
        """Check if all critical limits were set."""
        return self.memory_limit_set and self.cpu_limit_set and self.fd_limit_set

    @property
    def any_limits_set(self) -> bool:
        """Check if any limits were set."""
        return self.memory_limit_set or self.cpu_limit_set or self.fd_limit_set

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/debugging."""
        return {
            "memory": {
                "set": self.memory_limit_set,
                "value_mb": self.memory_limit_value // (1024 * 1024)
                if self.memory_limit_value
                else None,
            },
            "cpu": {
                "set": self.cpu_limit_set,
                "value_seconds": self.cpu_limit_value,
            },
            "file_descriptors": {
                "set": self.fd_limit_set,
                "value": self.fd_limit_value,
            },
        }


# Global status tracking
_resource_limit_status = ResourceLimitStatus()


def set_resource_limits() -> ResourceLimitStatus:
    """Set resource limits to prevent resource exhaustion attacks.

    These limits apply to the current process and are enforced by the OS.

    Returns:
        ResourceLimitStatus indicating which limits were successfully set.
    """
    global _resource_limit_status
    status = ResourceLimitStatus()

    # Check if we're in a containerized environment (Docker sets cgroup limits)
    in_container = (
        os.path.exists("/.dockerenv") or os.environ.get("CONTAINER", "") == "true"
    )

    try:
        # Limit virtual memory to prevent memory exhaustion
        # This catches attacks like: x = [0] * (10**9)
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        # Only set if not already limited by container
        if hard == resource.RLIM_INFINITY or hard > MAX_MEMORY_BYTES:
            resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, hard))
            status.memory_limit_set = True
            status.memory_limit_value = MAX_MEMORY_BYTES
            logger.info(f"Set memory limit to {MAX_MEMORY_BYTES // (1024 * 1024)}MB")
        else:
            # Container already has stricter limit - consider it set
            status.memory_limit_set = True
            status.memory_limit_value = hard
            logger.info(
                f"Container memory limit already set to {hard // (1024 * 1024)}MB"
            )
    except (ValueError, resource.error) as e:
        if in_container:
            # In container, cgroup limits may be enforced instead
            logger.info(f"Memory limit via cgroup (container): {e}")
            status.memory_limit_set = True  # Trust container limits
        else:
            logger.warning(f"Could not set memory limit: {e}")

    try:
        # CPU time limiting: RLIMIT_CPU is cumulative across the entire process
        # lifetime, not per-execution. Setting a low value (e.g., 60s) would
        # crash the long-running sandbox process after 60 cumulative CPU seconds
        # across ALL tool executions (DoS vulnerability).
        #
        # Per-execution CPU limits are enforced by:
        # 1. asyncio.wait_for() timeout (per-execution, default 30s)
        # 2. Container cgroup CPU limits (enforced by Docker)
        #
        # We set a generous process-level limit as a last-resort safety net.
        cpu_limit = 3600  # 1 hour cumulative CPU — safety net, not per-execution
        soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, hard))
        status.cpu_limit_set = True
        status.cpu_limit_value = cpu_limit
        logger.info(f"Set CPU time limit to {cpu_limit}s (process-level safety net)")
    except (ValueError, resource.error) as e:
        if in_container:
            logger.info(f"CPU limit via cgroup (container): {e}")
            status.cpu_limit_set = True  # Trust container limits
        else:
            logger.warning(f"Could not set CPU limit: {e}")

    try:
        # Limit file descriptors to prevent FD exhaustion attacks
        # This catches attacks like: [open('/dev/null') for _ in range(100000)]
        max_fds = 256  # Reasonable limit for tool execution
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (max_fds, hard))
        status.fd_limit_set = True
        status.fd_limit_value = max_fds
        logger.info(f"Set file descriptor limit to {max_fds}")
    except (ValueError, resource.error) as e:
        if in_container:
            logger.info(f"FD limit via container: {e}")
            status.fd_limit_set = True  # Trust container limits
        else:
            logger.warning(f"Could not set file descriptor limit: {e}")

    _resource_limit_status = status
    return status


def validate_resource_limits() -> tuple[bool, str | None]:
    """Validate that resource limits are properly configured.

    Returns:
        Tuple of (is_valid, error_message). If is_valid is True, error_message is None.
    """
    status = _resource_limit_status

    if not status.any_limits_set:
        return False, "No resource limits could be set - sandbox is not secure"

    if REQUIRE_RESOURCE_LIMITS and not status.all_limits_set:
        missing = []
        if not status.memory_limit_set:
            missing.append("memory")
        if not status.cpu_limit_set:
            missing.append("CPU")
        if not status.fd_limit_set:
            missing.append("file descriptors")
        return (
            False,
            f"Missing required resource limits: {', '.join(missing)}. Set REQUIRE_RESOURCE_LIMITS=false to disable this check.",
        )

    return True, None


# Set resource limits when module loads (runs once per process)
_init_status = set_resource_limits()

# Log validation result
is_valid, error_msg = validate_resource_limits()
if not is_valid:
    if REQUIRE_RESOURCE_LIMITS:
        logger.error(f"SECURITY: {error_msg}")
    else:
        logger.warning(f"SECURITY WARNING: {error_msg}")


# =============================================================================
# SAFE MODULE PROXY
# =============================================================================
#
# Modules injected into the sandbox (json, datetime, and any imported module)
# are wrapped in SafeModuleProxy to prevent attribute traversal attacks.
#
# Attack vector: Standard library modules carry references to `sys`, `os`, etc.
# via internal attributes (e.g., json.codecs.sys, datetime.sys).
# An attacker can traverse: datetime.sys.modules["os"].popen("id")
#
# Solution: Only expose a whitelist of safe public attributes per module.
# All other attribute access is blocked.
# =============================================================================

# Per-module allowlists of safe attributes.
# Only these attributes are accessible through the proxy.
# If a module is not listed here, all non-underscore public attrs are allowed.
_MODULE_SAFE_ATTRS: dict[str, set[str]] = {
    "json": {
        "dumps",
        "loads",
        "dump",
        "load",
        "JSONEncoder",
        "JSONDecoder",
        "JSONDecodeError",
    },
    "datetime": {
        "datetime",
        "date",
        "time",
        "timedelta",
        "timezone",
        "tzinfo",
        "MINYEAR",
        "MAXYEAR",
        "UTC",
    },
    "base64": {
        "b64encode",
        "b64decode",
        "urlsafe_b64encode",
        "urlsafe_b64decode",
        "b32encode",
        "b32decode",
        "b16encode",
        "b16decode",
        "encodebytes",
        "decodebytes",
        "standard_b64encode",
        "standard_b64decode",
    },
    "math": {
        "ceil",
        "floor",
        "sqrt",
        "pow",
        "log",
        "log2",
        "log10",
        "exp",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "pi",
        "e",
        "tau",
        "inf",
        "nan",
        "isnan",
        "isinf",
        "isfinite",
        "fabs",
        "factorial",
        "gcd",
        "lcm",
        "comb",
        "perm",
        "degrees",
        "radians",
        "hypot",
        "dist",
        "fsum",
        "prod",
        "trunc",
        "modf",
        "frexp",
        "ldexp",
        "copysign",
        "remainder",
        "isclose",
        "nextafter",
        "ulp",
    },
    "hashlib": {
        "md5",
        "sha1",
        "sha224",
        "sha256",
        "sha384",
        "sha512",
        "sha3_224",
        "sha3_256",
        "sha3_384",
        "sha3_512",
        "blake2b",
        "blake2s",
        "new",
        "algorithms_available",
        "algorithms_guaranteed",
        "pbkdf2_hmac",
        "scrypt",
    },
    "hmac": {
        "new",
        "compare_digest",
        "digest",
        "HMAC",
    },
    "collections": {
        "OrderedDict",
        "defaultdict",
        "deque",
        "Counter",
        "namedtuple",
        "ChainMap",
        "UserDict",
        "UserList",
        "UserString",
    },
    "itertools": {
        "count",
        "cycle",
        "repeat",
        "accumulate",
        "chain",
        "compress",
        "dropwhile",
        "filterfalse",
        "groupby",
        "islice",
        "pairwise",
        "starmap",
        "takewhile",
        "tee",
        "zip_longest",
        "product",
        "permutations",
        "combinations",
        "combinations_with_replacement",
        "batched",
    },
    "functools": {
        "reduce",
        "partial",
        "partialmethod",
        "lru_cache",
        "cache",
        "cached_property",
        "total_ordering",
        "cmp_to_key",
        "wraps",
        "update_wrapper",
        "singledispatch",
        "singledispatchmethod",
    },
    "statistics": {
        "mean",
        "median",
        "median_low",
        "median_high",
        "median_grouped",
        "mode",
        "multimode",
        "stdev",
        "pstdev",
        "variance",
        "pvariance",
        "harmonic_mean",
        "geometric_mean",
        "quantiles",
        "NormalDist",
        "correlation",
        "covariance",
        "linear_regression",
        "fmean",
    },
    "decimal": {
        "Decimal",
        "getcontext",
        "setcontext",
        "localcontext",
        "BasicContext",
        "ExtendedContext",
        "DefaultContext",
        "ROUND_UP",
        "ROUND_DOWN",
        "ROUND_CEILING",
        "ROUND_FLOOR",
        "ROUND_HALF_UP",
        "ROUND_HALF_DOWN",
        "ROUND_HALF_EVEN",
        "ROUND_05UP",
        "InvalidOperation",
        "DivisionByZero",
        "Inexact",
        "Rounded",
        "Subnormal",
        "Overflow",
        "Underflow",
        "FloatOperation",
    },
    "uuid": {
        "uuid1",
        "uuid3",
        "uuid4",
        "uuid5",
        "UUID",
        "NAMESPACE_DNS",
        "NAMESPACE_URL",
        "NAMESPACE_OID",
        "NAMESPACE_X500",
        "SafeUUID",
    },
    "html": {
        "escape",
        "unescape",
    },
    "urllib.parse": {
        "urlparse",
        "urlunparse",
        "urljoin",
        "urlencode",
        "quote",
        "quote_plus",
        "unquote",
        "unquote_plus",
        "parse_qs",
        "parse_qsl",
        "urlsplit",
        "urlunsplit",
        "ParseResult",
        "SplitResult",
    },
    "string": {
        "ascii_letters",
        "ascii_lowercase",
        "ascii_uppercase",
        "digits",
        "hexdigits",
        "octdigits",
        "punctuation",
        "printable",
        "whitespace",
        "capwords",
        "Formatter",
        "Template",
    },
    "textwrap": {
        "wrap",
        "fill",
        "shorten",
        "dedent",
        "indent",
        "TextWrapper",
    },
    "copy": {
        "copy",
        "deepcopy",
        "error",
    },
    "enum": {
        "Enum",
        "IntEnum",
        "StrEnum",
        "Flag",
        "IntFlag",
        "auto",
        "unique",
        "EnumType",
    },
    "dataclasses": {
        "dataclass",
        "field",
        "fields",
        "asdict",
        "astuple",
        "make_dataclass",
        "replace",
        "is_dataclass",
        "FrozenInstanceError",
        "InitVar",
        "Field",
        "KW_ONLY",
        "MISSING",
    },
    "typing": {
        "Any",
        "Union",
        "Optional",
        "List",
        "Dict",
        "Tuple",
        "Set",
        "FrozenSet",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Iterable",
        "Iterator",
        "Generator",
        "Callable",
        "ClassVar",
        "Final",
        "Literal",
        "TypeVar",
        "Generic",
        "Protocol",
        "runtime_checkable",
        "TypedDict",
        "NamedTuple",
        "get_type_hints",
        "cast",
        "overload",
        "no_type_check",
        "TYPE_CHECKING",
    },
    "binascii": {
        "hexlify",
        "unhexlify",
        "a2b_base64",
        "b2a_base64",
        "a2b_hex",
        "b2a_hex",
        "crc32",
        "crc_hqx",
        "Error",
        "Incomplete",
    },
    "difflib": {
        "SequenceMatcher",
        "Differ",
        "HtmlDiff",
        "context_diff",
        "unified_diff",
        "ndiff",
        "get_close_matches",
        "IS_CHARACTER_JUNK",
        "IS_LINE_JUNK",
        "restore",
    },
    "fractions": {
        "Fraction",
    },
    "cmath": {
        "phase",
        "polar",
        "rect",
        "exp",
        "log",
        "log10",
        "sqrt",
        "cos",
        "sin",
        "tan",
        "acos",
        "asin",
        "atan",
        "cosh",
        "sinh",
        "tanh",
        "acosh",
        "asinh",
        "atanh",
        "isfinite",
        "isinf",
        "isnan",
        "isclose",
        "pi",
        "e",
        "tau",
        "inf",
        "infj",
        "nan",
        "nanj",
    },
    "calendar": {
        "Calendar",
        "TextCalendar",
        "HTMLCalendar",
        "LocaleTextCalendar",
        "LocaleHTMLCalendar",
        "setfirstweekday",
        "firstweekday",
        "isleap",
        "leapdays",
        "weekday",
        "weekheader",
        "monthrange",
        "monthcalendar",
        "prmonth",
        "month",
        "prcal",
        "calendar",
        "timegm",
        "month_name",
        "month_abbr",
        "day_name",
        "day_abbr",
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    },
    "zoneinfo": {
        "ZoneInfo",
        "available_timezones",
        "TZPATH",
        "reset_tzpath",
        "ZoneInfoNotFoundError",
    },
}

# Attributes that are NEVER safe on any module (traversal vectors)
_MODULE_FORBIDDEN_ATTRS = frozenset(
    {
        "sys",
        "os",
        "subprocess",
        "builtins",
        "codecs",
        "posixpath",
        "genericpath",
        "posix",
        "nt",
        "ntpath",
        "_os",
        "_sys",
        "__spec__",
        "__loader__",
        "__builtins__",
        "__file__",
        "__path__",
        "__cached__",
    }
)


class SafeModuleProxy:
    """Proxy wrapper that restricts module attribute access to a whitelist.

    Prevents sandbox escape via module attribute traversal (e.g.,
    datetime.sys.modules["os"].popen("id")).

    Only explicitly whitelisted attributes are accessible. All others
    raise AttributeError.
    """

    __slots__ = ("_module", "_allowed_attrs", "_name")

    def __init__(self, module: Any, name: str | None = None):
        mod_name = name or getattr(module, "__name__", "unknown")
        object.__setattr__(self, "_name", mod_name)
        object.__setattr__(self, "_module", module)

        # Use explicit allowlist if defined, otherwise auto-generate from public attrs
        if mod_name in _MODULE_SAFE_ATTRS:
            object.__setattr__(self, "_allowed_attrs", _MODULE_SAFE_ATTRS[mod_name])
        else:
            # For modules without explicit allowlists, allow public non-underscore attrs
            # but always block known-dangerous traversal attrs
            safe_attrs = {
                attr
                for attr in dir(module)
                if not attr.startswith("_") and attr not in _MODULE_FORBIDDEN_ATTRS
            }
            object.__setattr__(self, "_allowed_attrs", safe_attrs)

    def __getattr__(self, name: str) -> Any:
        if name in _MODULE_FORBIDDEN_ATTRS:
            raise AttributeError(
                f"Access to '{name}' on module '{self._name}' is forbidden "
                f"(potential sandbox escape vector)"
            )
        if name not in self._allowed_attrs:
            raise AttributeError(
                f"module '{self._name}' has no attribute '{name}' "
                f"(not in sandbox allowlist)"
            )
        attr = getattr(self._module, name)

        # If the attribute is itself a module, wrap it too
        import types

        if isinstance(attr, types.ModuleType):
            return SafeModuleProxy(attr, name=f"{self._name}.{name}")

        return attr

    def __repr__(self) -> str:
        return f"<SafeModuleProxy '{self._name}'>"

    def __str__(self) -> str:
        return f"<SafeModuleProxy '{self._name}'>"

    # Prevent attribute setting/deletion
    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Cannot set attributes on sandbox module proxy")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Cannot delete attributes on sandbox module proxy")


class SizeLimitedStringIO(StringIO):
    """StringIO wrapper that limits total size to prevent memory exhaustion.

    When the limit is exceeded, writes are silently truncated and a warning
    is added at the end of the output.
    """

    def __init__(self, max_size: int = MAX_OUTPUT_SIZE):
        super().__init__()
        self.max_size = max_size
        self._truncated = False

    def write(self, s: str) -> int:
        if self._truncated:
            return 0  # Silently discard further writes

        current_size = self.tell()
        remaining = self.max_size - current_size

        if remaining <= 0:
            self._truncated = True
            super().write("\n... [OUTPUT TRUNCATED - exceeded 1MB limit] ...")
            return 0

        if len(s) > remaining:
            # Write only what fits
            super().write(s[:remaining])
            self._truncated = True
            super().write("\n... [OUTPUT TRUNCATED - exceeded 1MB limit] ...")
            return remaining

        return super().write(s)

    @property
    def was_truncated(self) -> bool:
        return self._truncated


# =============================================================================
# MODULE ALLOWLIST CONFIGURATION
# =============================================================================
#
# SECURITY CRITERIA (based on collective.trustedimports):
# - No file system access (read/write)
# - No network access (we provide protected httpx instead)
# - No system information disclosure
# - No unbounded execution time (regex has timeout wrapper)
# - No arbitrary attribute setting on objects
#
# DANGEROUS MODULES (never allow):
# - os, sys, subprocess, shutil, pathlib - system access
# - pickle, shelve, marshal, code, codeop - arbitrary code execution
# - socket, urllib.request, http.client - network (use provided http client)
# - inspect, gc, traceback, __builtins__ - sandbox escape via introspection
# - ctypes, cffi, mmap - memory access
# - multiprocessing, threading, signal - process/thread control
# - importlib, builtins - import system manipulation
#
# See: https://github.com/collective/collective.trustedimports
# See: https://python-security.readthedocs.io/security.html
# =============================================================================

DEFAULT_ALLOWED_MODULES = {
    # Data formats
    "json",
    "base64",
    "binascii",
    "html",
    # Date/Time
    "datetime",
    "calendar",
    "zoneinfo",
    # Math & Numbers
    "math",
    "cmath",
    "decimal",
    "fractions",
    "statistics",
    # Text processing
    "regex",  # Timeout-protected wrapper (not 're' - ReDoS vulnerable)
    "string",
    "textwrap",
    "difflib",
    # URL handling (parse only, NOT urllib.request)
    "urllib.parse",
    # Data structures
    "collections",
    "collections.abc",
    "itertools",
    "functools",
    # NOTE: 'operator' intentionally excluded - attrgetter() enables sandbox escape
    # Types & Utilities
    "typing",
    "dataclasses",
    "enum",
    "uuid",
    "copy",
    # Hashing (for checksums, signatures)
    "hashlib",
    "hmac",
}


# --- Shared safe builtins (single source of truth) ---
#
# Used by both PythonExecutor (tool execution) and the /execute endpoint.
# IMPORTANT: Any changes here affect ALL code execution paths.

# Allowed builtin names — everything NOT in this set is blocked.
ALLOWED_BUILTIN_NAMES = {
    # Types
    "bool",
    "int",
    "float",
    "str",
    "list",
    "dict",
    "tuple",
    "set",
    "frozenset",
    "bytes",
    "bytearray",
    # NOTE: type() removed - allows sandbox escape via type().__bases__[0].__subclasses__()
    # NOTE: object removed - allows sandbox escape via object.__subclasses__() which
    # provides access to dangerous classes like _io._IOBase, subprocess.Popen, etc.
    # NOTE: super() removed - implicitly accesses __class__ and MRO, enabling escape
    # Functions
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "callable",
    "chr",
    "divmod",
    "enumerate",
    "filter",
    "format",
    # NOTE: getattr/setattr/hasattr removed - they allow sandbox escape via __class__, __bases__
    # hasattr() internally calls getattr() which defeats the purpose of blocking getattr
    "hash",
    "hex",
    "id",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "map",
    "max",
    "min",
    "next",
    "oct",
    "ord",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    # NOTE: setattr removed - allows modifying protected attributes
    "slice",
    "sorted",
    "sum",
    "zip",
    # Exceptions
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "StopIteration",
    "StopAsyncIteration",
    "AttributeError",
    "ImportError",
    "IOError",
    "OSError",
    "FileNotFoundError",
    "PermissionError",
    "ConnectionError",
    "TimeoutError",
    "NotImplementedError",
    "ZeroDivisionError",
    "OverflowError",
    "UnicodeError",
    "UnicodeDecodeError",
    "UnicodeEncodeError",
    "ArithmeticError",
    "LookupError",
    # Constants
    "True",
    "False",
    "None",
}


def create_safe_builtins(
    allowed_modules: set[str] | None = None,
) -> dict[str, Any]:
    """Create a restricted builtins dict for safe code execution.

    This is the single source of truth for sandbox builtins, used by both
    PythonExecutor (tool execution via registry) and the /execute endpoint.

    Args:
        allowed_modules: Set of module names that can be imported.
                        If None, uses DEFAULT_ALLOWED_MODULES.

    Returns:
        A dict suitable for use as __builtins__ in exec().
    """
    import builtins

    if allowed_modules is None:
        allowed_modules = DEFAULT_ALLOWED_MODULES

    safe_builtins: dict[str, Any] = {}

    for name in ALLOWED_BUILTIN_NAMES:
        if hasattr(builtins, name):
            safe_builtins[name] = getattr(builtins, name)

    # Add safe __import__ that only allows whitelisted modules
    if isinstance(__builtins__, dict):
        real_import = __builtins__["__import__"]
    else:
        real_import = __builtins__.__import__

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        base_module = name.split(".")[0]

        if name not in allowed_modules and base_module not in allowed_modules:
            raise ImportError(
                f"Import of '{name}' is not allowed. "
                f"Use mcpbox_request_module to request it be whitelisted. "
                f"Allowed modules: {sorted(allowed_modules)}"
            )

        module = real_import(name, globals, locals, fromlist, level)

        # Wrap regex module with timeout protection
        if name == "regex":
            return TimeoutProtectedRegex(module)

        # Wrap all imported modules with SafeModuleProxy to prevent
        # attribute traversal attacks (e.g., json.codecs.sys.modules["os"])
        return SafeModuleProxy(module, name=name)

    safe_builtins["__import__"] = safe_import

    return safe_builtins


# NOTE: There is no FORBIDDEN_MODULES list. Admins have full control over
# which modules are allowed via the global module whitelist in Settings.
# If an admin chooses to allow potentially dangerous modules like 'os' or
# 'subprocess', that is their decision to make for their homelab deployment.

# Timeout for regex operations (configurable, default 5s) to prevent ReDoS attacks
REGEX_TIMEOUT = float(os.environ.get("SANDBOX_REGEX_TIMEOUT", 5.0))

# =============================================================================
# SANDBOX ESCAPE PREVENTION
# =============================================================================
#
# Even with dangerous builtins removed (type, object, getattr, setattr),
# attackers can still escape via dunder attributes on existing objects:
#
#   [].__class__.__mro__[-1].__subclasses__()  # Gets all object subclasses
#   "".__class__.__bases__[0].__subclasses__() # Same via string
#   func.__globals__                           # Access to global namespace
#   func.__code__                              # Access to code objects
#
# These attributes allow sandbox escape by accessing:
# - builtins.code, builtins.frame, builtins.function
# - _io._IOBase, subprocess.Popen, os._wrap_close
# - Any class that provides file/process/network access
#
# SOLUTION: Scan code for dangerous attribute access patterns before execution.
# =============================================================================

# Dunder attributes that enable sandbox escape
FORBIDDEN_DUNDER_ATTRS = {
    "__class__",  # Access object's class (leads to __mro__, __bases__)
    "__bases__",  # Access parent classes (leads to object)
    "__mro__",  # Method Resolution Order (leads to object)
    "__subclasses__",  # List all subclasses (exposes dangerous classes)
    "__globals__",  # Function's global namespace (access to modules)
    "__code__",  # Function's code object (can be manipulated)
    "__builtins__",  # Access to builtins dict/module
    "__import__",  # Direct import function access
    "__loader__",  # Module loader (can load arbitrary code)
    "__spec__",  # Module spec (contains loader)
    "__dict__",  # Object namespace (exposes internals, aids escape chains)
    "__traceback__",  # Exception traceback (leads to frame objects → f_globals) (SEC-026)
}

# Additional patterns that indicate escape attempts
FORBIDDEN_PATTERNS = [
    # Direct attribute access patterns
    r"\.__class__\b",
    r"\.__bases__\b",
    r"\.__mro__\b",
    r"\.__subclasses__\b",
    r"\.__globals__\b",
    r"\.__code__\b",
    r"\.__builtins__\b",
    r"\.__import__\b",
    r"\.__loader__\b",
    r"\.__spec__\b",
    r"\.__dict__\b",
    r"\.__traceback__\b",
    # Module traversal patterns (e.g., datetime.sys, json.codecs.sys)
    r"\.sys\b",
    r"\bsys\s*\[",
    r"\[[\'\"]os[\'\"]\]",
    r"\[[\'\"]sys[\'\"]\]",
    r"\[[\'\"]subprocess[\'\"]\]",
    r"\[[\'\"]builtins[\'\"]\]",
    r"\.modules\s*\[",
    # getattr-style access (in case someone passes strings)
    r"getattr\s*\([^)]*['\"]__\w+__['\"]",
    # vars() can expose __dict__ which contains dunders
    r"\bvars\s*\(",
    # dir() can be used to discover attributes
    r"\bdir\s*\(",
]


def _ast_validate(code: str, source_name: str) -> tuple[bool, str | None]:
    """AST-based defense-in-depth validation.

    Catches dunder attribute access that regex might miss (e.g. via Unicode
    normalization, string concatenation, or creative formatting).

    Returns (is_safe, error_message).
    """
    import ast

    try:
        tree = ast.parse(code, filename=source_name, mode="exec")
    except SyntaxError:
        # Syntax errors will be caught later during exec() — let them through
        return True, None

    # Forbidden attribute names accessed via dotted notation
    forbidden_attrs = {
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__code__",
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "__dict__",
        "__traceback__",
        "__init_subclass__",
        "__set_name__",
        "__del__",
        "__reduce__",
        "__reduce_ex__",
    }

    # Forbidden function calls
    forbidden_calls = {"getattr", "setattr", "hasattr", "delattr", "vars", "dir"}

    for node in ast.walk(tree):
        # Check attribute access: something.__class__, etc.
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            return False, (
                f"Security violation in {source_name}: "
                f"Access to '.{node.attr}' is forbidden (line {node.lineno})."
            )

        # Check forbidden function calls: getattr(...), vars(...), etc.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in forbidden_calls:
                return False, (
                    f"Security violation in {source_name}: "
                    f"Call to '{node.func.id}()' is forbidden (line {node.lineno})."
                )

    return True, None


def validate_code_safety(
    code: str, source_name: str = "<tool>"
) -> tuple[bool, str | None]:
    """Validate that code doesn't contain sandbox escape patterns.

    Uses two layers:
    1. Regex-based pattern matching (catches string patterns)
    2. AST-based validation (catches attribute access and forbidden calls)

    Args:
        code: Python source code to validate
        source_name: Name to use in error messages

    Returns:
        Tuple of (is_safe, error_message). If is_safe is True, error_message is None.
    """
    import regex

    # Layer 1: Regex-based pattern matching
    for pattern in FORBIDDEN_PATTERNS:
        try:
            match = regex.search(pattern, code, timeout=REGEX_TIMEOUT)
            if match:
                # Extract the specific forbidden attribute for the error message
                matched_text = match.group(0)
                return False, (
                    f"Security violation in {source_name}: "
                    f"Access to '{matched_text}' is forbidden. "
                    f"This pattern can be used to escape the sandbox."
                )
        except regex.TimeoutError:
            # If regex times out, reject the code as potentially malicious
            return False, (
                f"Security violation in {source_name}: "
                f"Code pattern analysis timed out (possible ReDoS attempt)"
            )

    # Layer 2: AST-based validation (defense-in-depth)
    return _ast_validate(code, source_name)


class TimeoutProtectedRegex:
    """Wrapper around regex module that enforces timeout on all operations.

    Prevents ReDoS (Regular Expression Denial of Service) attacks by ensuring
    all regex operations complete within REGEX_TIMEOUT seconds.

    SECURITY (F-04): Uses __slots__ and name-mangled attributes to prevent
    sandbox code from accessing the underlying module via regex._regex.
    Consistent with SSRFProtectedAsyncHttpClient's access control pattern.
    """

    __slots__ = ("__wrapped_regex", "__timeout")

    def __init__(self, regex_module):
        # Use object.__setattr__ to bypass our __setattr__ guard
        object.__setattr__(self, "_TimeoutProtectedRegex__wrapped_regex", regex_module)
        object.__setattr__(self, "_TimeoutProtectedRegex__timeout", REGEX_TIMEOUT)

    def __getattr__(self, name: str):
        raise AttributeError(
            f"Access to '{name}' is not allowed on the regex module. "
            f"Use regex.search(), regex.match(), regex.compile(), etc."
        )

    def __setattr__(self, name: str, value):
        raise AttributeError("Cannot set attributes on the regex module")

    def _add_timeout(self, kwargs: dict) -> dict:
        """Add timeout to kwargs if not already present."""
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.__timeout
        return kwargs

    def compile(self, pattern, flags=0, **kwargs):
        """Compile a regex pattern with timeout protection."""
        return self.__wrapped_regex.compile(pattern, flags, **self._add_timeout(kwargs))

    def search(self, pattern, string, flags=0, **kwargs):
        """Search for pattern in string with timeout protection."""
        return self.__wrapped_regex.search(
            pattern, string, flags, **self._add_timeout(kwargs)
        )

    def match(self, pattern, string, flags=0, **kwargs):
        """Match pattern at start of string with timeout protection."""
        return self.__wrapped_regex.match(
            pattern, string, flags, **self._add_timeout(kwargs)
        )

    def fullmatch(self, pattern, string, flags=0, **kwargs):
        """Match pattern against entire string with timeout protection."""
        return self.__wrapped_regex.fullmatch(
            pattern, string, flags, **self._add_timeout(kwargs)
        )

    def split(self, pattern, string, maxsplit=0, flags=0, **kwargs):
        """Split string by pattern with timeout protection."""
        return self.__wrapped_regex.split(
            pattern, string, maxsplit, flags, **self._add_timeout(kwargs)
        )

    def findall(self, pattern, string, flags=0, **kwargs):
        """Find all matches of pattern in string with timeout protection."""
        return self.__wrapped_regex.findall(
            pattern, string, flags, **self._add_timeout(kwargs)
        )

    def finditer(self, pattern, string, flags=0, **kwargs):
        """Find all matches as iterator with timeout protection."""
        return self.__wrapped_regex.finditer(
            pattern, string, flags, **self._add_timeout(kwargs)
        )

    def sub(self, pattern, repl, string, count=0, flags=0, **kwargs):
        """Replace pattern matches with timeout protection."""
        return self.__wrapped_regex.sub(
            pattern, repl, string, count, flags, **self._add_timeout(kwargs)
        )

    def subn(self, pattern, repl, string, count=0, flags=0, **kwargs):
        """Replace pattern matches and return count with timeout protection."""
        return self.__wrapped_regex.subn(
            pattern, repl, string, count, flags, **self._add_timeout(kwargs)
        )

    def escape(self, pattern):
        """Escape special characters in pattern (no timeout needed)."""
        return self.__wrapped_regex.escape(pattern)

    def purge(self):
        """Clear the regex cache (no timeout needed)."""
        return self.__wrapped_regex.purge()

    # Expose commonly used flags
    @property
    def IGNORECASE(self):
        return self.__wrapped_regex.IGNORECASE

    @property
    def I(self):  # noqa: E743 - Intentionally mirrors regex.I API
        return self.__wrapped_regex.I

    @property
    def MULTILINE(self):
        return self.__wrapped_regex.MULTILINE

    @property
    def M(self):
        return self.__wrapped_regex.M

    @property
    def DOTALL(self):
        return self.__wrapped_regex.DOTALL

    @property
    def S(self):
        return self.__wrapped_regex.S

    @property
    def VERBOSE(self):
        return self._regex.VERBOSE

    @property
    def X(self):
        return self._regex.X

    @property
    def ASCII(self):
        return self._regex.ASCII

    @property
    def A(self):
        return self._regex.A

    @property
    def UNICODE(self):
        return self._regex.UNICODE

    @property
    def U(self):
        return self._regex.U

    # Allow access to error class
    @property
    def error(self):
        return self._regex.error

    # Allow access to TimeoutError for users who want to catch it
    @property
    def TimeoutError(self):
        return self._regex.TimeoutError


class ErrorDetail:
    """Detailed error information for debugging."""

    def __init__(
        self,
        message: str,
        error_type: str = "Error",
        line_number: Optional[int] = None,
        code_context: Optional[list[str]] = None,
        traceback_lines: Optional[list[str]] = None,
        source_file: str = "<tool>",
        http_info: Optional[dict[str, Any]] = None,
    ):
        self.message = message
        self.error_type = error_type
        self.line_number = line_number
        self.code_context = code_context or []
        self.traceback_lines = traceback_lines or []
        self.source_file = source_file
        self.http_info = http_info

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "message": self.message,
            "error_type": self.error_type,
            "line_number": self.line_number,
            "code_context": self.code_context,
            "traceback": self.traceback_lines,
            "source_file": self.source_file,
        }
        if self.http_info:
            result["http_info"] = self.http_info
        return result

    def __str__(self) -> str:
        if self.line_number:
            return f"{self.error_type} at line {self.line_number}: {self.message}"
        return f"{self.error_type}: {self.message}"


class DebugInfo:
    """Debug information captured during execution."""

    def __init__(self):
        self.http_calls: list[dict[str, Any]] = []

    def add_http_call(
        self,
        method: str,
        url: str,
        status_code: Optional[int] = None,
        duration_ms: int = 0,
        request_headers: Optional[dict] = None,
        response_preview: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.http_calls.append(
            {
                "method": method,
                "url": url,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "request_headers": request_headers,
                "response_preview": response_preview,
                "error": error,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "http_calls": self.http_calls,
        }


class ExecutionResult:
    """Result of executing Python code."""

    def __init__(
        self,
        success: bool,
        result: Any = None,
        error: Optional[str] = None,
        error_detail: Optional[ErrorDetail] = None,
        stdout: str = "",
        duration_ms: int = 0,
        debug_info: Optional[DebugInfo] = None,
    ):
        self.success = success
        self.result = result
        self.error = error
        self.error_detail = error_detail
        self.stdout = stdout
        self.duration_ms = duration_ms
        self.debug_info = debug_info

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        # Enforce result size limit to prevent memory exhaustion
        result_value = self.result
        if result_value is not None:
            try:
                result_serialized = (
                    json.dumps(result_value)
                    if not isinstance(result_value, str)
                    else result_value
                )
                if len(result_serialized) > MAX_OUTPUT_SIZE:
                    result_value = (
                        result_serialized[:MAX_OUTPUT_SIZE]
                        + f"\n... [RESULT TRUNCATED - exceeded"
                        f" {MAX_OUTPUT_SIZE // 1024}KB limit] ..."
                    )
            except (TypeError, ValueError):
                # Non-serializable: convert to string representation
                try:
                    result_value = str(result_value)
                except Exception:
                    result_value = "<unserializable result>"
            except Exception as e:
                # MemoryError, RecursionError, etc. during serialization
                logger.error(f"Result serialization failed: {type(e).__name__}: {e}")
                try:
                    result_value = str(result_value)[:MAX_OUTPUT_SIZE]
                except Exception:
                    result_value = f"<result serialization failed: {type(e).__name__}>"

        result = {
            "success": self.success,
            "result": result_value,
            "error": self.error,
            "stdout": self.stdout[:MAX_OUTPUT_SIZE] if self.stdout else "",
            "duration_ms": self.duration_ms,
        }
        if self.error_detail:
            result["error_detail"] = self.error_detail.to_dict()
        if self.debug_info:
            result["debug_info"] = self.debug_info.to_dict()
        return result


def extract_error_detail(
    exception: Exception,
    python_code: str,
    source_file: str = "<tool>",
) -> ErrorDetail:
    """Extract detailed error information from an exception.

    Parses the traceback to find errors in user code and provides
    context around the error location.
    """
    error_type = type(exception).__name__
    message = str(exception)
    line_number = None
    code_context = []

    # Get full traceback
    tb_lines = traceback.format_exception(
        type(exception), exception, exception.__traceback__
    )

    # Find line number from traceback
    for line in reversed(tb_lines):
        # Look for lines mentioning our source file
        if source_file in line:
            # Parse line like '  File "<tool>", line 5, in main'
            import regex

            match = regex.search(
                rf'File "{regex.escape(source_file)}", line (\d+)',
                line,
                timeout=REGEX_TIMEOUT,
            )
            if match:
                line_number = int(match.group(1))
                break

    # Extract code context if we found a line number
    if line_number and python_code:
        code_lines = python_code.split("\n")
        start = max(0, line_number - 3)
        end = min(len(code_lines), line_number + 2)

        for i in range(start, end):
            prefix = ">>> " if i == line_number - 1 else "    "
            code_context.append(f"{i + 1:4d} {prefix}{code_lines[i]}")

    # Clean up traceback for user display
    clean_tb = []
    for line in tb_lines:
        if "sandbox/app" not in line and "__builtins__" not in line:
            clean_tb.append(line.rstrip())

    # Extract structured HTTP info from httpx exceptions
    http_info = _extract_http_info(exception)

    return ErrorDetail(
        message=message,
        error_type=error_type,
        line_number=line_number,
        code_context=code_context,
        traceback_lines=clean_tb,
        source_file=source_file,
        http_info=http_info,
    )


def _extract_http_info(exception: Exception) -> Optional[dict[str, Any]]:
    """Extract structured HTTP info from httpx exceptions.

    When a tool crashes with an httpx.HTTPStatusError, this extracts the
    status code, request URL, key response headers, and a body preview so
    the caller can distinguish "tool crashed before HTTP" from "HTTP 403
    from rate limiting" from "HTTP 403 from wrong User-Agent".
    """
    try:
        import httpx as _httpx
    except ImportError:
        return None

    if isinstance(exception, _httpx.HTTPStatusError):
        resp = exception.response
        info: dict[str, Any] = {
            "status_code": resp.status_code,
            "url": str(exception.request.url),
        }
        # Key headers for debugging rate limits and bot detection
        header_keys = [
            "content-type",
            "retry-after",
            "x-ratelimit-remaining",
            "x-ratelimit-limit",
            "x-ratelimit-reset",
            "x-deny-reason",
        ]
        headers = {}
        for key in header_keys:
            val = resp.headers.get(key)
            if val:
                headers[key] = val
        if headers:
            info["response_headers"] = headers
        # Body preview — enough to distinguish HTML error page from JSON error
        try:
            body = resp.text[:500]
            if body:
                info["body_preview"] = body
        except Exception:
            pass
        return info

    if isinstance(exception, _httpx.ConnectError):
        return {"error_type": "ConnectError", "detail": str(exception)}

    if isinstance(exception, _httpx.TimeoutException):
        return {"error_type": "TimeoutException", "detail": str(exception)}

    return None


# --- SSRF Prevention for Python Code Mode ---
# SSRFProtectedAsyncHttpClient is imported at the top of the file


class DebugHttpClient:
    """Wrapper around httpx.AsyncClient that captures request/response info.

    Used in debug mode to provide visibility into HTTP calls made by user code.
    """

    def __init__(self, client: httpx.AsyncClient, debug_info: DebugInfo):
        self._client = client
        self._debug_info = debug_info

    async def _capture_request(
        self,
        method: str,
        url: str,
        response: Optional[httpx.Response] = None,
        error: Optional[Exception] = None,
        duration_ms: int = 0,
        **kwargs,
    ):
        """Capture request/response details for debugging."""
        # Sanitize headers (remove auth for display)
        request_headers = {}
        if "headers" in kwargs:
            for k, v in kwargs["headers"].items():
                if k.lower() in ("authorization", "x-api-key"):
                    request_headers[k] = "[REDACTED]"
                else:
                    request_headers[k] = v

        response_preview = None
        status_code = None

        if response:
            status_code = response.status_code
            try:
                # Get first 500 chars of response for preview
                content = response.text[:500]
                if len(response.text) > 500:
                    content += "... [truncated]"
                response_preview = content
            except Exception:
                response_preview = "[binary content]"

        self._debug_info.add_http_call(
            method=method,
            url=str(url),
            status_code=status_code,
            duration_ms=duration_ms,
            request_headers=request_headers if request_headers else None,
            response_preview=response_preview,
            error=str(error) if error else None,
        )

    async def get(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.get(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "GET", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "GET", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def post(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.post(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "POST", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "POST", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def put(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.put(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "PUT", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "PUT", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def patch(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.patch(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "PATCH", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "PATCH", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def delete(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.delete(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "DELETE", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "DELETE", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def head(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.head(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "HEAD", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "HEAD", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def options(self, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.options(url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "OPTIONS", url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                "OPTIONS", url, error=e, duration_ms=duration, **kwargs
            )
            raise

    async def request(self, method, url, **kwargs):
        start = time.monotonic()
        try:
            response = await self._client.request(method, url, **kwargs)
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                method, url, response=response, duration_ms=duration, **kwargs
            )
            return response
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            await self._capture_request(
                method, url, error=e, duration_ms=duration, **kwargs
            )
            raise


# Minimum secret length to attempt redaction (avoids false positives on short values)
_MIN_SECRET_REDACTION_LENGTH = 8


def _redact_secrets(text: str, secrets: dict[str, str] | None) -> str:
    """Redact known secret values from text to prevent accidental leakage.

    Scans the text for any secret value and replaces it with [REDACTED].
    Only redacts values >= _MIN_SECRET_REDACTION_LENGTH to avoid false positives.
    """
    if not secrets or not text:
        return text
    for value in secrets.values():
        if value and len(value) >= _MIN_SECRET_REDACTION_LENGTH:
            text = text.replace(value, "[REDACTED]")
    return text


class PythonExecutor:
    """Executes Python code safely with injected dependencies.

    Supports:
    - Helper code that gets loaded into the namespace
    - Pre-authenticated httpx.AsyncClient injection
    - Execution timeouts
    - Output size limits
    - Safe built-in restrictions
    """

    def _create_safe_builtins(
        self,
        allowed_modules: set[str] | None = None,
    ) -> dict[str, Any]:
        """Create a restricted builtins dict for safe execution.

        Delegates to the module-level create_safe_builtins() which is the
        single source of truth for sandbox builtins.
        """
        return create_safe_builtins(allowed_modules=allowed_modules)

    def _create_execution_namespace(
        self,
        http_client: httpx.AsyncClient,
        allowed_modules: set[str] | None = None,
        secrets: dict[str, str] | None = None,
        allowed_hosts: set[str] | None = None,
    ) -> dict[str, Any]:
        """Create the execution namespace with injected dependencies.

        Args:
            http_client: HTTP client for making requests
            allowed_modules: Set of allowed module names (None = use defaults)
            secrets: Dict of secret key→value pairs (read-only)
            allowed_hosts: Set of approved network hostnames (None = no restriction)
        """
        from types import MappingProxyType

        # Wrap HTTP client with SSRF protection to prevent access to internal IPs.
        # If allowed_hosts is set, also enforce per-server network allowlist.
        protected_client = SSRFProtectedAsyncHttpClient(
            http_client, allowed_hosts=allowed_hosts
        )

        namespace = {
            "__builtins__": self._create_safe_builtins(allowed_modules),
            # Inject SSRF-protected HTTP client
            "http": protected_client,
            # Inject commonly used modules wrapped in SafeModuleProxy
            # to prevent attribute traversal (e.g., datetime.sys.modules["os"])
            "json": SafeModuleProxy(json, name="json"),
            "datetime": SafeModuleProxy(datetime, name="datetime"),
            # Inject read-only secrets dict
            "secrets": MappingProxyType(secrets or {}),
        }

        return namespace

    async def execute(
        self,
        python_code: str,
        arguments: dict[str, Any],
        http_client: httpx.AsyncClient,
        timeout: float = DEFAULT_TIMEOUT,
        debug_mode: bool = False,
        allowed_modules: set[str] | None = None,
        secrets: dict[str, str] | None = None,
        allowed_hosts: set[str] | None = None,
    ) -> ExecutionResult:
        """Execute Python code with the provided arguments.

        Args:
            python_code: Python code with async main() function
            arguments: Keyword arguments to pass to main()
            http_client: Pre-authenticated httpx client
            timeout: Execution timeout in seconds
            debug_mode: If True, capture detailed debug info
            allowed_modules: Set of module names allowed for import (None = defaults)
            allowed_hosts: Set of approved network hostnames (None = no restriction)

        Returns:
            ExecutionResult with success/error and result
        """
        start_time = time.monotonic()
        stdout_capture = SizeLimitedStringIO()  # Use size-limited to prevent OOM
        debug_info = DebugInfo() if debug_mode else None

        # Wrap HTTP client to capture debug info
        if debug_mode:
            http_client = DebugHttpClient(http_client, debug_info)

        # SECURITY: Validate code for sandbox escape patterns before execution
        is_safe, error_msg = validate_code_safety(python_code, "<tool>")
        if not is_safe:
            error_detail = ErrorDetail(
                message=error_msg,
                error_type="SecurityError",
                source_file="<tool>",
            )
            return ExecutionResult(
                success=False,
                error=error_msg,
                error_detail=error_detail,
                stdout="",
                duration_ms=int((time.monotonic() - start_time) * 1000),
                debug_info=debug_info,
            )

        try:
            # Create execution namespace
            try:
                namespace = self._create_execution_namespace(
                    http_client,
                    allowed_modules,
                    secrets,
                    allowed_hosts,
                )
            except ValueError as e:
                error_detail = ErrorDetail(
                    message=str(e),
                    error_type="NamespaceError",
                    source_file="<setup>",
                )
                return ExecutionResult(
                    success=False,
                    error=str(e),
                    error_detail=error_detail,
                    stdout=stdout_capture.getvalue(),
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                    debug_info=debug_info,
                )

            # SECURITY: Override print() in builtins to capture stdout per-execution
            # instead of replacing global sys.stdout. This prevents output leakage
            # between concurrent tool executions (race condition).
            namespace["__builtins__"]["print"] = lambda *args, **kwargs: print(
                *args, file=stdout_capture, **kwargs
            )

            # Compile and execute the user's code to define main()
            # SECURITY (F-01): Run exec() in a thread with timeout to prevent
            # module-level infinite loops from blocking the event loop.
            # Without this, code outside main() (e.g., `while True: pass`)
            # blocks the entire sandbox indefinitely.
            compiled = compile(python_code, "<tool>", "exec")
            loop = asyncio.get_event_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, exec, compiled, namespace),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                error_detail = ErrorDetail(
                    message=f"Code initialization timed out after {timeout} seconds. "
                    "Check for expensive computation outside main().",
                    error_type="TimeoutError",
                    source_file="<tool>",
                )
                return ExecutionResult(
                    success=False,
                    error=f"Code initialization timed out after {timeout} seconds",
                    error_detail=error_detail,
                    stdout=stdout_capture.getvalue(),
                    duration_ms=int(timeout * 1000),
                    debug_info=debug_info,
                )

            # Verify main() exists and is async
            if "main" not in namespace:
                error_detail = ErrorDetail(
                    message="Code must define an async main() function",
                    error_type="ValidationError",
                )
                return ExecutionResult(
                    success=False,
                    error="Code must define an async main() function",
                    error_detail=error_detail,
                    stdout=stdout_capture.getvalue(),
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                    debug_info=debug_info,
                )

            main_func = namespace["main"]
            if not asyncio.iscoroutinefunction(main_func):
                error_detail = ErrorDetail(
                    message="main() must be an async function (use 'async def main(...)')",
                    error_type="ValidationError",
                )
                return ExecutionResult(
                    success=False,
                    error="main() must be an async function (use 'async def main(...)')",
                    error_detail=error_detail,
                    stdout=stdout_capture.getvalue(),
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                    debug_info=debug_info,
                )

            # Execute main() with timeout
            try:
                result = await asyncio.wait_for(
                    main_func(**arguments),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                error_detail = ErrorDetail(
                    message=f"Execution timed out after {timeout} seconds",
                    error_type="TimeoutError",
                )
                return ExecutionResult(
                    success=False,
                    error=f"Execution timed out after {timeout} seconds",
                    error_detail=error_detail,
                    stdout=stdout_capture.getvalue(),
                    duration_ms=int(timeout * 1000),
                    debug_info=debug_info,
                )

            # Ensure result is JSON-serializable
            try:
                json.dumps(result)
            except (TypeError, ValueError):
                result = str(result)

            # SECURITY: Redact any secret values that leaked into output.
            # This catches accidental leaks in return values and print statements.
            stdout_text = _redact_secrets(stdout_capture.getvalue(), secrets)
            if isinstance(result, str):
                result = _redact_secrets(result, secrets)
            elif isinstance(result, dict):
                # Redact within JSON-serialized form, then parse back
                redacted = _redact_secrets(json.dumps(result), secrets)
                try:
                    result = json.loads(redacted)
                except (json.JSONDecodeError, ValueError):
                    result = redacted

            return ExecutionResult(
                success=True,
                result=result,
                stdout=stdout_text,
                duration_ms=int((time.monotonic() - start_time) * 1000),
                debug_info=debug_info,
            )

        except SyntaxError as e:
            # Extract code context for syntax errors
            code_context = []
            if e.lineno and python_code:
                code_lines = python_code.split("\n")
                start = max(0, e.lineno - 3)
                end = min(len(code_lines), e.lineno + 1)
                for i in range(start, end):
                    prefix = ">>> " if i == e.lineno - 1 else "    "
                    code_context.append(f"{i + 1:4d} {prefix}{code_lines[i]}")

            error_detail = ErrorDetail(
                message=e.msg or "Invalid syntax",
                error_type="SyntaxError",
                line_number=e.lineno,
                code_context=code_context,
            )
            return ExecutionResult(
                success=False,
                error=f"Syntax error at line {e.lineno}: {e.msg}",
                error_detail=error_detail,
                stdout=stdout_capture.getvalue(),
                duration_ms=int((time.monotonic() - start_time) * 1000),
                debug_info=debug_info,
            )
        except ImportError as e:
            error_detail = ErrorDetail(
                message=str(e),
                error_type="ImportError",
            )
            return ExecutionResult(
                success=False,
                error=str(e),
                error_detail=error_detail,
                stdout=stdout_capture.getvalue(),
                duration_ms=int((time.monotonic() - start_time) * 1000),
                debug_info=debug_info,
            )
        except Exception as e:
            # Capture full traceback for debugging
            tb = traceback.format_exc()
            logger.error(f"Execution error: {tb}")

            error_detail = extract_error_detail(e, python_code)

            return ExecutionResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                error_detail=error_detail,
                stdout=stdout_capture.getvalue(),
                duration_ms=int((time.monotonic() - start_time) * 1000),
                debug_info=debug_info,
            )


# Global executor instance
python_executor = PythonExecutor()
