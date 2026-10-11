from datetime import datetime, timedelta, timezone

from app.dedupe import distance_m, find_target, normalize_address

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)


def case(id, lat=29.7722, lng=-95.3444, address="2500 Lyons Ave, Houston", minutes_ago=0, **kw):
    base = dict(id=id, lat=lat, lng=lng, address=address, source="call", status="open",
                location_confidence="high", created_at=NOW - timedelta(minutes=minutes_ago))
    base.update(kw)
    return base


def test_normalize_address():
    assert normalize_address("2500 Lyons Avenue, Houston, TX 77020") == normalize_address("2500 lyons ave")
    assert normalize_address(None) == ""


def test_distance():
    assert distance_m(case(1), case(2, lat=29.7722 + 0.0005)) < 75     # ~55 m
    assert distance_m(case(1), case(2, lat=29.7722 + 0.002)) > 75      # ~220 m


def test_merges_into_earliest_nearby_open_case():
    new = case(3, lat=29.77225)
    older, oldest = case(2, minutes_ago=10), case(1, minutes_ago=30)
    assert find_target(new, [older, oldest])["id"] == 1


def test_same_address_far_pins_still_merge():
    assert find_target(case(2), [case(1, lat=29.80, address="2500 Lyons Avenue, Houston, Texas")])["id"] == 1


def test_never_merges():
    new = case(9)
    assert find_target(new, [case(1, source="simulated")]) is None          # surge cases
    assert find_target(new, [case(1, status="closed")]) is None             # closed
    assert find_target(new, [case(1, status="rescued")]) is None
    assert find_target(new, [case(1, location_confidence="approximate")]) is None  # pin not confirmed
    assert find_target(new, [case(1, minutes_ago=180)]) is None             # older than 2 hours
    assert find_target(new, [case(1, lat=29.80, address="99 Other St")]) is None   # different place
    assert find_target(case(9, source="simulated"), [case(1)]) is None
    assert find_target(case(9, location_confidence="none"), [case(1)]) is None
