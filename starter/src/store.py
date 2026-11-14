import hashlib
import json
import re
from typing import Any

import psycopg

from .models import Chunk

_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in values) + "]"


class PgVectorStore:
    TABLE = "chunks"

    def __init__(self, database_url: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    strategy     text   NOT NULL,
                    chunk_id     text   NOT NULL,
                    document_id  text   NOT NULL,
                    source       text   NOT NULL,
                    page         int    NOT NULL,
                    text         text   NOT NULL,
                    metadata     jsonb  NOT NULL DEFAULT '{{}}',
                    content_hash text   NOT NULL,
                    embedding_model text NOT NULL,
                    embedding    vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            row = conn.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'embedding'",
                (self.TABLE,)).fetchone()
            if row and row[0] != self.dimensions:
                raise RuntimeError(
                    f"Table '{self.TABLE}' stores vector({row[0]}) but the model gives {self.dimensions} dims. "
                    "Use the same model or drop the table deliberately.")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {self.TABLE}_meta_idx ON {self.TABLE} USING gin (metadata)")

    def existing_hashes(self, strategy: str, model: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT chunk_id, content_hash FROM {self.TABLE} WHERE strategy = %s AND embedding_model = %s",
                (strategy, model)).fetchall()
        return dict(rows)

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               model: str, keep_ids: set[str] | None = None) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"vector has {len(vector)} dims, expected {self.dimensions}")
        keep = list(keep_ids if keep_ids is not None else {c.chunk_id for c in chunks})
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {self.TABLE} (strategy, chunk_id, document_id, source, page, text,
                                          metadata, content_hash, embedding_model, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                    text = EXCLUDED.text, metadata = EXCLUDED.metadata,
                    content_hash = EXCLUDED.content_hash, embedding_model = EXCLUDED.embedding_model,
                    embedding = EXCLUDED.embedding""",
                [(strategy, c.chunk_id, c.document_id, c.source, c.page, c.text,
                  json.dumps(c.metadata, ensure_ascii=False), content_hash(c.text), model, _vec(v))
                 for c, v in zip(chunks, vectors)])
            cur.execute(f"DELETE FROM {self.TABLE} WHERE strategy = %s AND NOT (chunk_id = ANY(%s))",
                        (strategy, keep))
            return cur.rowcount

    def count(self, strategy: str) -> tuple[int, int]:
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*), count(DISTINCT chunk_id) FROM {self.TABLE} WHERE strategy = %s",
                                (strategy,)).fetchone()

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if not _SAFE_KEY.match(key):
                raise ValueError(f"invalid filter key: {key!r}")
            where.append("metadata ->> %s = %s")
            params += [key, str(value)]
        sql = (f"SELECT chunk_id, document_id, source, page, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM {self.TABLE} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector LIMIT %s")
        vec = _vec(query_vector)
        with self._connect() as conn:
            rows = conn.execute(sql, [vec, *params, vec, top_k]).fetchall()
        return [{"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3], "text": r[4],
                 "metadata": r[5], "score": round(float(r[6]), 6)} for r in rows]
