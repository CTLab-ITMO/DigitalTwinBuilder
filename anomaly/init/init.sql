CREATE TABLE IF NOT EXISTS zones (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_zones_name ON zones(name);

CREATE TABLE IF NOT EXISTS registered_sources (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100) UNIQUE NOT NULL,
    source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('sensor', 'camera')),
    zone_id BIGINT REFERENCES zones(id) ON DELETE SET NULL,
    display_name VARCHAR(200),
    metadata_json JSONB,
    connection_info JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reg_sources_source_id ON registered_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_reg_sources_zone ON registered_sources(zone_id);
CREATE INDEX IF NOT EXISTS idx_reg_sources_type ON registered_sources(source_type);

CREATE TABLE IF NOT EXISTS detector_configs (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL REFERENCES registered_sources(source_id) ON DELETE CASCADE,
    detector_type VARCHAR(50) NOT NULL,
    parameters JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_detector_configs_source ON detector_configs(source_id);

CREATE TABLE IF NOT EXISTS dashboard_definitions (
    id BIGSERIAL PRIMARY KEY,
    zone_id BIGINT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    grafana_uid VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(200),
    dashboard_url VARCHAR(500),
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dash_defs_zone ON dashboard_definitions(zone_id);
CREATE INDEX IF NOT EXISTS idx_dash_defs_uid ON dashboard_definitions(grafana_uid);

CREATE TABLE IF NOT EXISTS detector_control (
    id BIGSERIAL PRIMARY KEY,
    zone_name VARCHAR(100) NOT NULL DEFAULT '*',
    detector_type VARCHAR(50) NOT NULL DEFAULT '*',
    command VARCHAR(50) NOT NULL CHECK (command IN ('train', 'enable', 'disable', 'reset')),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_detector_control_pending ON detector_control(zone_name, detector_type, command)
    WHERE executed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_detector_control_issued ON detector_control(issued_at DESC);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id BIGSERIAL PRIMARY KEY,
    channel_id VARCHAR(100) NOT NULL,
    dataset VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION,
    feature_index INTEGER DEFAULT 0,
    ground_truth BOOLEAN
);

CREATE TABLE IF NOT EXISTS sensor_anomaly_results (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL REFERENCES registered_sources(source_id) ON DELETE SET NULL,
    detector VARCHAR(50) NOT NULL,
    run_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    anomaly_score DOUBLE PRECISION,
    is_anomaly BOOLEAN,
    value DOUBLE PRECISION,
    details JSONB
);

CREATE TABLE IF NOT EXISTS image_detection_results (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL REFERENCES registered_sources(source_id) ON DELETE SET NULL,
    category VARCHAR(100) NOT NULL,
    detector VARCHAR(50) NOT NULL,
    run_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    image_name VARCHAR(200),
    label VARCHAR(100),
    is_anomaly BOOLEAN,
    anomaly_score DOUBLE PRECISION,
    auroc_image DOUBLE PRECISION,
    auroc_pixel DOUBLE PRECISION,
    pro_score DOUBLE PRECISION,
    details JSONB
);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(100),
    alert_type VARCHAR(20) NOT NULL CHECK (alert_type IN ('sensor_anomaly', 'camera_anomaly', 'fused', 'cross_modal')),
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    message TEXT,
    score DOUBLE PRECISION,
    run_id VARCHAR(100),
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_channel ON sensor_readings(channel_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_dataset ON sensor_readings(dataset);
CREATE INDEX IF NOT EXISTS idx_sensor_anomaly_channel ON sensor_anomaly_results(source_id, detector, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_anomaly_run ON sensor_anomaly_results(run_id);
CREATE INDEX IF NOT EXISTS idx_image_results_category ON image_detection_results(category, detector, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_image_results_source ON image_detection_results(source_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_image_results_run ON image_detection_results(run_id);
CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_source_severity ON alerts(source_id, severity, timestamp DESC);

CREATE OR REPLACE FUNCTION check_detector_control_zone()
RETURNS trigger AS $$
BEGIN
    IF NEW.zone_name != '*'
       AND NEW.zone_name != ''
       AND NOT EXISTS (SELECT 1 FROM zones WHERE name = NEW.zone_name) THEN
        RAISE EXCEPTION 'zone_name % is not a valid zone name (use * for all)', NEW.zone_name;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_detector_control_zone ON detector_control;
CREATE TRIGGER trg_detector_control_zone
    BEFORE INSERT OR UPDATE ON detector_control
    FOR EACH ROW
    EXECUTE FUNCTION check_detector_control_zone();
