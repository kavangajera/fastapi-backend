"""
schemas/ndc_search.py
──────────────────────
Response model for `GET /pharmacy/{ph_id}/ndc-search/{ndc}`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NdcSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ndc: str
    found_in_fda: bool
    active: bool | None = None  # True/False only when found_in_fda; None otherwise
    brand_name: str | None = None
    generic_name: str | None = None
    dosage_form: str | None = None
    marketing_end_date: str | None = None
    message: str  # plain-English summary for the search-bar UI
