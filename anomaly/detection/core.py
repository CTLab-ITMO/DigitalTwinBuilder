from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
import logging
import numpy as np

logger = logging.getLogger(__name__)

ArrayLike = Union[np.ndarray, List[float], List[int], float]

ImageArrayLike = Union[np.ndarray, List[np.ndarray]]


class DataSourceType(Enum):
    SENSOR = "sensor"
    CAMERA = "camera"
    VIDEO_STREAM = "video_stream"
    IMAGE = "image"


@dataclass
class SensorData:
    values: ArrayLike
    timestamp: Optional[datetime] = None
    source_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.values = np.asarray(self.values, dtype=np.float64)

        if self.values.ndim == 0:
            self.values = self.values.reshape(1)

    @property
    def is_batch(self) -> bool:
        if self.values.ndim == 1:
            return len(self.values) > 1
        return self.values.shape[0] > 1

    @property
    def n_samples(self) -> int:
        if self.values.ndim == 1:
            return len(self.values)
        return self.values.shape[0]

    @property
    def n_features(self) -> int:
        if self.values.ndim == 1:
            return 1
        return self.values.shape[-1]

    def to_2d(self) -> np.ndarray:
        if self.values.ndim == 1:
            return self.values.reshape(-1, 1)
        return self.values

    def to_1d(self) -> np.ndarray:
        if self.values.ndim == 1:
            return self.values
        if self.values.shape[0] == 1:
            return self.values[0]
        raise ValueError("Cannot convert multi-sample data to 1D")


@dataclass
class ImageData:
    values: ImageArrayLike
    timestamp: Optional[datetime] = None
    source_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.values, list):
            self.values = np.array(self.values)
        elif not isinstance(self.values, np.ndarray):
            self.values = np.array(self.values)

    @property
    def is_batch(self) -> bool:
        if self.values.ndim == 4:
            return self.values.shape[0] > 1
        return False

    @property
    def n_images(self) -> int:
        if self.values.ndim == 4:
            return self.values.shape[0]
        return 1

    @property
    def height(self) -> int:
        if self.values.ndim == 4:
            return self.values.shape[1]
        return self.values.shape[0]

    @property
    def width(self) -> int:
        if self.values.ndim == 4:
            return self.values.shape[2]
        return self.values.shape[1]

    @property
    def channels(self) -> int:
        if self.values.ndim == 4:
            return self.values.shape[3]
        return self.values.shape[2] if self.values.ndim == 3 else 1

    def to_batch(self) -> np.ndarray:
        if self.values.ndim == 3:
            return self.values[np.newaxis, ...]
        return self.values

    def get_image(self, index: int = 0) -> np.ndarray:
        if self.values.ndim == 4:
            return self.values[index]
        return self.values


class DataSource(ABC):

    def __init__(self, source_id: str, source_type: DataSourceType):
        self.source_id = source_id
        self.source_type = source_type
        self.is_connected = False

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        pass

    @abstractmethod
    def fetch_data(self) -> Optional[SensorData]:
        pass

    @abstractmethod
    def validate_connection(self) -> bool:
        pass


@dataclass
class AnomalyDetectionResult:
    is_anomaly: bool
    anomaly_score: float
    anomaly_type: Optional[str]
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)


class AnomalyDetector(ABC):

    def __init__(self, detector_id: str, threshold: float = 0.5):
        self.detector_id = detector_id
        self.threshold = threshold
        self.model = None
        self.is_trained = False

    @abstractmethod
    def fit(self, normal_data: Union[List['SensorData'], 'SensorData', np.ndarray, List[float]]) -> bool:
        pass

    @abstractmethod
    def detect(self, data: Union['SensorData', np.ndarray, List[float], float]) -> AnomalyDetectionResult:
        pass

    @abstractmethod
    def update(self, data: Union['SensorData', np.ndarray, List[float], float], is_normal: bool) -> None:
        pass


