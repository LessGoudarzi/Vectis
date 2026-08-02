from fastapi import APIRouter, HTTPException, Query
from database import db
from trace import DEFAULT_MAX_MILES

router = APIRouter(prefix="/api/v1/trace", tags=["Network Trace"])


@router.get("/power-plant/{plant_id}")
async def trace_power_plant(
    plant_id: int,
    max_miles: float = Query(DEFAULT_MAX_MILES, gt=0, description="Cumulative distance cap in miles; re-request with a larger value to 'trace further'"),
    allow_cross_subregion: bool = Query(
        False, description="Let the trace continue past the plant's home NERC subregion boundary"
    ),
):
    result = db.trace_power_plant(plant_id, max_miles=max_miles, allow_cross_subregion=allow_cross_subregion)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail=f"Power plant '{plant_id}' not found.")
    return result
