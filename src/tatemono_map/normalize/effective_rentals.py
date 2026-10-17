"""One private-row selection contract for aggregation and rendering."""
from __future__ import annotations


def canonical_key(value, aliases):
    seen = set()
    while value in aliases and aliases[value] != value:
        if value in seen:
            raise ValueError("alias_cycle")
        seen.add(value)
        value = aliases[value]
    return value


def effective_rentals(conn):
    aliases = dict(conn.execute("SELECT alias_key,canonical_key FROM building_key_aliases"))
    ranks = dict(conn.execute("SELECT source,priority_rank FROM source_priority WHERE domain='rental' AND enabled=1"))
    rows = conn.execute("""
        SELECT l.* FROM listings l
        WHERE (l.ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
          OR EXISTS (SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
            ON s.source=h.scope_key AND s.ingest_run_id=h.ingest_run_id WHERE h.listing_key=l.listing_key)
          OR (l.ingest_run_id IS NULL AND NOT EXISTS (SELECT 1 FROM current_ingest_snapshots)))
        AND (EXISTS (SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
            ON s.source=h.scope_key AND s.ingest_run_id=h.ingest_run_id WHERE h.listing_key=l.listing_key)
          OR NOT EXISTS (
          SELECT 1 FROM cloud_baseline_ownership o
          JOIN current_ingest_snapshots s ON s.source=o.scope_key
          WHERE o.listing_key=l.listing_key))
        AND NOT EXISTS (
          SELECT 1 FROM cloud_unit_overlaps o JOIN current_ingest_snapshots s
            ON s.source=o.scope_key AND s.ingest_run_id=o.ingest_run_id
          WHERE o.listing_key=l.listing_key)
        ORDER BY l.id DESC
    """).fetchall()
    grouped = {}
    for raw in rows:
        row = dict(raw)
        if row['building_key']:
            row['building_key'] = canonical_key(row['building_key'], aliases)
            grouped.setdefault(row['building_key'], []).append(row)
    selected = []
    for items in grouped.values():
        # Existing policy is building-wide, not a merge of individual fields.
        available = [ranks[r['source_kind']] for r in items if r['source_kind'] in ranks]
        # Unranked legacy imports keep their existing combined-snapshot policy.
        # Rank filtering applies when all rows have an explicit provider rank.
        best = min(available) if available and len(available) == len(items) else None
        selected.extend(r for r in items if best is None or ranks.get(r['source_kind']) == best)
    return selected