@dataclass
class MonitoringAlert:
    alert_id: str
    source_id: str
    alert_type: str
    severity: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    anomaly_result: Optional[AnomalyDetectionResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MonitoredStream:

    def __init__(self, source: DataSource):
        self.source = source
        self.anomaly_detector: Optional[AnomalyDetector] = None
        self.is_enabled = True
        self.data_history: List[SensorData] = []
        self.max_history_size = 1000

    def add_data(self, data: SensorData) -> None:
        self.data_history.append(data)
        if len(self.data_history) > self.max_history_size:
            self.data_history.pop(0)


class AnomalyDetectionService:

    def __init__(self, service_id: str = "anomaly_detection_service"):
        self.service_id = service_id
        self.monitored_streams: Dict[str, MonitoredStream] = {}
        self.is_running = False
        logger.info(f"Initialized {self.service_id}")

    def add_monitored_stream(self, source: DataSource,
                             anomaly_detector: Optional[AnomalyDetector] = None) -> bool:
        if source.source_id in self.monitored_streams:
            logger.warning(f"Stream {source.source_id} already exists")
            return False

        if not source.connect():
            logger.error(f"Failed to connect to source {source.source_id}")
            return False

        stream = MonitoredStream(source)
        stream.anomaly_detector = anomaly_detector

        self.monitored_streams[source.source_id] = stream
        logger.info(f"Added monitored stream: {source.source_id}")
        return True

    def remove_monitored_stream(self, source_id: str) -> bool:
        if source_id not in self.monitored_streams:
            return False

        stream = self.monitored_streams[source_id]
        stream.source.disconnect()
        del self.monitored_streams[source_id]
        logger.info(f"Removed monitored stream: {source_id}")
        return True

    def train_detectors(self, source_id: str, baseline_data: Union[List[SensorData], np.ndarray, List[float]]) -> bool:
        if source_id not in self.monitored_streams:
            logger.error(f"Stream {source_id} not found")
            return False

        stream = self.monitored_streams[source_id]

        if stream.drift_detector:
            if not stream.drift_detector.fit(baseline_data):
                logger.error(f"Failed to train drift detector for {source_id}")
                return False
            logger.info(f"Trained drift detector for {source_id}")
        if stream.anomaly_detector:
            if not stream.anomaly_detector.fit(baseline_data):
                logger.error(f"Failed to train anomaly detector for {source_id}")
                return False
            logger.info(f"Trained anomaly detector for {source_id}")

        return True

    def process_data(self, source_id: str) -> Optional[AnomalyDetectionResult]:
        if source_id not in self.monitored_streams:
            logger.error(f"Stream {source_id} not found")
            return None, None

        stream = self.monitored_streams[source_id]

        if not stream.is_enabled:
            return None, None

        data = stream.source.fetch_data()
        if data is None:
            return None, None

        stream.add_data(data)

        anomaly_result = None
        alerts_to_emit = []

        if stream.anomaly_detector:
            anomaly_result = stream.anomaly_detector.detect(data)
            if anomaly_result.is_anomaly:
                alerts_to_emit.append(
                    MonitoringAlert(
                        alert_id=f"anomaly_{source_id}_{datetime.now().timestamp()}",
                        source_id=source_id,
                        alert_type="anomaly",
                        severity=self._score_to_severity(anomaly_result.anomaly_score),
                        message=f"Anomaly detected: {anomaly_result.anomaly_type}",
                        anomaly_result=anomaly_result
                    )
                )
            stream.anomaly_detector.update(data, is_normal=not anomaly_result.is_anomaly)

        for alert in alerts_to_emit:
            self._emit_alert(alert)

        return anomaly_result

    def start_monitoring(self) -> None:
        logger.info(f"Starting {self.service_id}")
        self.is_running = True

    def stop_monitoring(self) -> None:
        logger.info(f"Stopping {self.service_id}")
        self.is_running = False
        for stream in self.monitored_streams.values():
            stream.source.disconnect()

    def _emit_alert(self, alert: MonitoringAlert) -> None:
        logger.warning(f"Alert: {alert.alert_type} - {alert.message}")
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Error in alert handler: {e}")

    @staticmethod
    def _score_to_severity(score: float) -> str:
        if score < 0.3:
            return "low"
        elif score < 0.6:
            return "medium"
        elif score < 0.8:
            return "high"
        else:
            return "critical"

    def get_stream_status(self, source_id: str) -> Dict[str, Any]:
        if source_id not in self.monitored_streams:
            return {}

        stream = self.monitored_streams[source_id]
        return {
            "source_id": source_id,
            "source_type": stream.source.source_type.value,
            "is_enabled": stream.is_enabled,
            "is_connected": stream.source.is_connected,
            "data_collected": len(stream.data_history),
            "drift_detector_trained": stream.drift_detector.is_trained if stream.drift_detector else False,
            "anomaly_detector_trained": stream.anomaly_detector.is_trained if stream.anomaly_detector else False
        }
