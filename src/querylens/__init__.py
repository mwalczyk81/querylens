"""QueryLens: Database query cost analyzer and optimization engine."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("querylens")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
