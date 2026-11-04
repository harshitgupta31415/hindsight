"""Scoped entity name searches keep the visible mention and inheritance rules."""

from uuid import UUID

import asyncpg

from hindsight_api.engine.memories.pg.curation import _list_entities_tag_filtered


async def test_scoped_entity_name_search(pg0_db_url):
    conn = await asyncpg.connect(pg0_db_url)
    try:
        await conn.execute("""
            CREATE TEMP TABLE entities (
                id uuid PRIMARY KEY, bank_id text, canonical_name text, entity_kind text, metadata jsonb
            );
            CREATE TEMP TABLE memory_units (
                id uuid PRIMARY KEY, bank_id text, fact_type text, occurred_start timestamptz,
                mentioned_at timestamptz, event_date timestamptz, tags varchar[], source_memory_ids uuid[]
            );
            CREATE TEMP TABLE unit_entities (unit_id uuid, entity_id uuid, PRIMARY KEY (unit_id, entity_id));
        """)
        visible, hidden, inherited, direct, hidden_observation = [UUID(int=i) for i in range(1, 6)]
        needle, other = UUID(int=10), UUID(int=11)
        await conn.executemany(
            "INSERT INTO entities VALUES ($1, 'bank', $2, 'regular', NULL)",
            [(needle, "needle entity"), (other, "other entity")],
        )
        await conn.executemany(
            "INSERT INTO memory_units VALUES ($1, 'bank', $2, NULL, NULL, now(), $3, $4)",
            [
                (visible, "world", ["team-a"], None),
                (hidden, "world", ["team-b"], None),
                (inherited, "observation", ["team-a"], [visible, hidden]),
                (direct, "observation", ["team-a"], [visible]),
                (hidden_observation, "observation", ["team-b"], [visible]),
            ],
        )
        await conn.executemany(
            "INSERT INTO unit_entities VALUES ($1, $2)", [(visible, needle), (hidden, needle), (direct, other)]
        )

        async def search(name, offset=0):
            return await _list_entities_tag_filtered(
                conn=conn,
                fq_table=lambda table: f"pg_temp.{table}",
                bank_id="bank",
                search=name,
                tags=["team-a"],
                tags_match="all_strict",
                tag_groups=None,
                limit=1,
                offset=offset,
            )

        narrow = await search("needle")
        broad = await search("entity")
        assert narrow["items"] == broad["items"]
        assert narrow["total"] == 1
        assert broad["total"] == 2
        assert narrow["items"][0]["id"] == str(needle)
        assert narrow["items"][0]["mention_count"] == 2
        assert (await search("entity", offset=1))["items"][0]["id"] == str(other)
        assert await search("needle", offset=1) == {"items": [], "total": 1, "limit": 1, "offset": 1}
        assert await search("missing") == {"items": [], "total": 0, "limit": 1, "offset": 0}

        await conn.execute("""
            INSERT INTO memory_units
            SELECT md5('hub-' || n)::uuid, 'bank', 'world', NULL, NULL, now(), '{team-a}', NULL
            FROM generate_series(1, 65) n;
        """)
        await conn.execute(
            "INSERT INTO unit_entities SELECT md5('hub-' || n)::uuid, $1 FROM generate_series(1, 65) n",
            needle,
        )
        assert (await search("needle"))["items"][0]["mention_count"] == 67
    finally:
        await conn.close()
