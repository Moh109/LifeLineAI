r"""Run the grounding check (backend/app/grounding.py) on every existing case.

    .\backend\.venv\Scripts\python.exe scripts\ground_cases.py            # preview: show what would be cleared
    .\backend\.venv\Scripts\python.exe scripts\ground_cases.py --apply    # clear ungrounded details, flag for review

On the server: cd /opt/lifeline/backend && .venv/bin/python ../scripts/ground_cases.py [--apply]
Ungrounded critical_reason / injuries / medical_needs are cleared and the case gets needs_review.
Nothing is deleted. Open dashboards pick up changes on refresh.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import cases, db, grounding  # noqa: E402


async def main(apply: bool) -> None:
    await db.connect()
    rows = [dict(r) for r in await db.pool.fetch("select * from cases where source <> 'simulated' order by id")]
    flagged = 0
    for case in rows:
        changes = grounding.check(case)
        if not changes:
            continue
        flagged += 1
        cleared = {k: case.get(k) for k in changes if k not in {"needs_review", "review_reason"}}
        print(f"{cases.case_number(case['id'])}: not found in what the caller said -> clear {cleared}")
        if apply:
            await cases.ground(case["id"])
    print(f"\nchecked {len(rows)} cases, {flagged} "
          f"{'updated' if apply else 'would be updated (preview; add --apply to write)'}")
    await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
