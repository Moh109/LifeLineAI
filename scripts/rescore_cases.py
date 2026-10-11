"""Re-score every case with the current rules in backend/app/scoring.py.

    python scripts/rescore_cases.py            # preview: show what would change
    python scripts/rescore_cases.py --apply    # write the new scores

Run with the backend venv (backend\\.venv\\Scripts\\python.exe). Only scores, reasons and review
flags change; nothing is deleted and existing review flags are never cleared.
Open dashboards pick up the new scores on refresh.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db  # noqa: E402
from app.cases import INCOMING_KEYS, _with_score, case_number  # noqa: E402


async def main(apply: bool) -> None:
    await db.connect()
    rows = [dict(r) for r in await db.pool.fetch("select * from cases order by id")]
    changed = 0
    for case in rows:
        fields = {k: case.get(k) for k in INCOMING_KEYS}
        fields.update(enriched=case.get("enriched"), neighborhood=case.get("neighborhood"),
                      location_confidence=case.get("location_confidence"))
        _with_score(fields, context=case)
        update = {"base_priority": fields["base_priority"], "reasons": fields["reasons"]}
        if not case.get("enriched"):
            update["summary_en"] = fields["summary_en"]
        if fields.get("needs_review") and not case.get("needs_review"):
            update.update(needs_review=True, review_reason=fields["review_reason"])
        if all(case.get(k) == v for k, v in update.items()):
            continue
        changed += 1
        if case["source"] != "simulated" or changed <= 15:
            print(f"{case_number(case['id'])} ({case['source']}): {case['base_priority']} -> {update['base_priority']}"
                  + ("  [needs review]" if update.get("needs_review") else ""))
        if apply:
            await db.update_case(case["id"], update)
    print(f"\n{changed} of {len(rows)} cases {'updated' if apply else 'would change (preview; add --apply to write)'}")
    await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
