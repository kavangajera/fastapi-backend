"""
routes/ndc_search.py
──────────────────────
`GET /pharmacy/{ph_id}/ndc-search/{ndc}` — standalone NDC lookup: enter an
NDC, hit FDA (via the shared cache), get back found/not-found and, when
found, active/discontinued.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from core.async_db import get_async_db
from core.enums import Feature
from middlewares.auth import auth_incoming_req
from schemas.ndc_search import NdcSearchResponse
from schemas.response_schema import Response_Schema, success_response
from schemas.system_internal_user_schema import System_Internal_User_Schema
from services.feature_gate import ensure_feature
from services.ndc_search_service import search_ndc
from services.pharmacy_authz import ensure_pharmacy_access

router = APIRouter(tags=["NDC Search"])


@router.get(
    "/pharmacy/{ph_id}/ndc-search/{ndc}",
    response_model=Response_Schema,
    summary="Look up whether an NDC is active in the FDA Drug NDC Directory",
    description=(
        "Enter an NDC, hit FDA (via the shared `medicine_ndc_cache`), and get "
        "back whether it was found and, when found, whether it's currently "
        "active or discontinued. No dispense data involved — this is a "
        "standalone lookup."
    ),
)
async def ndc_search(
    ph_id: int = Path(..., description="medical_store_id"),
    ndc: str = Path(..., description="NDC in any common form (11-digit, hyphenated NDC10, etc.)"),
    db: AsyncSession = Depends(get_async_db),
    user: System_Internal_User_Schema = Depends(auth_incoming_req),
) -> Response_Schema:
    await ensure_pharmacy_access(db, user, ph_id)
    await ensure_feature(db, ph_id, Feature.COMPLIANCE_REPORTS)

    result: NdcSearchResponse = await search_ndc(db, ndc)
    return success_response(result, "NDC search complete")
