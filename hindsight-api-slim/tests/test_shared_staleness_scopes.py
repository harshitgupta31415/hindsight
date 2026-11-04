"""Shared tag filters still answer each page's own freshness question."""

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from hindsight_api.engine.memories.base import MemoryScopeWatermark
from hindsight_api.engine.memories.pg.reads import any_memory_updated_since, any_memory_updated_since_batch


@pytest.mark.parametrize("tags_match", ["all_strict", "any_strict", "exact"])
async def test_shared_scope_matches_single_checks(pg0_db_url, tags_match):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    conn = await asyncpg.connect(pg0_db_url)
    try:
        await conn.execute("""
            CREATE TEMP TABLE memory_units (
                bank_id text, fact_type text, tags varchar[], updated_at timestamptz
            );
            CREATE INDEX ON memory_units USING gin(tags);
            CREATE INDEX ON memory_units(bank_id, updated_at DESC);
        """)
        await conn.executemany(
            "INSERT INTO memory_units VALUES ($1, $2, $3, $4)",
            [
                ("bank", "observation", ["cold"], now - timedelta(days=1)),
                ("bank", "observation", ["shared"], now),
                ("bank", "observation", ["shared", "extra"], now + timedelta(seconds=1)),
                ("bank", "experience", ["shared"], now + timedelta(seconds=2)),
                ("other-bank", "observation", ["shared"], now + timedelta(seconds=3)),
                *[("bank", "observation", ["other"], now - timedelta(seconds=i + 1)) for i in range(64)],
            ],
        )
        cases = [
            ("older-page", ["shared"], ["observation"], now - timedelta(seconds=1)),
            ("cold-match", ["cold"], ["observation"], now - timedelta(days=2)),
            ("equal-watermark", ["shared"], ["observation"], now),
            ("cold-fresh", ["cold"], ["observation"], now),
            ("missing-1", ["missing"], None, now - timedelta(days=2)),
            ("missing-2", ["missing"], [], now),
            ("experience", ["shared"], ["experience"], now),
        ]
        scopes = [
            MemoryScopeWatermark(key=key, tags=tags, fact_types=fact_types, tags_match=tags_match, since=since)
            for key, tags, fact_types, since in cases
        ]

        def table(name):
            return f"pg_temp.{name}"

        actual = await any_memory_updated_since_batch(conn=conn, fq_table=table, bank_id="bank", scopes=scopes)
        expected = {
            scope.key: await any_memory_updated_since(
                conn=conn,
                fq_table=table,
                bank_id="bank",
                since=scope.since,
                tags=scope.tags,
                fact_types=scope.fact_types,
                tags_match=scope.tags_match,
            )
            for scope in scopes
        }
        assert (
            actual
            == expected
            == {
                "older-page": True,
                "cold-match": True,
                "equal-watermark": tags_match != "exact",
                "cold-fresh": False,
                "missing-1": False,
                "missing-2": False,
                "experience": True,
            }
        )
    finally:
        await conn.close()
