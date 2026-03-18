from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from neo4j import AsyncGraphDatabase
except Exception:  # pragma: no cover
    AsyncGraphDatabase = None  # type: ignore


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        if AsyncGraphDatabase is None:
            raise RuntimeError("neo4j driver is not installed. Install backend/requirements.txt or run via Docker.")
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        await self._driver.close()

    async def run_query(self, query: str, parameters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run(query, parameters or {})
            return await result.data()

    async def initialize_schema(self) -> None:
        await self.run_query(
            """
            CREATE CONSTRAINT account_id IF NOT EXISTS
            FOR (a:Account) REQUIRE a.id IS UNIQUE
            """
        )
        await self.run_query(
            """
            CREATE CONSTRAINT transaction_id IF NOT EXISTS
            FOR (t:Transaction) REQUIRE t.id IS UNIQUE
            """
        )
        await self.run_query(
            """
            CREATE INDEX account_type_idx IF NOT EXISTS
            FOR (a:Account) ON (a.type)
            """
        )
        await self.run_query(
            """
            CREATE INDEX transaction_timestamp_idx IF NOT EXISTS
            FOR (t:Transaction) ON (t.timestamp)
            """
        )

    async def get_subgraph(
        self,
        center_id: str,
        depth: int = 2,
        relationship_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        rel_filter = ""
        if relationship_types:
            rel_filter = ":" + "|".join(relationship_types)
        query = f"""
        MATCH path = (center {{id: $center_id}})-[{rel_filter}*0..{depth}]-(neighbor)
        WITH center, neighbor, relationships(path) as rels
        UNWIND rels as rel
        WITH center, neighbor, rel, startNode(rel) as source, endNode(rel) as target
        RETURN
          collect(DISTINCT {{id: center.id, type: labels(center)[0], properties: properties(center)}}) +
          collect(DISTINCT {{id: neighbor.id, type: labels(neighbor)[0], properties: properties(neighbor)}}) as nodes,
          collect(DISTINCT {{source: source.id, target: target.id, type: type(rel), properties: properties(rel)}}) as edges
        """
        rows = await self.run_query(query, {"center_id": center_id})
        if not rows:
            return {"nodes": [], "edges": []}
        return rows[0]

