import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .core import DataSourceType, AnomalyDetectionService
from .sources import SensorDataSource, CameraDataSource

logger = logging.getLogger(__name__)


class DataSourceFactory:

    @staticmethod
    def create_sensor_source(source_id: str, sensor_type: str, **config) -> SensorDataSource:
        return SensorDataSource(source_id, sensor_type, **config)

    @staticmethod
    def create_camera_source(source_id: str, camera_url: str, frame_rate: int = 30, **config) -> CameraDataSource:
        return CameraDataSource(source_id, camera_url, frame_rate, **config)


@dataclass
class StreamConfiguration:
    source_id: str
    source_type: DataSourceType
    source_config: Dict[str, Any]
    anomaly_detector_type: Optional[str] = None
    anomaly_detector_config: Dict[str, Any] = field(default_factory=dict)


class MonitoringServiceBuilder:

    def __init__(self, service_id: str = "anomaly_detection_service"):
        self.service = AnomalyDetectionService(service_id)
        self.streams_config: List[StreamConfiguration] = []

    def add_sensor_stream(self, source_id: str, sensor_type: str,
                          anomaly_detector: Optional[Dict] = None,
                          **source_config) -> "MonitoringServiceBuilder":
        self.streams_config.append(StreamConfiguration(
            source_id=source_id,
            source_type=DataSourceType.SENSOR,
            source_config={"sensor_type": sensor_type, **source_config},
            anomaly_detector_type=anomaly_detector.get("type") if anomaly_detector else None,
            anomaly_detector_config=anomaly_detector or {}
        ))
        return self

    def add_camera_stream(self, source_id: str, camera_url: str, frame_rate: int = 30,
                          anomaly_detector: Optional[Dict] = None,
                          **source_config) -> "MonitoringServiceBuilder":
        self.streams_config.append(StreamConfiguration(
            source_id=source_id,
            source_type=DataSourceType.CAMERA,
            source_config={"camera_url": camera_url, "frame_rate": frame_rate, **source_config},
            anomaly_detector_type=anomaly_detector.get("type") if anomaly_detector else None,
            anomaly_detector_config=anomaly_detector or {}
        ))
        return self

    def build(self) -> AnomalyDetectionService:
        for config in self.streams_config:
            if config.source_type == DataSourceType.SENSOR:
                source = DataSourceFactory.create_sensor_source(
                    config.source_id,
                    config.source_config.get("sensor_type"),
                    **{k: v for k, v in config.source_config.items() if k != "sensor_type"}
                )
            elif config.source_type == DataSourceType.CAMERA:
                source = DataSourceFactory.create_camera_source(
                    config.source_id,
                    config.source_config.get("camera_url"),
                    config.source_config.get("frame_rate", 30),
                    **{k: v for k, v in config.source_config.items() if k not in ["camera_url", "frame_rate"]}
                )
            else:
                logger.error(f"Unknown source type: {config.source_type}")
                continue

            anomaly_detector = None
            if config.anomaly_detector_type:
                logger.warning(
                    f"Anomaly detector type '{config.anomaly_detector_type}' "
                    f"requires factory (None used) for {config.source_id}")

            self.service.add_monitored_stream(source, anomaly_detector)

        logger.info(f"Built monitoring service with {len(self.streams_config)} streams")
        return self.service
