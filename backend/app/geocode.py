"""Address -> coordinates, biased to greater Houston.

Uses Google Geocoding when GOOGLE_MAPS_API_KEY is set, otherwise the free
OpenStreetMap Nominatim service (max 1 request/second, so calls are serialized).
"""

import asyncio
import logging
import re
import time

import httpx

from . import config
from .areas import HOUSTON_VIEWBOX

log = logging.getLogger("lifeline.geocode")

_cache: dict[str, tuple[float, float] | None] = {}
_nominatim_lock = asyncio.Lock()
_last_nominatim = 0.0


def _with_city(address: str) -> str:
    if re.search(r"\b(tx|texas)\b", address, re.I):
        return address
    # A city name counts only when it isn't part of a street name like "Bellaire Blvd"
    if re.search(r"\b(houston|pasadena|katy|kingwood|channelview|bellaire|humble|sugar land|pearland|baytown)\b"
                 r"(?!\s+(blvd|st|street|rd|road|ave|avenue|dr|drive|pkwy|fwy|ln|lane|way)\b)",
                 address, re.I):
        return f"{address}, Texas"
    return f"{address}, Houston, Texas"


async def _google(query: str) -> tuple[float, float] | None:
    west, north, east, south = HOUSTON_VIEWBOX
    params = {
        "address": query,
        "bounds": f"{south},{west}|{north},{east}",
        "region": "us",
        "key": config.GOOGLE_MAPS_API_KEY,
    }
    async with httpx.AsyncClient(timeout=6) as client:
        r = await client.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
        data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


async def _nominatim(query: str) -> tuple[float, float] | None:
    global _last_nominatim
    west, north, east, south = HOUSTON_VIEWBOX
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "us",
        "viewbox": f"{west},{north},{east},{south}",
        "bounded": 1,
    }
    headers = {"User-Agent": f"Lifeline-CodeRED-hackathon/1.0 ({config.GEOCODER_CONTACT_EMAIL})"}
    async with _nominatim_lock:
        wait = 1.05 - (time.monotonic() - _last_nominatim)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=6, headers=headers) as client:
                r = await client.get("https://nominatim.openstreetmap.org/search", params=params)
                data = r.json() if r.status_code == 200 else []
        finally:
            _last_nominatim = time.monotonic()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


async def geocode(address: str | None, landmark: str | None = None) -> tuple[float, float] | None:
    """Return (lat, lng) or None. Tries the address, then the landmark."""
    candidates = [a for a in (address, landmark) if a and a.strip()]
    for raw in candidates:
        query = _with_city(raw.strip())
        if query in _cache:
            if _cache[query]:
                return _cache[query]
            continue
        try:
            result = await (_google(query) if config.GOOGLE_MAPS_API_KEY else _nominatim(query))
            _cache[query] = result
        except Exception as exc:  # network trouble: don't cache, try again next time
            log.warning("Geocoding failed for %r: %s", query, exc)
            result = None
        if result:
            return result
    return None
