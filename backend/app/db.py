"""Database access. Works on Tiger Data (TimescaleDB) and on plain Postgres.

On Tiger Data, call_events becomes a hypertable with a real-time continuous
aggregate (calls_per_minute) that powers the surge history. On plain Postgres
the same queries fall back to date_bin / date_trunc.
"""

import json
import logging
from typing import Any

import asyncpg

from . import config

log = logging.getLogger("lifeline.db")

pool: asyncpg.Pool | None = None
HAS_TIMESCALE = False

SCHEMA = """
create table if not exists cases (
  id bigserial primary key,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  source text not null default 'call',
  phone text,
  conversation_ids text[] not null default '{}',
  caller_name text,
  language text,
  address text,
  landmark text,
  neighborhood text,
  lat double precision,
  lng double precision,
  location_confidence text not null default 'none',
  people_count int,
  water_level text,
  water_rising boolean,
  vulnerable text[] not null default '{}',
  medical_needs text[] not null default '{}',
  injuries text,
  life_threatening boolean not null default false,
  critical_reason text,
  battery_pct int,
  pets text,
  notes text,
  summary_en text,
  base_priority int not null default 0,
  reasons jsonb not null default '[]',
  status text not null default 'open',
  unit text,
  eta_minutes int,
  assigned_at timestamptz,
  resolved_at timestamptz,
  callback_status text,
  call_count int not null default 1,
  transcript jsonb not null default '[]',
  transcript_en jsonb,
  enriched boolean not null default false
);
create index if not exists cases_phone_idx on cases (phone);
create index if not exists cases_status_idx on cases (status);
create index if not exists cases_conv_idx on cases using gin (conversation_ids);

create table if not exists call_events (
  time timestamptz not null default now(),
  case_id bigint,
  phone text,
  kind text not null,
  area text,
  language text,
  duration_s int
);
create index if not exists call_events_time_idx on call_events (time desc);
"""

CASE_COLUMNS = {
    "source", "phone", "conversation_ids", "caller_name", "language", "address", "landmark",
    "neighborhood", "lat", "lng", "location_confidence", "people_count", "water_level",
    "water_rising", "vulnerable", "medical_needs", "injuries", "life_threatening",
    "critical_reason", "battery_pct", "pets", "notes", "summary_en", "base_priority",
    "reasons", "status", "unit", "eta_minutes", "assigned_at", "resolved_at",
    "callback_status", "call_count", "transcript", "transcript_en", "enriched",
    "created_at",
}


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect() -> None:
    global pool, HAS_TIMESCALE
    # Close idle connections after 60s: the cloud DB / network silently drops idle ones, which broke the next query
    pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10, init=_init_connection,
                                     max_inactive_connection_lifetime=60)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
        HAS_TIMESCALE = await _setup_timescale(conn)
    log.info("Database ready (timescale=%s)", HAS_TIMESCALE)


async def _setup_timescale(conn: asyncpg.Connection) -> bool:
    try:
        await conn.execute("create extension if not exists timescaledb")
    except Exception:
        pass
    installed = await conn.fetchval("select 1 from pg_extension where extname = 'timescaledb'")
    if not installed:
        log.info("TimescaleDB not available; using plain Postgres queries")
        return False

    for stmt in (
        "select create_hypertable('call_events', by_range('time'), if_not_exists => true, migrate_data => true)",
        "select create_hypertable('call_events', 'time', if_not_exists => true, migrate_data => true)",
    ):
        try:
            await conn.execute(stmt)
            break
        except Exception as exc:  # older/newer syntax
            log.debug("hypertable attempt failed: %s", exc)

    try:
        await conn.execute(
            """
            create materialized view if not exists calls_per_minute
            with (timescaledb.continuous, timescaledb.materialized_only = false) as
            select time_bucket('1 minute', time) as minute, kind, count(*) as calls
            from call_events
            group by minute, kind
            with no data
            """
        )
        await conn.execute(
            """
            select add_continuous_aggregate_policy('calls_per_minute',
              start_offset => interval '1 day',
              end_offset => interval '1 minute',
              schedule_interval => interval '1 minute',
              if_not_exists => true)
            """
        )
    except Exception as exc:
        log.warning("Continuous aggregate setup skipped: %s", exc)
    return True


async def close() -> None:
    if pool:
        await pool.close()


# ---------- cases ----------

async def get_case(case_id: int) -> dict | None:
    row = await pool.fetchrow("select * from cases where id = $1", case_id)
    return dict(row) if row else None


async def find_open_case_by_phone(phone: str) -> dict | None:
    if not phone:
        return None
    row = await pool.fetchrow(
        "select * from cases where phone = $1 and status in ('open','assigned') order by updated_at desc limit 1",
        phone,
    )
    return dict(row) if row else None


