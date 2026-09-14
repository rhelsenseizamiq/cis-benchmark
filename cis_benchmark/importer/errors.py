class ImporterError(Exception):
    """Raised for any expected `cis import` failure: missing pdftotext,
    a benchmark document whose structure doesn't match what the parser
    expects, or a --cloud choice with no parser implemented yet. Callers
    (cli.py) catch this and print a clean message — never a raw traceback.
    """
