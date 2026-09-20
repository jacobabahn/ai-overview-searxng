class OverviewError(Exception):
    """An error whose code and message are safe to show in the browser."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
