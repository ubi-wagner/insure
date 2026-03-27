from geopy.geocoders import Nominatim
from geopy.distance import geodesic


def get_county_from_coords(lat: float, lng: float) -> str | None:
    """Reverse geocode coordinates to get the Florida county name."""
    try:
        geolocator = Nominatim(user_agent="insure-lead-gen")
        location = geolocator.reverse(f"{lat}, {lng}", exactly_one=True)
        if location and location.raw.get("address"):
            county = location.raw["address"].get("county", "")
            # Strip " County" suffix if present
            return county.replace(" County", "").strip() or None
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None


def get_bounding_box_center(bbox: dict) -> tuple[float, float]:
    """Return the center point (lat, lng) of a bounding box."""
    lat = (bbox["north"] + bbox["south"]) / 2
    lng = (bbox["east"] + bbox["west"]) / 2
    return lat, lng


def is_within_bounds(lat: float, lng: float, bbox: dict) -> bool:
    """Check if a point falls within the bounding box."""
    return (
        bbox["south"] <= lat <= bbox["north"]
        and bbox["west"] <= lng <= bbox["east"]
    )


def distance_to_coast_miles(lat: float, lng: float) -> float:
    """
    Rough estimate of distance to nearest Florida coast.
    Uses a simplified approach - checks distance to nearest known coastal point.
    For production, would use a coastline shapefile.
    """
    # Key Florida coastal reference points
    coastal_points = [
        (27.9659, -82.8001),  # Clearwater Beach
        (26.1003, -80.1298),  # Fort Lauderdale Beach
        (25.7617, -80.1918),  # Miami Beach
        (26.7153, -80.0534),  # Palm Beach
        (30.2954, -81.3931),  # Jacksonville Beach
        (27.4989, -82.5748),  # Sarasota Beach
        (26.4615, -81.9495),  # Fort Myers Beach
        (24.5551, -81.7800),  # Key West
        (28.4132, -80.6051),  # Cocoa Beach
        (29.2108, -81.0228),  # Daytona Beach
        (30.3935, -86.4958),  # Destin
        (30.1766, -85.8055),  # Panama City Beach
        (27.3264, -82.5307),  # Siesta Key
        (26.2235, -80.1256),  # Pompano Beach
        (27.8600, -82.8400),  # Indian Rocks Beach
    ]

    min_distance = float("inf")
    for coast_lat, coast_lng in coastal_points:
        dist = geodesic((lat, lng), (coast_lat, coast_lng)).miles
        if dist < min_distance:
            min_distance = dist

    return round(min_distance, 2)
