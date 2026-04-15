"""
Geographic utilities.

Primary use case: compute distance from any FL property to the nearest ocean.
We use a list of ~120 anchor points along the Florida coastline (Atlantic,
Gulf, and Keys) and compute the minimum Haversine distance to any anchor.

Accuracy: anchor points are spaced ~5-15 miles apart, giving ~2-5 mile
worst-case error for the "distance to ocean" calculation. Good enough for
filtering leads by coastal exposure.
"""

import math


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (lat, lon) points in miles."""
    R = 3958.8  # Earth radius in miles
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


# Florida coastline anchor points (lat, lon), clockwise from GA border
# sampled every 5-15 miles along both Atlantic and Gulf coasts, plus Keys.
# Sources: Google Maps lookups of coastal cities, inlets, beaches.
FL_COASTLINE_ANCHORS: list[tuple[float, float]] = [
    # Atlantic Coast — GA border → Keys (roughly north → south)
    (30.71, -81.45),  # Fernandina Beach
    (30.50, -81.44),  # Amelia Island south
    (30.37, -81.40),  # Mayport
    (30.29, -81.39),  # Jacksonville Beach
    (30.18, -81.38),  # Ponte Vedra
    (29.90, -81.31),  # St. Augustine
    (29.66, -81.22),  # Matanzas Inlet
    (29.47, -81.12),  # Flagler Beach
    (29.21, -81.02),  # Daytona Beach
    (29.02, -80.90),  # Ponce Inlet
    (28.81, -80.80),  # New Smyrna Beach
    (28.60, -80.64),  # Cape Canaveral
    (28.39, -80.61),  # Cocoa Beach
    (28.08, -80.57),  # Melbourne Beach
    (27.83, -80.46),  # Sebastian Inlet
    (27.64, -80.37),  # Vero Beach
    (27.47, -80.31),  # Fort Pierce
    (27.28, -80.22),  # St. Lucie Inlet
    (27.19, -80.17),  # Stuart (Hutchinson Island)
    (26.94, -80.07),  # Jupiter
    (26.77, -80.04),  # Palm Beach (Lake Worth inlet)
    (26.53, -80.05),  # Boynton Beach
    (26.46, -80.06),  # Delray Beach
    (26.36, -80.07),  # Boca Raton
    (26.25, -80.08),  # Deerfield Beach
    (26.19, -80.10),  # Pompano Beach
    (26.12, -80.10),  # Fort Lauderdale
    (26.02, -80.11),  # Hollywood
    (25.93, -80.12),  # Hallandale
    (25.91, -80.12),  # Aventura / Sunny Isles
    (25.85, -80.12),  # Bal Harbour
    (25.79, -80.13),  # Miami Beach
    (25.73, -80.15),  # South Beach / Government Cut
    (25.69, -80.16),  # Key Biscayne
    (25.58, -80.32),  # Homestead Bay
    (25.47, -80.48),  # Biscayne Bay south
    # Keys
    (25.16, -80.38),  # Key Largo
    (24.90, -80.74),  # Islamorada
    (24.71, -80.97),  # Long Key
    (24.71, -81.09),  # Marathon
    (24.67, -81.34),  # Big Pine Key
    (24.55, -81.78),  # Key West
    # Gulf Coast — Keys → Panhandle (roughly south → northwest)
    (25.12, -81.07),  # Cape Sable
    (25.82, -81.38),  # Everglades City
    (25.93, -81.72),  # Marco Island
    (26.14, -81.80),  # Naples
    (26.22, -81.81),  # Vanderbilt Beach
    (26.34, -81.85),  # Bonita Beach
    (26.44, -81.95),  # Fort Myers Beach
    (26.45, -82.11),  # Sanibel
    (26.53, -82.19),  # Captiva
    (26.75, -82.26),  # Boca Grande
    (26.93, -82.35),  # Englewood
    (27.10, -82.46),  # Venice
    (27.20, -82.51),  # Casey Key
    (27.27, -82.55),  # Siesta Key
    (27.33, -82.58),  # Lido Key
    (27.40, -82.61),  # Longboat Key north
    (27.50, -82.71),  # Anna Maria
    (27.58, -82.73),  # Bradenton Beach
    (27.65, -82.74),  # St. Pete Beach south
    (27.73, -82.75),  # St. Pete Beach
    (27.82, -82.80),  # Treasure Island
    (27.88, -82.84),  # Madeira Beach
    (27.98, -82.83),  # Clearwater
    (28.04, -82.83),  # Dunedin
    (28.15, -82.77),  # Tarpon Springs
    (28.25, -82.74),  # Anclote Key
    (28.36, -82.69),  # Hudson
    (28.44, -82.66),  # Port Richey
    (28.53, -82.65),  # Hernando Beach
    (28.61, -82.66),  # Bayport
    (28.73, -82.68),  # Homosassa
    (28.90, -82.64),  # Crystal River
    (29.02, -82.76),  # Yankeetown
    (29.14, -83.04),  # Cedar Key
    (29.38, -83.17),  # Suwannee
    (29.58, -83.33),  # Horseshoe Beach
    (29.67, -83.39),  # Steinhatchee
    (29.83, -83.58),  # Keaton Beach
    (29.92, -83.73),  # Econfina
    (30.01, -83.94),  # Aucilla
    (30.06, -84.18),  # St. Marks
    (30.00, -84.37),  # Panacea
    (29.89, -84.58),  # Alligator Point
    (29.80, -84.74),  # Carrabelle
    (29.73, -84.99),  # Apalachicola
    (29.72, -85.02),  # Eastpoint
    (29.73, -85.02),  # St. George Island
    (29.69, -85.35),  # Cape San Blas
    (29.81, -85.30),  # Port St. Joe
    (29.98, -85.40),  # Mexico Beach
    (30.10, -85.58),  # Tyndall
    (30.14, -85.66),  # Panama City
    (30.15, -85.75),  # Panama City Beach east
    (30.19, -85.80),  # Panama City Beach central
    (30.26, -85.96),  # Laguna Beach
    (30.28, -86.04),  # Inlet Beach
    (30.33, -86.19),  # Seagrove Beach
    (30.33, -86.25),  # Seaside
    (30.38, -86.47),  # Destin east
    (30.39, -86.50),  # Destin
    (30.41, -86.62),  # Fort Walton Beach
    (30.41, -86.69),  # Okaloosa Island
    (30.40, -86.80),  # Navarre Beach east
    (30.38, -86.93),  # Navarre Beach west
    (30.33, -87.14),  # Pensacola Beach
    (30.32, -87.28),  # Fort Pickens
    (30.32, -87.40),  # Perdido Key east
    (30.30, -87.43),  # Perdido Key
    (30.28, -87.51),  # AL border
]


def distance_to_ocean_miles(lat: float | None, lon: float | None) -> float | None:
    """Return the minimum distance (miles) from (lat, lon) to the nearest
    FL coastline anchor point. Returns None if coordinates are missing."""
    if lat is None or lon is None:
        return None
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    min_dist = float("inf")
    for alat, alon in FL_COASTLINE_ANCHORS:
        d = haversine_miles(lat, lon, alat, alon)
        if d < min_dist:
            min_dist = d
    return round(min_dist, 2)
