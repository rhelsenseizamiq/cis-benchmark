from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cis-benchmark")
except PackageNotFoundError:
    # Running from source without an install (e.g. a plain checkout).
    __version__ = "0.0.0-dev"
