"""Ordered migration list. Append new migrations; never edit one that has shipped."""

from conector_odoo.infrastructure.migrations.migrator import Migration

_INITIAL_SCHEMA = (
    """
    CREATE TABLE connection_profiles (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        type TEXT NOT NULL,
        base_url TEXT NOT NULL,
        auth_method TEXT NOT NULL,
        secrets_blob BLOB,
        extra_headers_json TEXT NOT NULL DEFAULT '{}',
        tls_verify INTEGER NOT NULL DEFAULT 1 CHECK (tls_verify IN (0, 1)),
        timeout_seconds REAL NOT NULL DEFAULT 30,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE resources (
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES connection_profiles(id),
        name TEXT NOT NULL,
        config_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE (profile_id, name)
    )
    """,
    """
    CREATE TABLE mappings (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        version INTEGER NOT NULL,
        definition_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (name, version)
    )
    """,
    """
    CREATE TABLE sync_jobs (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        source_profile_id INTEGER NOT NULL REFERENCES connection_profiles(id),
        target_profile_id INTEGER NOT NULL REFERENCES connection_profiles(id),
        mapping_id INTEGER NOT NULL REFERENCES mappings(id),
        direction TEXT NOT NULL,
        trigger_json TEXT NOT NULL DEFAULT '{}',
        filter_json TEXT NOT NULL DEFAULT '{}',
        batch_size INTEGER NOT NULL DEFAULT 100,
        upsert_key TEXT NOT NULL,
        conflict_rule TEXT NOT NULL DEFAULT 'source_wins',
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_sync_jobs_mapping ON sync_jobs(mapping_id)",
    "CREATE INDEX idx_sync_jobs_source ON sync_jobs(source_profile_id)",
    "CREATE INDEX idx_sync_jobs_target ON sync_jobs(target_profile_id)",
    """
    CREATE TABLE sync_runs (
        id INTEGER PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES sync_jobs(id),
        status TEXT NOT NULL,
        trigger TEXT NOT NULL,
        created INTEGER NOT NULL DEFAULT 0,
        updated INTEGER NOT NULL DEFAULT 0,
        skipped INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        dry_run INTEGER NOT NULL DEFAULT 0 CHECK (dry_run IN (0, 1))
    )
    """,
    "CREATE INDEX idx_sync_runs_job_started ON sync_runs(job_id, started_at)",
    """
    CREATE TABLE run_errors (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
        record_ref TEXT,
        message TEXT NOT NULL,
        payload_json TEXT,
        retried INTEGER NOT NULL DEFAULT 0 CHECK (retried IN (0, 1))
    )
    """,
    "CREATE INDEX idx_run_errors_run ON run_errors(run_id)",
    """
    CREATE TABLE xref (
        id INTEGER PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES sync_jobs(id),
        resource TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (job_id, resource, source_id)
    )
    """,
    """
    CREATE TABLE admin_users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'operator')),
        created_at TEXT NOT NULL
    )
    """,
)

MIGRATIONS: tuple[Migration, ...] = (Migration(1, "initial_admin_schema", _INITIAL_SCHEMA),)
