BEGIN;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL,
    case_id TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    feedback_requested INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active
    ON sessions(owner_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS events (
    seq BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    ref TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS disclosures (
    session_id TEXT NOT NULL REFERENCES sessions(id),
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    transport TEXT NOT NULL DEFAULT 'returned',
    PRIMARY KEY (session_id, filename)
);

COMMIT;
