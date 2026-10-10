"""Surge mode: replays a Harvey-scale wave of calls across Houston.

Simulated cases go through the same scoring as real ones, are stored with
source='simulated', use fake 555 numbers (so no callback is ever placed), and
are removed by /api/demo/reset.
"""

import asyncio
import logging
import random

from . import db
from .areas import AREAS
from .cases import _with_score, publish
from .realtime import hub

log = logging.getLogger("lifeline.simulator")

_running: asyncio.Task | None = None

LANGUAGES = [("English", 52), ("Spanish", 30), ("Vietnamese", 7), ("Chinese", 4), ("Arabic", 4), ("Urdu", 3)]

NAMES = {
    "English": ["James", "Linda", "Marcus", "Tasha", "Robert", "Karen", "DeShawn", "Emily", "Gary", "Brenda"],
    "Spanish": ["María", "José", "Guadalupe", "Luis", "Rosa", "Carlos", "Ana", "Miguel", "Lucía", "Jorge"],
    "Vietnamese": ["Nguyễn Lan", "Trần Minh", "Phạm Hoa", "Lê Tuấn"],
    "Chinese": ["Wang Fang", "Li Wei", "Zhang Min"],
    "Arabic": ["Fatima", "Omar", "Layla", "Yusuf"],
    "Urdu": ["Ayesha", "Imran", "Sana", "Bilal"],
}

LEVEL_WORDS = {
    "Spanish": {"ankle": "los tobillos", "knee": "las rodillas", "waist": "la cintura", "chest": "el pecho", "roof": "el techo"},
    "Vietnamese": {"ankle": "mắt cá chân", "knee": "đầu gối", "waist": "thắt lưng", "chest": "ngực", "roof": "mái nhà"},
    "Chinese": {"ankle": "脚踝", "knee": "膝盖", "waist": "腰", "chest": "胸口", "roof": "屋顶"},
    "Arabic": {"ankle": "الكاحل", "knee": "الركبة", "waist": "الخصر", "chest": "الصدر", "roof": "السطح"},
    "Urdu": {"ankle": "ٹخنوں", "knee": "گھٹنوں", "waist": "کمر", "chest": "سینے", "roof": "چھت"},
}

TEMPLATES = {
    "English": "I'm at {addr}. There are {n} of us here. The water is up to my {level}{rising}.",
    "Spanish": "Estoy en {addr}. Somos {n} aquí. El agua me llega a {level}{rising}.",
    "Vietnamese": "Tôi ở {addr}. Chúng tôi có {n} người. Nước đã lên tới {level}{rising}.",
    "Chinese": "我在{addr}。我们这里有{n}个人。水已经到{level}了{rising}。",
    "Arabic": "أنا في {addr}. نحن {n} أشخاص هنا. الماء وصل إلى {level}{rising}.",
    "Urdu": "میں {addr} پر ہوں۔ ہم یہاں {n} لوگ ہیں۔ پانی {level} تک آ گیا ہے{rising}۔",
}

RISING = {
    "English": " and it's still rising", "Spanish": " y sigue subiendo", "Vietnamese": " và vẫn đang dâng",
    "Chinese": "，还在涨", "Arabic": " وما زال يرتفع", "Urdu": " اور بڑھ رہا ہے",
}

WATER_WEIGHTS = [("ankle", 10), ("knee", 24), ("waist", 32), ("chest", 23), ("roof", 11)]
VULNERABLE = [("elderly", 18), ("baby", 8), ("child", 12), ("disabled", 6), ("pregnant", 3)]
MEDICAL = [("insulin", 6), ("oxygen", 5), ("dialysis", 3), ("medication", 5)]


def _pick(weighted: list[tuple[str, int]]) -> str:
    items, weights = zip(*weighted)
    return random.choices(items, weights=weights, k=1)[0]


def _fake_case() -> dict:
    area = random.choices(AREAS, weights=[a["risk"] for a in AREAS], k=1)[0]
    language = _pick(LANGUAGES)
    address = f"{random.randint(100, 15999)} {random.choice(area['streets'])}"
    people = random.choices([1, 2, 3, 4, 5, 6, 8], weights=[18, 26, 20, 16, 10, 6, 4], k=1)[0]
    water = _pick(WATER_WEIGHTS)
    rising = random.random() < 0.55
    vulnerable = sorted({v for v, w in VULNERABLE if random.random() * 100 < w})
    medical = sorted({m for m, w in MEDICAL if random.random() * 100 < w})
    injuries = random.choice(["cut on leg from debris", "possible broken arm", "fell on stairs"]) \
        if random.random() < 0.07 else None
    life = random.random() < 0.035
    battery = random.choice([None, None, random.randint(3, 95)])

    level_word = water if language == "English" else LEVEL_WORDS[language][water]
    rising_word = RISING[language] if rising else ""
    line = TEMPLATES[language].format(addr=address, n=people, level=level_word, rising=rising_word)

    fields = {
        "source": "simulated",
        "phone": f"+1555{random.randint(1000000, 9999999)}",
        "caller_name": random.choice(NAMES[language]),
        "language": language,
        "address": address,
        "neighborhood": area["name"],
        "lat": area["lat"] + random.uniform(-0.018, 0.018),
        "lng": area["lng"] + random.uniform(-0.022, 0.022),
        "location_confidence": "high",
        "people_count": people,
        "water_level": water,
        "water_rising": rising,
        "vulnerable": vulnerable,
        "medical_needs": medical,
        "injuries": injuries,
        "life_threatening": life,
        "critical_reason": "Person unresponsive in rising water" if life else None,
        "battery_pct": battery,
        "transcript": [
            {"role": "agent", "message": "Lifeline emergency line. Are you or anyone with you in danger right now?", "call": "intake"},
            {"role": "user", "message": line, "call": "intake"},
        ],
        "enriched": False,
    }
    return _with_score(fields)


async def _run(count: int, seconds: float) -> None:
    await hub.broadcast({"type": "surge", "state": "started", "count": count, "seconds": seconds})
    # Arrivals ramp up then taper, like a real surge
    gaps = [random.expovariate(1.0) for _ in range(count)]
    scale = seconds / sum(gaps)
    try:
        for i, gap in enumerate(gaps):
            await asyncio.sleep(gap * scale)
            case = await db.insert_case(_fake_case())
            await db.add_call_event("simulated", case_id=case["id"], phone=case["phone"],
                                    area=case["neighborhood"], language=case["language"])
            data = await publish(case)
            if case.get("life_threatening"):
                await hub.broadcast({"type": "alert", "level": "critical", "case": data})
    finally:
        await hub.broadcast({"type": "surge", "state": "finished"})


def start(count: int = 300, seconds: float = 60) -> bool:
    global _running
    if _running and not _running.done():
        return False
    _running = asyncio.create_task(_run(count, seconds))
    return True


def running() -> bool:
    return bool(_running and not _running.done())
