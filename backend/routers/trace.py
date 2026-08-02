from fastapi import APIRouter, HTTPException, Query
from database import db
from trace import DEFAULT_MAX_MILES

router = APIRouter(prefix="/api/v1/trace", tags=["Network Trace"])


@router.get("/{layer_id}/{facility_id}")
async def trace_facility(
    layer_id: str,
    facility_id: int,
    max_miles: float = Query(DEFAULT_MAX_MILES, gt=0, description="Cumulative distance cap in miles; re-request with a larger value to 'trace further'"),
    allow_cross_subregion: bool = Query(
        False, description="Let the trace continue past the facility's home NERC subregion boundary"
    ),
):
    if layer_id not in db.TRACE_SOURCE_TABLES:
        raise HTTPException(status_code=404, detail=f"Tracing isn't supported for layer '{layer_id}'.")
    result = db.trace_facility(layer_id, facility_id, max_miles=max_miles, allow_cross_subregion=allow_cross_subregion)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail=f"Facility '{facility_id}' not found in layer '{layer_id}'.")
    return result
