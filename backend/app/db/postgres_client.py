from __future__ import annotations

from typing import Any, Optional

try:
    import asyncpg
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore


class PostgresClient:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool = None

    async def connect(self) -> None:
        if asyncpg is None:
            raise RuntimeError("asyncpg is not installed. Install backend/requirements.txt or run via Docker.")
        if self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self._pool is None:
            raise RuntimeError("Postgres pool not initialized")
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

