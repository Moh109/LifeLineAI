from app.scoring import VERIFY_PEOPLE, base_score, has_injury, label_for


def score(**case):
    s, reasons = base_score(case)
    return s, label_for(s), reasons


def joined(reasons):
    return " | ".join(reasons)


# ---------- the four scenarios ----------

def test_gunshot_alone_life_threatening_gets_no_water_points():
    s, label, reasons = score(life_threatening=True, people_count=1, water_level=None,
                              critical_reason="Man shot in stomach, bleeding heavily",
                              transcript=[{"role": "user", "message": "My friend got shot, he's bleeding"}])
    assert "water" not in joined(reasons).lower()
    assert label == "red"


def test_fire_none_reported_100_people_battery_1():
    s, label, reasons = score(injuries="none reported", people_count=100, battery_pct=1, notes="House fire")
    assert "Injury" not in joined(reasons)
    assert VERIFY_PEOPLE in reasons
    assert "100 people (+10)" in reasons  # people points stay capped
    assert "Phone at 1%, may lose contact (+5)" in reasons


def test_chest_deep_rising_three_people_elderly_on_oxygen_stays_red():
    s, label, reasons = score(water_level="chest", water_rising=True, people_count=3,
                              vulnerable=["elderly"], medical_needs=["oxygen"])
    assert label == "red" and s >= 60


def test_elderly_wheelchair_user_alone_knee_water_gets_cant_evacuate_every_time():
    variants = [
        dict(vulnerable=["disabled", "elderly"], people_count=1, water_level="knee"),       # post extraction
        dict(vulnerable=["elderly"], people_count=1, water_level="knee",                   # only in the call
             transcript=[{"role": "user", "message": "She's in a wheelchair, alone, water at her knees"}]),
        dict(vulnerable=["elderly"], water_level="knee", notes="Uses a wheelchair, lives alone"),
    ]
    for case in variants:
        s, label, reasons = score(**case)
        assert any(r.startswith("Can't evacuate alone") for r in reasons), case
        assert label in {"orange", "red"}, case


# ---------- one test per bug ----------

def test_a_no_injury_words():
    for text in ["none", "None reported", "no", "N/A", "", None, "none reported.", "no injuries"]:
        assert not has_injury(text), text
    assert has_injury("cut on leg")


def test_b_water_rules_only_for_flood_cases():
    _, _, reasons = score(people_count=2, notes="Heart attack")
    assert not any("water" in r.lower() for r in reasons)
    _, _, reasons = score(people_count=2, notes="Trapped by flood water")  # depth not given, still a flood
    assert "Unknown water level (+10)" in reasons
    _, _, reasons = score(water_level="unknown")  # agent said water, depth unknown
    assert "Unknown water level (+10)" in reasons


def test_c_prank_people_count_is_capped_and_flagged():
    s20, _, r20 = score(people_count=20)
    s100, _, r100 = score(people_count=100)
    assert s20 == s100 == 10
    assert VERIFY_PEOPLE not in r20 and VERIFY_PEOPLE in r100


def test_d_disabled_or_cant_move_alone_triggers_rule():
    for case in [dict(vulnerable=["disabled"], people_count=1),
                 dict(people_count=1, notes="He can't move his legs"),
                 dict(people_count=1, medical_needs=["wheelchair"])]:
        _, label, reasons = score(**case)
        assert any(r.startswith("Can't evacuate alone") for r in reasons), case
        assert label == "orange", case
    _, _, reasons = score(vulnerable=["disabled"], people_count=4)  # family there: not alone
    assert not any(r.startswith("Can't evacuate alone") for r in reasons)


def test_c_high_people_count_sets_needs_review_on_the_case():
    from app.cases import _with_score
    fields = _with_score({"people_count": 100, "notes": "House fire"})
    assert fields["needs_review"] is True and "people count" in fields["review_reason"]
    assert "needs_review" not in _with_score({"people_count": 3})


def test_age_counts_as_elderly_or_child():
    _, _, reasons = score(age="72", people_count=2)
    assert "Vulnerable: elderly (+8)" in reasons
    _, _, reasons = score(age="8 and 40", people_count=2)
    assert "Vulnerable: baby or child (+8)" in reasons
    _, _, reasons = score(age="35", people_count=1)
    assert not any(r.startswith("Vulnerable") for r in reasons)
    _, label, reasons = score(age="81", people_count=1, notes="sprained ankle")  # 81 and alone
    assert any(r.startswith("Can't evacuate alone") for r in reasons) and label == "orange"


def test_non_water_case_summary_never_mentions_water():
    from app.cases import build_summary
    s = build_summary({"people_count": 1, "address": "4173 Elgin St", "water_level": "none", "age": "30",
                       "injuries": "sprained ankle"})
    assert "water" not in s.lower() and "Age: 30." in s


def test_summary_water_sentences_dropped_for_non_water_calls():
    from app.cases import strip_water_talk
    s = ("Ryan is alone at 4173 Elgin Street with a sprained ankle. "
         "There is no water involved and no life-threatening conditions reported.")
    case = {"water_level": "none", "transcript": [{"role": "user", "message": "I sprained my ankle at soccer"}]}
    assert strip_water_talk(s, case) == "Ryan is alone at 4173 Elgin Street with a sprained ankle."
    flood = {"water_level": "knee", "transcript": [{"role": "user", "message": "water is at my knees"}]}
    assert strip_water_talk("Water at knee level. Two people.", flood) == "Water at knee level. Two people."


def test_caller_saying_no_water_still_drops_water_sentences():
    from app.cases import strip_water_talk
    case = {"water_level": "none", "transcript": [{"role": "user", "message": "Uh, there's no water."}]}
    assert strip_water_talk("Ryan sprained his ankle. He is alone and there is no water involved.", case) \
        == "Ryan sprained his ankle."
