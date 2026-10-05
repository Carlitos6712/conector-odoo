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
        -- seconds; generous default for slow third-party APIs
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
        -- records per request/chunk; small enough to keep one failure cheap to retry
        batch_size INTEGER NOT NULL DEFAULT 100,
        upsert_key TEXT NOT NULL,
        -- on conflicting edits the source system overwrites the target
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

# Non-secret, type-specific profile settings (odoo db/login, token url, scope, api-key header) and
# the NAMES of the stored secrets, kept as JSON so new auth options need no schema change.
_PROFILE_OPTIONS = (
    "ALTER TABLE connection_profiles ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'",
)

# Resource catalog: where an entry came from (manual or an OpenAPI import) and when it last changed.
# The configuration itself stays in ``config_json`` so new options need no schema change.
_RESOURCE_CATALOG = (
    "ALTER TABLE resources ADD COLUMN source TEXT NOT NULL DEFAULT 'manual' "
    "CHECK (source IN ('manual', 'openapi'))",
    "ALTER TABLE resources ADD COLUMN updated_at TEXT",
)

# Sync engine: jobs name their resources and mapping versions (``mapping_id`` keeps pointing at one
# stored version so deleting a referenced mapping stays refused); runs gain conflicts, a resumable
# checkpoint, a heartbeat for crash detection, a parent link for retries and a bounded dry-run
# sample; run errors say which side/kind failed; xref keeps the content hashes of both sides.
_SYNC_ENGINE = (
    "ALTER TABLE sync_jobs ADD COLUMN source_resource TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sync_jobs ADD COLUMN target_resource TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sync_jobs ADD COLUMN mapping_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sync_jobs ADD COLUMN mapping_version INTEGER",
    "ALTER TABLE sync_jobs ADD COLUMN reverse_mapping_id INTEGER REFERENCES mappings(id)",
    "ALTER TABLE sync_jobs ADD COLUMN reverse_mapping_name TEXT",
    "ALTER TABLE sync_jobs ADD COLUMN reverse_mapping_version INTEGER",
    "ALTER TABLE sync_jobs ADD COLUMN source_updated_field TEXT",
    "ALTER TABLE sync_jobs ADD COLUMN target_updated_field TEXT",
    "CREATE UNIQUE INDEX idx_sync_jobs_name ON sync_jobs(name)",
    "CREATE INDEX idx_sync_jobs_reverse_mapping ON sync_jobs(reverse_mapping_id)",
    "ALTER TABLE sync_runs ADD COLUMN conflicts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE sync_runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE sync_runs ADD COLUMN heartbeat_at TEXT",
    "ALTER TABLE sync_runs ADD COLUMN parent_run_id INTEGER REFERENCES sync_runs(id)",
    "ALTER TABLE sync_runs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE sync_runs ADD COLUMN error TEXT",
    "ALTER TABLE sync_runs ADD COLUMN sample_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE sync_runs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX idx_sync_runs_status ON sync_runs(status)",
    "ALTER TABLE run_errors ADD COLUMN side TEXT NOT NULL DEFAULT 'source'",
    "ALTER TABLE run_errors ADD COLUMN kind TEXT NOT NULL DEFAULT 'other'",
    "ALTER TABLE run_errors ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE xref ADD COLUMN content_hash TEXT",
    "ALTER TABLE xref ADD COLUMN reverse_hash TEXT",
    "CREATE INDEX idx_xref_target ON xref(job_id, resource, target_id)",
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial_admin_schema", _INITIAL_SCHEMA),
    Migration(2, "connection_profile_options", _PROFILE_OPTIONS),
    Migration(3, "resource_catalog", _RESOURCE_CATALOG),
    Migration(4, "sync_engine", _SYNC_ENGINE),
)
