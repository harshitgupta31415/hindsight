"""Scoped retain reads existing document tags in the same order across stores."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg

from hindsight_api.engine.memories import postgres
from hindsight_api.engine.memories.base import DocumentTags, MemoriesExtension


async def test_postgres_document_tags_across_batches(pg0_db_url, monkeypatch):
    monkeypatch.setattr(postgres, "fq_store_table", lambda name: f"pg_temp.{name}")
    conn = await asyncpg.connect(pg0_db_url)
    try:
        await conn.execute("""
            CREATE TEMP TABLE documents (id text, bank_id text, tags varchar[], PRIMARY KEY (id, bank_id));
            INSERT INTO documents VALUES
                ('tagged', 'bank', '{team}'),
                ('untagged', 'bank', NULL),
                ('elsewhere', 'other', '{private}');
        """)
        ids = ["tagged", "elsewhere", *[f"missing-{i}" for i in range(1000)], "untagged"]
        actual = [
            item
            async for item in postgres.PostgresMemories({}).iter_current_document_tags(
                conn=conn, fq_table=None, bank_id="bank", document_ids=ids
            )
        ]
        assert actual == [("tagged", ["team"]), ("untagged", [])]
    finally:
        await conn.close()


async def test_store_default_keeps_missing_tags_distinct_from_missing_documents():
    store = SimpleNamespace(
        current_document_tags=AsyncMock(
            side_effect=[DocumentTags(found=True, tags=None), DocumentTags(found=False, tags=None)]
        )
    )
    actual = [
        item
        async for item in MemoriesExtension.iter_current_document_tags(
            store, conn=None, fq_table=None, bank_id="bank", document_ids=["existing", "missing"]
        )
    ]
    assert actual == [("existing", None)]
