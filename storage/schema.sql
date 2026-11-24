CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    scenario TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT CHECK (ended_at IS NULL OR ended_at >= started_at),
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    series_id TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    air_temperature_c REAL NOT NULL,
    relative_humidity_pct REAL NOT NULL CHECK (relative_humidity_pct > 0 AND relative_humidity_pct <= 100),
    surface_temperature_c REAL NOT NULL,
    dew_point_c REAL NOT NULL,
    dpu_c REAL NOT NULL,
    UNIQUE (experiment_id, measured_at, series_id)
);

CREATE TABLE IF NOT EXISTS experiment_events (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    event_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT CHECK (ended_at IS NULL OR ended_at >= started_at),
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS method_settings (
    id INTEGER PRIMARY KEY,
    method TEXT NOT NULL CHECK (method IN ('threshold', 'linear', 'random_forest')),
    parameters_json TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL CHECK (horizon_minutes IN (5, 10, 15)),
    model_version TEXT NOT NULL DEFAULT '',
    model_path TEXT NOT NULL DEFAULT '',
    CHECK (method <> 'random_forest' OR (model_version <> '' AND model_path <> '')),
    UNIQUE (method, parameters_json, horizon_minutes, model_version, model_path)
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL REFERENCES measurements(id),
    setting_id INTEGER NOT NULL REFERENCES method_settings(id),
    predicted_at TEXT NOT NULL,
    risk INTEGER NOT NULL CHECK (risk IN (0, 1)),
    first_displayed_at TEXT CHECK (first_displayed_at IS NULL OR (risk = 1 AND first_displayed_at >= predicted_at)),
    UNIQUE (measurement_id, setting_id, predicted_at)
);

CREATE INDEX IF NOT EXISTS idx_events_experiment_time ON experiment_events(experiment_id, started_at);
CREATE INDEX IF NOT EXISTS idx_predictions_setting ON predictions(setting_id);
