from fastapi import APIRouter, Query, HTTPException, Response
from database import db
from typing import Optional

router = APIRouter(prefix="/api/v1/layers", tags=["Spatial Layers"])

VALID_LAYERS = ["auto_plants", "power_grid", "power_plants", "industrial_convergence"]


@router.get("/{layer_id}")
async def get_layer_data(
    layer_id: str,
    min_lon: Optional[float] = Query(None),
    min_lat: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    corridor: Optional[str] = Query(None, description="Filter industrial_convergence facilities by corridor"),
    energy_bottleneck_flag: Optional[bool] = Query(None, description="Filter industrial_convergence facilities by bottleneck status"),
):
    table_name = layer_id.replace("-", "_")
    if table_name not in VALID_LAYERS:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    bbox = None
    if all(v is not None for v in [min_lon, min_lat, max_lon, max_lat]):
        bbox = (min_lon, min_lat, max_lon, max_lat)

    if table_name == "industrial_convergence":
        geojson_raw = db.get_industrial_convergence_geojson(
            bbox=bbox,
            corridor=corridor,
            energy_bottleneck_flag=energy_bottleneck_flag,
        )
    else:
        geojson_raw = db.get_layer_geojson(table_name, bbox)

    return Response(content=geojson_raw, media_type="application/json")


@router.get("/industrial-convergence/corridor-summary")
async def get_industrial_convergence_corridor_summary():
    """Corridor-level rollups (facility counts, output totals, bottleneck
    counts) — mirrors power/app.py's /api/bucket-summaries endpoint, which
    exists so the frontend can build filter chips without pulling every
    feature down first.
    """
    return db.get_corridor_summary()
