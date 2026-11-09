-- Riverside Family Medicine (FICTIONAL DEMO) — SQLite schema
-- All data in this database is fake. No real patient information.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS providers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,          -- "Dr. Maya Patel"
    last_name   TEXT NOT NULL,          -- "Patel" (used for fuzzy matching "Dr. Patel")
    specialty   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    start_time  TEXT NOT NULL,          -- clinic-local ISO, e.g. "2026-11-10T09:30"
    duration_min INTEGER NOT NULL DEFAULT 30,
    is_blocked  INTEGER NOT NULL DEFAULT 0,  -- 1 = held (meetings, admin time); never offered
    UNIQUE (provider_id, start_time)
);

CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,          -- as first given, e.g. "Robert O'Brien"
    name_key    TEXT NOT NULL,          -- letters only, lowercase: "robertobrien"
    dob         TEXT NOT NULL,          -- "YYYY-MM-DD"
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (name_key, dob)
);

CREATE TABLE IF NOT EXISTS appointments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patients(id),
    slot_id         INTEGER NOT NULL REFERENCES slots(id),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'cancelled')),
    previous_slot_id INTEGER REFERENCES slots(id),   -- set when rescheduled
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The double-booking guard: at most ONE scheduled appointment per slot.
-- Cancelled appointments don't count, so a cancelled slot becomes bookable again.
-- Enforced by the database, so two concurrent calls can't both win the same slot.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_appt_per_slot
    ON appointments(slot_id) WHERE status = 'scheduled';

CREATE TABLE IF NOT EXISTS transfers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     TEXT,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every tool call the agent makes, success or failure. This is the debugging backbone.
CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,          -- UTC ISO timestamp
    call_id     TEXT,                   -- Vapi call id (NULL for direct REST/curl calls)
    source      TEXT NOT NULL,          -- 'vapi' or 'rest'
    tool        TEXT NOT NULL,
    inputs      TEXT NOT NULL,          -- JSON
    result      TEXT NOT NULL,          -- JSON
    ok          INTEGER NOT NULL,       -- 1 success, 0 error
    error_code  TEXT,
    duration_ms REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_call_id ON tool_calls(call_id);
