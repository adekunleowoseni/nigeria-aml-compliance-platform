"""
PostgreSQL DDL for append-only ``audit_events`` with hash chain, FORCE RLS, and SECURITY DEFINER append.

Direct INSERT/UPDATE/DELETE on the table are blocked for normal sessions; writes go through ``append_audit_event``.
"""

from __future__ import annotations

from app.db.postgres_client import PostgresClient


async def ensure_audit_events_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence BIGSERIAL PRIMARY KEY,
            id UUID NOT NULL UNIQUE,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            nonce TEXT NOT NULL,
            chain_hash TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            actor_sub TEXT,
            actor_email TEXT,
            actor_role TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            ip_address TEXT,
            CONSTRAINT audit_events_prev_len CHECK (LENGTH(TRIM(prev_hash)) = 64),
            CONSTRAINT audit_events_chain_len CHECK (LENGTH(TRIM(chain_hash)) = 64),
            CONSTRAINT audit_events_nonce_nonempty CHECK (LENGTH(TRIM(nonce)) >= 8)
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON audit_events (ts DESC);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events (action);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_sequence ON audit_events (sequence);
        """
    )

    await pg.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_reject_update_delete()
        RETURNS TRIGGER
        LANGUAGE plpgsql AS $f$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only: UPDATE and DELETE are not allowed';
          RETURN NULL;
        END;
        $f$;
        """
    )
    await pg.execute(
        """
        DROP TRIGGER IF EXISTS tr_audit_events_no_mutate ON audit_events;
        """
    )
    await pg.execute(
        """
        CREATE TRIGGER tr_audit_events_no_mutate
          BEFORE UPDATE OR DELETE ON audit_events
          FOR EACH ROW EXECUTE FUNCTION audit_events_reject_update_delete();
        """
    )

    await pg.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;")
    await pg.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;")

    await pg.execute(
        """
        DROP POLICY IF EXISTS audit_events_select_policy ON audit_events;
        """
    )
    await pg.execute(
        """
        CREATE POLICY audit_events_select_policy ON audit_events
          FOR SELECT USING (true);
        """
    )

    await pg.execute(
        """
        CREATE OR REPLACE FUNCTION append_audit_event(
          p_id UUID,
          p_ts TIMESTAMPTZ,
          p_actor TEXT,
          p_action TEXT,
          p_prev_hash TEXT,
          p_nonce TEXT,
          p_chain_hash TEXT,
          p_resource_type TEXT,
          p_resource_id TEXT,
          p_actor_sub TEXT,
          p_actor_email TEXT,
          p_actor_role TEXT,
          p_details JSONB,
          p_ip TEXT
        ) RETURNS BIGINT
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $fn$
        DECLARE
          v_seq BIGINT;
        BEGIN
          PERFORM set_config('row_security', 'off', true);
          INSERT INTO audit_events (
            id, ts, actor, action, prev_hash, nonce, chain_hash,
            resource_type, resource_id, actor_sub, actor_email, actor_role, details, ip_address
          ) VALUES (
            p_id, p_ts, p_actor, p_action, p_prev_hash,
            p_nonce, p_chain_hash,
            p_resource_type, p_resource_id, p_actor_sub, p_actor_email, p_actor_role,
            COALESCE(p_details, '{}'::jsonb), p_ip
          )
          RETURNING sequence INTO v_seq;
          RETURN v_seq;
        END;
        $fn$;
        """
    )

    await pg.execute("REVOKE ALL ON TABLE audit_events FROM PUBLIC;")

    cu = await pg.fetchval("SELECT current_user")
    if cu:
        await pg.execute(f'GRANT SELECT ON TABLE audit_events TO "{cu}";')
        await pg.execute(
            f"""
            GRANT EXECUTE ON FUNCTION append_audit_event(
              UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT
            ) TO "{cu}";
            """
        )
