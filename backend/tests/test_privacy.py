from datetime import datetime, timezone

from app.cases import mask_phone, serialize


def test_mask_phone():
    assert mask_phone("+12814085709") == "•••-•••-5709"
    assert mask_phone(None) is None and mask_phone("") is None


def test_serialize_never_contains_the_full_number():
    case = {"id": 5, "phone": "+12814085709", "base_priority": 50, "status": "open",
            "created_at": datetime.now(timezone.utc), "conversation_ids": ["conv_x"]}
    out = serialize(case)
    assert out["phone"] == "•••-•••-5709"
    assert "2814085709" not in str(out) and "conversation_ids" not in out
