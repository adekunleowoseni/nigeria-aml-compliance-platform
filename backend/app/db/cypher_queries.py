FIND_SMURFING = """
MATCH (beneficiary:Account)<-[t:TRANSFERRED]-(source:Account)
WHERE source.id IN $source_ids
  AND datetime($start_time) <= t.timestamp <= datetime($end_time)
WITH beneficiary,
     count(DISTINCT source) as source_count,
     sum(t.amount) as total_amount,
     collect(DISTINCT source.id) as sources
WHERE source_count >= $min_sources
  AND total_amount >= $threshold
RETURN beneficiary.id as beneficiary,
       source_count,
       total_amount,
       sources
"""

FIND_CYCLES = """
MATCH path = (a:Account)-[:TRANSFERRED*3..{max_length}]->(a)
WHERE a.id = $account_id
WITH path,
     [n IN nodes(path) | n.id] as node_ids,
     reduce(total = 0, t IN relationships(path) | total + coalesce(t.amount, 0)) as cycle_amount
RETURN node_ids,
       length(path) as cycle_length,
       cycle_amount
ORDER BY cycle_amount DESC
"""

RAPID_SUCCESSION = """
MATCH (a:Account)-[t1:TRANSFERRED]->()
MATCH (a)-[t2:TRANSFERRED]->()
WHERE datetime($start_time) <= t1.timestamp <= datetime($end_time)
  AND t1 <> t2
  AND duration.between(t1.timestamp, t2.timestamp).seconds < $threshold_seconds
RETURN a.id as account_id,
       count(*) as rapid_transaction_count
"""

SUBGRAPH_EXTRACTION = """
MATCH path = (center)-[:TRANSFERRED*0..{depth}]-(neighbor)
WHERE center.id = $center_id
WITH center, neighbor, relationships(path) as rels
UNWIND rels as rel
WITH center, neighbor, rel,
     startNode(rel) as source,
     endNode(rel) as target
RETURN collect(DISTINCT {
    id: center.id,
    type: labels(center)[0],
    properties: properties(center)
}) + collect(DISTINCT {
    id: neighbor.id,
    type: labels(neighbor)[0],
    properties: properties(neighbor)
}) as nodes,
collect(DISTINCT {
    source: source.id,
    target: target.id,
    type: type(rel),
    properties: properties(rel)
}) as edges
"""

NETWORK_METRICS = """
MATCH (a:Account {id: $account_id})
OPTIONAL MATCH (a)-[t:TRANSFERRED]->()
WITH a, count(t) as out_degree, sum(coalesce(t.amount, 0)) as out_volume
OPTIONAL MATCH (a)<-[t2:TRANSFERRED]-()
RETURN out_degree,
       count(t2) as in_degree,
       out_volume,
       sum(coalesce(t2.amount, 0)) as in_volume,
       out_degree + count(t2) as total_degree
"""