async def find_latest_case_by_phone(phone: str) -> dict | None:
    if not phone:
        return None
    row = await pool.fetchrow("select * from cases where phone = $1 order by updated_at desc limit 1", phone)
    return dict(row) if row else None


async def find_case_by_conversation(conversation_id: str) -> dict | None:
    if not conversation_id:
        return None
    row = await pool.fetchrow(
        "select * from cases where $1 = any(conversation_ids) order by updated_at desc limit 1",
        conversation_id,
    )
    return dict(row) if row else None


async def insert_case(fields: dict[str, Any]) -> dict:
    cols = [c for c in fields if c in CASE_COLUMNS]
    placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    sql = f"insert into cases ({', '.join(cols)}) values ({placeholders}) returning *"
    row = await pool.fetchrow(sql, *[fields[c] for c in cols])
    return dict(row)


async def update_case(case_id: int, fields: dict[str, Any]) -> dict | None:
    cols = [c for c in fields if c in CASE_COLUMNS]
    if not cols:
        return await get_case(case_id)
    sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(cols, start=2))
    sql = f"update cases set {sets}, updated_at = now() where id = $1 returning *"
    row = await pool.fetchrow(sql, case_id, *[fields[c] for c in cols])
    return dict(row) if row else None


async def list_cases(include_closed: bool = False, limit: int = 1000) -> list[dict]:
    if include_closed:
        rows = await pool.fetch("select * from cases order by created_at desc limit $1", limit)
    else:
        rows = await pool.fetch(
            """
            select * from cases
            where status in ('open','assigned')
               or (status in ('rescued','closed') and resolved_at > now() - interval '2 hours')
            order by created_at desc limit $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def delete_cases(source: str | None = None) -> list[int]:
    if source:
        rows = await pool.fetch("delete from cases where source = $1 returning id", source)
        await pool.execute("delete from call_events where kind = $1", source)
    else:
        rows = await pool.fetch("delete from cases returning id")
        await pool.execute("delete from call_events")
    return [r["id"] for r in rows]


# ---------- call events ----------

async def add_call_event(kind: str, case_id: int | None = None, phone: str | None = None,
                         area: str | None = None, language: str | None = None,
                         duration_s: int | None = None) -> None:
    await pool.execute(
        "insert into call_events (case_id, phone, kind, area, language, duration_s) values ($1,$2,$3,$4,$5,$6)",
        case_id, phone, kind, area, language, duration_s,
    )


async def stats() -> dict:
    bucket = "time_bucket('15 seconds', time)" if HAS_TIMESCALE else \
        "date_bin('15 seconds', time, timestamptz '2000-01-01')"
    series_rows = await pool.fetch(
        f"""
        select {bucket} as bucket, count(*) as calls
        from call_events
        where time > now() - interval '10 minutes' and kind <> 'callback'
        group by bucket order by bucket
        """
    )
    last_minute = await pool.fetchval(
        "select count(*) from call_events where time > now() - interval '60 seconds' and kind <> 'callback'"
    )
    status_rows = await pool.fetch(
        "select status, count(*) as n from cases where status in ('open','assigned') group by status"
    )
    rescued_recent = await pool.fetchval(
        "select count(*) from cases where status = 'rescued' and resolved_at > now() - interval '24 hours'"
    )
    wait = await pool.fetchval(
        "select coalesce(avg(extract(epoch from now() - created_at)) / 60, 0) from cases where status = 'open'"
    )
    lang_rows = await pool.fetch(
        """
        select coalesce(nullif(language,''),'Unknown') as language, count(*) as n
        from cases where status in ('open','assigned')
        group by 1 order by n desc limit 6
        """
    )

    per_minute = []
    if HAS_TIMESCALE:
        try:
            rows = await pool.fetch(
                """
                select minute, sum(calls)::int as calls from calls_per_minute
                where minute > now() - interval '60 minutes' and kind <> 'callback'
                group by minute order by minute
                """
            )
            per_minute = [{"minute": r["minute"].isoformat(), "calls": r["calls"]} for r in rows]
        except Exception as exc:
            log.debug("cagg query failed: %s", exc)

    return {
        "series": [{"bucket": r["bucket"].isoformat(), "calls": r["calls"]} for r in series_rows],
        "calls_last_minute": last_minute or 0,
        "open": next((r["n"] for r in status_rows if r["status"] == "open"), 0),
        "assigned": next((r["n"] for r in status_rows if r["status"] == "assigned"), 0),
        "rescued_24h": rescued_recent or 0,
        "avg_wait_min": round(float(wait or 0), 1),
        "languages": [{"language": r["language"], "n": r["n"]} for r in lang_rows],
        "per_minute": per_minute,
        "timescale": HAS_TIMESCALE,
    }
