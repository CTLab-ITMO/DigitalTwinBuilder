from sqlalchemy import Column, Integer, BigInteger, String, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    channel_id = Column(String(100), nullable=False, index=True)
    dataset = Column(String(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    value = Column(Float)
    feature_index = Column(Integer, default=0)
    ground_truth = Column(Boolean)


class SensorAnomalyResult(Base):
    __tablename__ = "sensor_anomaly_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=False)
    detector = Column(String(50), nullable=False)
    run_id = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    anomaly_score = Column(Float)
    is_anomaly = Column(Boolean)
    value = Column(Float)
    details = Column(JSON)


class ImageDetectionResult(Base):
    __tablename__ = "image_detection_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=False)
    category = Column(String(100), nullable=False)
    detector = Column(String(50), nullable=False)
    run_id = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    image_name = Column(String(200))
    label = Column(String(100))
    is_anomaly = Column(Boolean)
    anomaly_score = Column(Float)
    auroc_image = Column(Float)
    auroc_pixel = Column(Float)
    pro_score = Column(Float)
    details = Column(JSON)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(String(100))
    alert_type = Column(String(20))
    severity = Column(String(20))
    message = Column(Text)
    score = Column(Float)
    run_id = Column(String(100))
    timestamp = Column(DateTime(timezone=True), default=func.now())


class Zone(Base):
    __tablename__ = "zones"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    sources = relationship("RegisteredSource", back_populates="zone")


class RegisteredSource(Base):
    __tablename__ = "registered_sources"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(String(100), unique=True, nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    zone_id = Column(BigInteger, ForeignKey("zones.id"), nullable=True, index=True)
    display_name = Column(String(200))
    metadata_json = Column(JSON)
    connection_info = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    zone = relationship("Zone", back_populates="sources")
    detector_configs = relationship("DetectorConfig", back_populates="source", cascade="all, delete-orphan")


class DetectorConfig(Base):
    __tablename__ = "detector_configs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(String(100), ForeignKey("registered_sources.source_id"), nullable=False)
    detector_type = Column(String(50), nullable=False)
    parameters = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    source = relationship("RegisteredSource", back_populates="detector_configs")


class DetectorControl(Base):
    __tablename__ = "detector_control"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    zone_name = Column(String(100), nullable=False, default="*")
    detector_type = Column(String(50), nullable=False, default="*")
    command = Column(String(50), nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    executed_at = Column(DateTime(timezone=True))


class DashboardDefinition(Base):
    __tablename__ = "dashboard_definitions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    zone_id = Column(BigInteger, ForeignKey("zones.id"), nullable=False, index=True)
    grafana_uid = Column(String(100), unique=True, nullable=False)
    title = Column(String(200))
    dashboard_url = Column(String(500))
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
