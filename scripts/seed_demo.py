r"""Load a clean demo state for judging: 8 open cases across Houston flood neighborhoods.

    .\backend\.venv\Scripts\python.exe scripts\seed_demo.py --dry-run    # show the cases and their scores, touch nothing
    .\backend\.venv\Scripts\python.exe scripts\seed_demo.py              # asks before deleting ALL cases, then loads the demo set

Run in PowerShell from the project folder, about 30 minutes before judging.
It talks to the database in backend/.env, which is the same one the live server uses.
Every phone is a fake +1555 number, so nobody can be called. Refresh open dashboards afterwards.

The set: red/orange/yellow mix, one Spanish call with English translation, one "2 reports"
case, one "needs review" case, one non-flood emergency.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db  # noqa: E402
from app.areas import AREAS  # noqa: E402
from app.cases import _with_score, case_number  # noqa: E402
from app.scoring import label_for  # noqa: E402

AREA = {a["name"]: a for a in AREAS}


def turns(*pairs):
    return [{"role": r, "message": m, "call": "intake"} for r, m in pairs]


DEMO = [
    dict(area="Fifth Ward", dlat=0.002, dlng=-0.004, minutes=6, phone="+15550100001", caller_name="James Carter",
         language="English", address="2500 Lyons Ave, Houston", people_count=3, water_level="chest", water_rising=True,
         life_threatening=True, critical_reason="Neighbor unconscious after being pulled from the water",
         vulnerable=["elderly"], medical_needs=["oxygen"],
         notes="Trapped by flood water. Neighbor unconscious.",
         summary_en="Three people trapped at 2500 Lyons Ave with chest-deep rising water. A neighbor is unconscious after being pulled from the water; an elderly woman is on oxygen.",
         transcript=turns(("agent", "Lifeline emergency line. Is anyone not breathing, unconscious, or bleeding heavily?"),
                          ("user", "Yes, my neighbor is unconscious, we pulled him out of the water. Water's at my chest and rising."),
                          ("agent", "I've marked this as life-threatening for a human dispatcher. What's your address?"),
                          ("user", "2500 Lyons Avenue. Three of us, my grandmother is on oxygen."))),
    dict(area="Meyerland", dlat=-0.003, dlng=0.005, minutes=14, phone="+15550100002", caller_name="Linda Nguyen",
         language="English", address="5100 Jason St, Houston", people_count=4, water_level="roof", water_rising=True,
         vulnerable=["baby", "elderly"], notes="Trapped by flood water. On the roof.",
         summary_en="Four people including a baby and an elderly man are on the roof at 5100 Jason St. Water still rising.",
         transcript=turns(("agent", "Tell me what's happening."),
                          ("user", "We're on the roof, the water keeps rising. My baby and my father are with me. 5100 Jason Street."))),
    dict(area="Greenspoint", dlat=0.004, dlng=0.003, minutes=22, phone="+15550100003", caller_name="María López",
         language="Spanish", address="210 Greens Rd, Houston", people_count=5, water_level="waist", water_rising=True,
         vulnerable=["child", "elderly"], medical_needs=["insulin"], notes="Trapped by flood water",
         summary_en="Five people, including two children and an elderly father with diabetes who needs insulin, are trapped at 210 Greens Rd with waist-deep rising water.",
         transcript=turns(("agent", "Línea de emergencia Lifeline. Cuénteme qué está pasando."),
                          ("user", "Estamos atrapados, el agua nos llega a la cintura y sigue subiendo. Mi papá tiene diabetes y necesita su insulina."),
                          ("agent", "¿Cuál es su dirección?"),
                          ("user", "210 Greens Road. Somos cinco, con mis dos niños.")),
         transcript_en=[{"role": "agent", "message": "Lifeline emergency line. Tell me what's happening."},
                        {"role": "caller", "message": "We're trapped, the water is up to our waists and still rising. My dad has diabetes and needs his insulin."},
                        {"role": "agent", "message": "What is your address?"},
                        {"role": "caller", "message": "210 Greens Road. There are five of us, with my two kids."}]),
    dict(area="Kashmere Gardens", dlat=-0.002, dlng=-0.003, minutes=31, phone="+15550100004", caller_name="Dorothy Wells",
         language="English", address="3300 Lockwood Dr, Houston", people_count=1, water_level="knee",
         vulnerable=["elderly", "disabled"], notes="Trapped by flood water. Uses a wheelchair, alone.",
         summary_en="An elderly woman who uses a wheelchair is alone at 3300 Lockwood Dr with knee-deep water in the house. She cannot leave on her own.",
         transcript=turns(("agent", "Tell me what's happening."),
                          ("user", "I'm in a wheelchair and I'm alone. The water is at my knees in the living room. 3300 Lockwood Drive."))),
    dict(area="Sunnyside", dlat=0.003, dlng=0.002, minutes=38, phone="+15550100005", caller_name="Marcus Hill",
         language="English", address="4200 Bellfort Ave, Houston", people_count=3, water_level="knee", water_rising=True,
         call_count=2, notes="Trapped by flood water. Reported by 2 sources.",
         summary_en="Three people at 4200 Bellfort Ave with knee-deep rising water. Reported by 2 sources.",
         transcript=turns(("user", "Water's at our knees and rising, 4200 Bellfort. Three of us."),
                          ("user", "Calling again, it's still rising."))),
    dict(area="Kingwood", dlat=-0.004, dlng=0.004, minutes=17, phone="+15550100006", caller_name="Rachel Kim",
         language="English", address="2400 Kingwood Dr, Kingwood", people_count=3, water_level="waist", battery_pct=8,
         notes="Trapped by flood water",
         summary_en="Three people at 2400 Kingwood Dr with waist-deep water. Caller's phone is at 8%.",
         transcript=turns(("user", "Water's up to my waist at 2400 Kingwood Drive, three of us. My phone is at 8 percent."))),
    dict(area="East End", dlat=0.001, dlng=0.004, minutes=9, phone="+15550100007", caller_name="Omar Haddad",
         language="English", address="7000 Harrisburg Blvd, Houston", people_count=2, water_level="none",
         injuries="Burns on both hands", notes="House fire",
         summary_en="House fire at 7000 Harrisburg Blvd. Two people out of the house; one has burns on both hands.",
         transcript=turns(("user", "There's a fire in my house, we got out but my brother burned both hands. 7000 Harrisburg."))),
    dict(area="Sharpstown", dlat=0.002, dlng=-0.002, minutes=26, phone="+15550100008", caller_name="Unknown caller",
         language="English", address="6800 Bellaire Blvd, Houston", people_count=60, water_level="ankle",
         notes="Trapped by flood water. Caller claims 60 people at a strip mall.",
         summary_en="Caller says 60 people are stuck at a strip mall at 6800 Bellaire Blvd with ankle-deep water. Count unverified.",
         transcript=turns(("user", "There's like sixty people stuck here at the mall on Bellaire, the water's at our ankles."))),
]


def build(spec: dict, now: datetime) -> dict:
    s = dict(spec)
    area = AREA[s.pop("area")]
    dlat, dlng, minutes = s.pop("dlat"), s.pop("dlng"), s.pop("minutes")
    fields = dict(source="call", lat=area["lat"] + dlat, lng=area["lng"] + dlng, location_confidence="high",
                  neighborhood=area["name"], enriched=True, status="open",
                  created_at=now - timedelta(minutes=minutes), vulnerable=[], medical_needs=[])
    fields.update(s)
    summary = fields["summary_en"]
    _with_score(fields)
    fields["summary_en"] = summary  # keep the hand-written English summary
    return fields


async def main(dry_run: bool, yes: bool) -> None:
    now = datetime.now(timezone.utc)
    cases = [build(s, now) for s in DEMO]
    for c in cases:
        flags = [f for f, on in [("Spanish", c["language"] == "Spanish"), (f"{c.get('call_count', 1)} reports", c.get("call_count", 1) > 1),
                                 ("needs review", c.get("needs_review")), ("life-threatening", c.get("life_threatening"))] if on]
        print(f"  {c['base_priority']:3} {label_for(c['base_priority']):6} {c['neighborhood']:17} {c['address']:32} {', '.join(flags)}")
    if dry_run:
        print("\nDry run: nothing changed.")
        return

    await db.connect()
    existing = await db.pool.fetchval("select count(*) from cases")
    if existing and not yes:
        answer = input(f"\nThis DELETES all {existing} cases and call history in the database, then loads the "
                       f"{len(cases)} demo cases. Type CLEAR to continue: ")
        if answer.strip() != "CLEAR":
            print("Cancelled. Nothing changed.")
            await db.close()
            return
    removed = await db.delete_cases(None)
    for c in cases:
        row = await db.insert_case(c)
        await db.add_call_event("inbound", case_id=row["id"], phone=row["phone"], area=row["neighborhood"],
                                language=row["language"])
        print(f"  added {case_number(row['id'])} {row['address']}")
    await db.close()
    print(f"\nRemoved {len(removed)} old cases, loaded {len(cases)} demo cases. Refresh the dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="show the demo cases, change nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.yes))
