r"""Write the sample data for the static demo site (frontend/src/demo/*.json).

    python scripts/build_static_demo.py           # rewrite the JSON files
    python scripts/build_static_demo.py --check   # fail if the JSON no longer matches the scoring rules

Run from the project folder with the backend venv active (no .env or database needed).
Every case goes through the real scoring (`cases._with_score`) and the real phone masking
(`cases.mask_phone`), so the demo shows exactly what the live system would. Nothing here comes
from the database: callers are made up, phones are fake +1555 numbers, and addresses are
block-level ("7300 block of ...") so none of them points at a real home.
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.areas import AREAS  # noqa: E402
from app.cases import _with_score, case_number, mask_phone  # noqa: E402
from app.scoring import label_for  # noqa: E402
from app import simulator  # noqa: E402

OUT_DIR = ROOT / "frontend" / "src" / "demo"
AREA = {a["name"]: a for a in AREAS}
SURGE_COUNT = 300
FIRST_ID = 401  # case numbers start at LF-1401


def turns(*pairs):
    return [{"role": r, "message": m, "call": "intake"} for r, m in pairs]


# minutes = how long ago the call came in, relative to when the page opens
DEMO = [
    dict(area="Meyerland", dlat=-0.003, dlng=0.004, minutes=4, phone="+15550100101", caller_name="Denise",
         language="English", address="7300 block of Endicott Ln", people_count=4, water_level="roof", water_rising=True,
         vulnerable=["elderly", "baby"], medical_needs=["oxygen"], battery_pct=12,
         notes="Family on the roof. Grandfather on oxygen, power is out.",
         summary_en="Four people on the roof in the 7300 block of Endicott Ln, water still rising. A baby and an elderly man who uses oxygen; the power is out. Phone at 12%.",
         transcript=turns(("agent", "Lifeline emergency line. Are you or anyone with you in danger right now?"),
                          ("user", "We had to climb onto the roof, the water is still coming up. It's me, my husband, our baby and my dad."),
                          ("agent", "I'm getting help to you. Does anyone need medicine or a machine to breathe?"),
                          ("user", "My dad is on oxygen and the power's been out for two hours. My phone is at twelve percent."),
                          ("agent", "Understood. Stay on the roof and keep your phone off when you're not using it."))),
    dict(area="Fifth Ward", dlat=0.002, dlng=-0.004, minutes=7, phone="+15550100102", caller_name="Terrence",
         language="English", address="3100 block of Lyons Ave", people_count=2, water_level="chest", water_rising=True,
         life_threatening=True, critical_reason="Neighbor pulled from the water, not responding",
         notes="Caller pulled a neighbor out of the water. Neighbor not responding.",
         summary_en="Two people in the 3100 block of Lyons Ave with chest-deep rising water. The caller pulled a neighbor out of the water and he is not responding.",
         transcript=turns(("agent", "Lifeline emergency line. Is anyone not breathing, unconscious, or bleeding heavily?"),
                          ("user", "My neighbor, I pulled him out of the water and he's not answering me. The water's at my chest."),
                          ("agent", "I've marked this as life-threatening for a human dispatcher right now. Is he breathing?"),
                          ("user", "I think so, barely. Please hurry."))),
    dict(area="Greenspoint", dlat=0.004, dlng=0.003, minutes=18, phone="+15550100103", caller_name="Guadalupe",
         language="Spanish", address="400 block of Greens Rd", people_count=5, water_level="waist", water_rising=True,
         vulnerable=["child", "elderly"], medical_needs=["insulin"],
         notes="Five people, two kids. Father is diabetic and his insulin is running out.",
         summary_en="Five people in the 400 block of Greens Rd with waist-deep rising water, including two children and an elderly father who needs insulin.",
         transcript=turns(("agent", "Línea de emergencia Lifeline. Cuénteme qué está pasando."),
                          ("user", "Estamos atrapados, el agua nos llega a la cintura y sigue subiendo. Mi papá es diabético y casi no le queda insulina."),
                          ("agent", "¿Cuántas personas están con usted?"),
                          ("user", "Somos cinco, con mis dos niños.")),
         transcript_en=[{"role": "agent", "message": "Lifeline emergency line. Tell me what's happening."},
                        {"role": "caller", "message": "We're trapped, the water is up to our waists and still rising. My dad is diabetic and he's almost out of insulin."},
                        {"role": "agent", "message": "How many people are with you?"},
                        {"role": "caller", "message": "There are five of us, with my two kids."}]),
    dict(area="Kashmere Gardens", dlat=-0.002, dlng=-0.003, minutes=26, phone="+15550100104", caller_name="Evelyn",
         language="English", address="4800 block of Lockwood Dr", people_count=1, water_level="knee", age="81",
         vulnerable=["disabled"], notes="Uses a wheelchair, alone in the house.",
         summary_en="An 81-year-old woman who uses a wheelchair is alone in the 4800 block of Lockwood Dr with knee-deep water inside. She can't leave on her own.",
         transcript=turns(("agent", "Lifeline emergency line. Tell me what's happening."),
                          ("user", "I'm in my wheelchair and I'm by myself. There's water up to my knees in the living room."),
                          ("agent", "Can you get to a higher spot in the house?"),
                          ("user", "No, I can't get out of the chair on my own."))),
    dict(area="Sunnyside", dlat=0.003, dlng=0.002, minutes=34, phone="+15550100105", caller_name="Andre",
         language="English", address="3700 block of Bellfort Ave", people_count=3, water_level="knee", water_rising=True,
         call_count=2, notes="Called twice. Water rising.",
         memory=["[Oct 21 14:02 UTC] 3 people at 3700 block of Bellfort Ave. Water at knee and rising.",
                 "[Oct 21 14:19 UTC] Called again: water still rising, no team yet."],
         summary_en="Three people in the 3700 block of Bellfort Ave with knee-deep rising water. Second call from this number.",
         transcript=turns(("user", "Water's at our knees and it's rising. Three of us, 3700 block of Bellfort."),
                          ("agent", "I have your request. Has anything changed since you last called?"),
                          ("user", "It's still coming up. Nobody's here yet."))),
    dict(area="Alief", dlat=-0.001, dlng=0.002, minutes=12, phone="+15550100106", caller_name="Lan",
         language="Vietnamese", address="11200 block of Bissonnet St", people_count=2, water_level="waist",
         vulnerable=["elderly"], notes="Elderly couple, water inside the house.",
         summary_en="An elderly couple in the 11200 block of Bissonnet St with waist-deep water inside the house.",
         transcript=turns(("agent", "Đường dây khẩn cấp Lifeline. Chuyện gì đang xảy ra?"),
                          ("user", "Nước đã lên tới thắt lưng trong nhà. Tôi và chồng tôi, cả hai đều đã già.")),
         transcript_en=[{"role": "agent", "message": "Lifeline emergency line. What is happening?"},
                        {"role": "caller", "message": "The water is up to our waists inside the house. My husband and me, we're both old."}]),
    dict(area="Kingwood", dlat=-0.004, dlng=0.004, minutes=21, phone="+15550100107", caller_name="Rachel",
         language="English", landmark="the apartments behind the Kingwood Dr shopping center", people_count=3,
         water_level="ankle", location_confidence="approximate",
         notes="Couldn't give a street address. Ankle-deep water in the parking lot.",
         summary_en="Three people at an apartment complex off Kingwood Dr with ankle-deep water. No street address yet, so the pin marks the neighborhood.",
         transcript=turns(("user", "We're at the apartments behind the shopping center on Kingwood Drive. Water's at our ankles in the parking lot."),
                          ("agent", "Do you know the street number or the name of the complex?"),
                          ("user", "No, sorry, we just moved here."))),
    dict(area="Sharpstown", dlat=0.002, dlng=-0.002, minutes=29, phone="+15550100108", caller_name="Unknown caller",
         language="English", landmark="strip mall on Bellaire Blvd near Fondren Rd", people_count=60, water_level="ankle",
         notes="Caller says 60 people at a strip mall. Count unverified.",
         summary_en="Caller says about 60 people are stuck at a strip mall on Bellaire Blvd near Fondren Rd with ankle-deep water. Count not verified.",
         transcript=turns(("user", "There's like sixty people stuck at the strip mall on Bellaire by Fondren, the water's at our ankles."))),
    dict(area="East End", dlat=0.001, dlng=0.004, minutes=41, phone="+15550100109", caller_name="Omar",
         language="English", address="6900 block of Harrisburg Blvd", people_count=2, water_level="none",
         injuries="burns on both hands", notes="House fire, not flood related.",
         status="assigned", unit="High-water truck T-7", eta_minutes=12, assigned_minutes=8,
         summary_en="House fire in the 6900 block of Harrisburg Blvd. Two people got out; one has burns on both hands.",
         transcript=turns(("user", "There's a fire in my house, we got out but my brother burned both his hands."),
                          ("agent", "Is anyone still inside?"),
                          ("user", "No, we're both outside on the sidewalk."))),
    dict(area="Bear Creek", dlat=0.003, dlng=-0.003, minutes=55, phone="+15550100110", caller_name="Hannah",
         language="English", address="16000 block of Clay Rd", people_count=4, water_level="chest", water_rising=True,
         vulnerable=["child"], pets="2 dogs", status="assigned", unit="Boat B-2", eta_minutes=20, assigned_minutes=15,
         summary_en="Four people including a child in the 16000 block of Clay Rd with chest-deep rising water. Two dogs with them.",
         transcript=turns(("user", "The water is up to my chest downstairs, we went up to the second floor. My son is six. We have two dogs."),
                          ("agent", "Stay upstairs. A team is being assigned."))),
    dict(area="Clear Lake", dlat=-0.002, dlng=0.003, minutes=95, phone="+15550100111", caller_name="Victor",
         language="English", address="1500 block of Bay Area Blvd", people_count=2, water_level="waist",
         status="rescued", unit="Boat B-1", eta_minutes=15, assigned_minutes=70, resolved_minutes=40,
         summary_en="Two adults in the 1500 block of Bay Area Blvd with waist-deep water. Picked up by Boat B-1.",
         transcript=turns(("user", "My wife and I are stuck, the water's at our waist and the car is gone."))),
]

TIMING_KEYS = ("minutes", "assigned_minutes", "resolved_minutes")


def build(spec: dict, case_id: int) -> dict:
    s = dict(spec)
    area = AREA[s.pop("area")]
    dlat, dlng = s.pop("dlat"), s.pop("dlng")
    timing = {k: s.pop(k) for k in TIMING_KEYS if k in s}
    memory = s.pop("memory", [])
    phone = s.pop("phone")
    approximate = s.get("location_confidence") == "approximate"
    fields = dict(source="call", neighborhood=area["name"], enriched=True, status="open", location_confidence="high",
                  lat=area["lat"] + (0 if approximate else dlat), lng=area["lng"] + (0 if approximate else dlng),
                  vulnerable=[], medical_needs=[], call_count=1)
    fields.update(s)
    summary = fields["summary_en"]
    _with_score(fields)
    fields["summary_en"] = summary  # keep the hand-written English summary, like seed_demo.py
    return {"id": case_id, "case_number": case_number(case_id), **fields, "phone": mask_phone(phone),
            "can_call_back": False, "recordings": [], "memory": memory,
            **{f"{k}_ago" if k != "minutes" else "minutes_ago": v for k, v in timing.items()}}


def block_address(address: str) -> str:
    """'7321 Endicott Ln' -> '7300 block of Endicott Ln': never a real house number."""
    number, street = address.split(" ", 1)
    return f"{int(number) // 100 * 100} block of {street}"


def build_surge(case_id: int) -> dict:
    fields = simulator._fake_case()
    exact = fields["address"]
    fields["address"] = block_address(exact)
    for line in fields["transcript"]:
        line["message"] = line["message"].replace(exact, fields["address"])
    fields["summary_en"] = fields["summary_en"].replace(exact, fields["address"])
    phone = fields.pop("phone")
    return {"id": case_id, "case_number": case_number(case_id), **fields, "status": "open", "call_count": 1,
            "phone": mask_phone(phone), "can_call_back": False, "recordings": [], "memory": []}


def generate() -> tuple[list[dict], list[dict]]:
    random.seed(20261011)  # same surge every time
    cases = [build(spec, FIRST_ID + i) for i, spec in enumerate(DEMO)]
    surge = [build_surge(2000 + i) for i in range(SURGE_COUNT)]  # ids re-numbered by the dashboard per run
    return cases, surge


def dump(data, compact: bool = False) -> str:
    if compact:  # the surge file is only loaded when someone presses the button: keep it small
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(check: bool) -> None:
    cases, surge = generate()
    files = {OUT_DIR / "cases.json": dump(cases), OUT_DIR / "surge.json": dump(surge, compact=True)}
    for c in cases:
        print(f"  {c['case_number']} {c['base_priority']:3} {label_for(c['base_priority']):6} {c['status']:8} "
              f"{c['neighborhood']:17} {c.get('address') or c.get('landmark')}")
    if check:
        stale = [p.name for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            sys.exit(f"Out of date: {', '.join(stale)}. Run scripts/build_static_demo.py")
        print("Demo data matches the scoring rules.")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify the JSON instead of writing it")
    main(parser.parse_args().check)
