"""User-facing error types.

The CLI catches ``SlamRegressionError`` and reports it as a clean message with
exit code 2. Anything else escaping to the top level is a bug and should
produce a traceback.
"""


class SlamRegressionError(Exception):
    """Base class for all user-facing errors."""


class TrajectoryError(SlamRegressionError):
    """Raised when a trajectory file cannot be read, parsed, or used."""


class ConfigError(SlamRegressionError):
    """Raised when configuration is missing, malformed, or invalid."""


class MetricsError(SlamRegressionError):
    """Raised when metrics cannot be computed for the given input."""
