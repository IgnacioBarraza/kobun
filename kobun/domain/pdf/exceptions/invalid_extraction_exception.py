class InvalidExtractionException(Exception):
    """
    Raised when an asset extraction is asked for in terms that cannot be
    honoured: an unknown mode, or a resolution outside the usable range.

    It is an expected error —the user can fix it— and not a bug.
    """
    pass
