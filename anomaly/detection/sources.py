import logging
from datetime import datetime
from typing import Optional

from .core import DataSource, DataSourceType, ImageData, SensorData

logger = logging.getLogger(__name__)


class SensorDataSource(DataSource):

    def __init__(self, source_id: str, sensor_type: str, **config):
        super().__init__(source_id, DataSourceType.SENSOR)
        self.sensor_type = sensor_type
        self.config = config
        self.last_reading = None

    def connect(self) -> bool:
        logger.info(f"Connecting to sensor {self.source_id}")
        self.is_connected = True
        return self.is_connected

    def disconnect(self) -> bool:
        logger.info(f"Disconnecting from sensor {self.source_id}")
        self.is_connected = False
        return True

    def fetch_data(self) -> Optional[SensorData]:
        if not self.is_connected:
            return None

        return SensorData(
            values=0.0,
            timestamp=datetime.now(),
            source_id=self.source_id,
            metadata={"sensor_type": self.sensor_type}
        )

    def validate_connection(self) -> bool:
        return self.is_connected


class CameraDataSource(DataSource):

    def __init__(self, source_id: str, camera_url: str, frame_rate: int = 30, **config):
        super().__init__(source_id, DataSourceType.CAMERA)
        self.camera_url = camera_url
        self.frame_rate = frame_rate
        self.config = config
        self.current_frame = None

    def connect(self) -> bool:
        logger.info(f"Connecting to camera {self.source_id}")
        self.is_connected = True
        return self.is_connected

    def disconnect(self) -> bool:
        logger.info(f"Disconnecting from camera {self.source_id}")
        self.is_connected = False
        return True

    def fetch_data(self) -> Optional[ImageData]:
        if not self.is_connected:
            return None

        import numpy as np
        black_frame = np.zeros((224, 224, 3), dtype=np.uint8)
        return ImageData(
            image=black_frame,
            timestamp=datetime.now(),
            source_id=self.source_id,
            metadata={"frame_rate": self.frame_rate, "camera_url": self.camera_url}
        )

    def validate_connection(self) -> bool:
        return self.is_connected
