from typing import Any

from pydantic import BaseModel, Field


class Response_Schema(BaseModel):
    """
    Standard envelope used by **every** API response.

    - ``status_code`` mirrors the logical HTTP status (200, 201, 400, 401, 403, 404, 422 …).
    - ``message`` is a human-readable summary.
    - ``data`` contains the payload on success, or ``null`` on error.
    """

    status_code: int = Field(
        ...,
        description="Logical HTTP status code (e.g. 200 for success, 201 for created, 4xx for client errors).",
        examples=[200],
    )
    message: str = Field(
        ...,
        description="Human-readable result summary, e.g. 'Login successful' or 'Validation Error: …'.",
        examples=["Success"],
    )
    data: Any = Field(
        None,
        description="Response payload — contains the requested resource(s) on success, or null on error.",
    )


def success_response(
    data: Any = None, message: str = "Success", status_code: int = 200
) -> Response_Schema:
    """Build the standard success envelope. Mirrors the local helpers in
    ``routes/user.py`` / ``routes/pharmacy.py`` so every route can share one
    implementation."""
    return Response_Schema(status_code=status_code, message=message, data=data)
