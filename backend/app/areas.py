"""Houston-area neighborhoods: used to label cases and to place simulated calls.

Coordinates are approximate neighborhood centers. `risk` weights how often the
surge simulator picks an area (flood-prone areas get more calls).
"""

import math

HOUSTON_CENTER = (29.7604, -95.3698)

AREAS = [
    {"name": "Meyerland", "lat": 29.6866, "lng": -95.4588, "risk": 9,
     "streets": ["S Braeswood Blvd", "Jason St", "Endicott Ln", "Chimney Rock Rd"]},
    {"name": "Kashmere Gardens", "lat": 29.8030, "lng": -95.3270, "risk": 8,
     "streets": ["Lockwood Dr", "Kelley St", "Hirsch Rd", "Liberty Rd"]},
    {"name": "Greenspoint", "lat": 29.9450, "lng": -95.4140, "risk": 8,
     "streets": ["Greens Rd", "Imperial Valley Dr", "Aldine Bender Rd", "Greenspoint Dr"]},
    {"name": "Kingwood", "lat": 30.0499, "lng": -95.1855, "risk": 7,
     "streets": ["Kingwood Dr", "Woodland Hills Dr", "Northpark Dr"]},
    {"name": "Fifth Ward", "lat": 29.7700, "lng": -95.3330, "risk": 6,
     "streets": ["Lyons Ave", "Jensen Dr", "Lockwood Dr"]},
    {"name": "Sunnyside", "lat": 29.6680, "lng": -95.3550, "risk": 6,
     "streets": ["Bellfort Ave", "Cullen Blvd", "Reed Rd"]},
    {"name": "Sharpstown", "lat": 29.6950, "lng": -95.5300, "risk": 5,
     "streets": ["Bellaire Blvd", "Fondren Rd", "Beechnut St"]},
    {"name": "Alief", "lat": 29.7060, "lng": -95.5900, "risk": 6,
     "streets": ["Wilcrest Dr", "Bissonnet St", "Boone Rd"]},
    {"name": "Spring Branch", "lat": 29.8000, "lng": -95.5100, "risk": 4,
     "streets": ["Long Point Rd", "Gessner Rd", "Hammerly Blvd"]},
    {"name": "Acres Homes", "lat": 29.8580, "lng": -95.4400, "risk": 5,
     "streets": ["W Little York Rd", "Antoine Dr", "Pinemont Dr"]},
    {"name": "Clear Lake", "lat": 29.5600, "lng": -95.1300, "risk": 5,
     "streets": ["Bay Area Blvd", "NASA Pkwy", "El Camino Real"]},
    {"name": "Pasadena", "lat": 29.6911, "lng": -95.2091, "risk": 5,
     "streets": ["Red Bluff Rd", "Spencer Hwy", "Shaver St"]},
    {"name": "Channelview", "lat": 29.7760, "lng": -95.1150, "risk": 6,
     "streets": ["Sheldon Rd", "Market St", "Woodforest Blvd"]},
    {"name": "Bear Creek", "lat": 29.8300, "lng": -95.6600, "risk": 7,
     "streets": ["Clay Rd", "Barker Cypress Rd", "Highway 6"]},
    {"name": "Energy Corridor", "lat": 29.7830, "lng": -95.6300, "risk": 6,
     "streets": ["Eldridge Pkwy", "Memorial Dr", "Briar Forest Dr"]},
    {"name": "Katy", "lat": 29.7858, "lng": -95.8245, "risk": 3,
     "streets": ["Mason Rd", "Fry Rd", "Franz Rd"]},
    {"name": "East End", "lat": 29.7330, "lng": -95.3200, "risk": 4,
     "streets": ["Navigation Blvd", "Harrisburg Blvd", "Telephone Rd"]},
    {"name": "Northshore", "lat": 29.7930, "lng": -95.2000, "risk": 4,
     "streets": ["Uvalde Rd", "Wallisville Rd", "Normandy St"]},
]

# Bounding box for geocoding (west, north, east, south) around greater Houston
HOUSTON_VIEWBOX = (-96.10, 30.35, -94.70, 29.25)


def area_mentioned(text: str | None) -> dict | None:
    """Return the first known neighborhood named in free text, e.g. 'near Meyerland Plaza'."""
    if not text:
        return None
    lowered = text.lower()
    for area in AREAS:
        if area["name"].lower() in lowered:
            return area
    return None


def nearest_area(lat: float | None, lng: float | None) -> str | None:
    if lat is None or lng is None:
        return None
    best, best_d = None, float("inf")
    for area in AREAS:
        d = math.hypot(area["lat"] - lat, (area["lng"] - lng) * math.cos(math.radians(lat)))
        if d < best_d:
            best, best_d = area["name"], d
    # ~0.06 deg is roughly 6-7 km; farther than that, call it by city name
    return best if best_d < 0.06 else "Houston area"
