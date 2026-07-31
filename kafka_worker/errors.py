"""Typed worker failures that must not consume retry attempts."""


class PermanentDocumentError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
