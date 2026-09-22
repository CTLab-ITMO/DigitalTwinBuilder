import logging
from pathlib import Path
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

SMAP_DATA: Dict[str, np.ndarray] = {}
SMAP_TEST_DATA: Dict[str, np.ndarray] = {}
SMAP_CHANNEL_NAMES: list[str] = []


def load_smap() -> None:
    global SMAP_DATA, SMAP_TEST_DATA, SMAP_CHANNEL_NAMES
    if SMAP_DATA:
        return

    candidates = [
        (Path.home() / ".cache" / "kagglehub" / "datasets" / "patrickfleith" /
         "nasa-anomaly-detection-dataset-smap-msl" / "versions" / "1" / "data" / "data"),
        Path("/kagglehub") / "datasets" / "patrickfleith" /
        "nasa-anomaly-detection-dataset-smap-msl" / "versions" / "1" / "data" / "data",
    ]

    base_dir = next((p for p in candidates if (p / "train").is_dir()), None)
    if base_dir is None:
        logger.error("SMAP data not found at kagglehub cache")
        return

    train_dir = base_dir / "train"
    test_dir = base_dir / "test"

    for f in sorted(train_dir.glob("*.npy")):
        arr = np.load(str(f), allow_pickle=True)
        if arr.ndim == 2 and arr.shape[1] >= 25:
            SMAP_CHANNEL_NAMES.append(f.stem)
            SMAP_DATA[f.stem] = arr.astype(np.float64)

    for ch_name in SMAP_CHANNEL_NAMES:
        test_path = test_dir / f"{ch_name}.npy"
        if test_path.exists():
            SMAP_TEST_DATA[ch_name] = np.load(str(test_path), allow_pickle=True).astype(np.float64)
        else:
            SMAP_TEST_DATA[ch_name] = SMAP_DATA[ch_name]

    logger.info("Loaded %d SMAP channels (train + test)", len(SMAP_DATA))


def get_zone_channel(zone_name: str) -> Optional[str]:
    if not SMAP_CHANNEL_NAMES:
        return None
    rng = np.random.default_rng(abs(hash(zone_name + "_smap_channel")))
    return SMAP_CHANNEL_NAMES[int(rng.integers(len(SMAP_CHANNEL_NAMES)))]


def get_zone_train(zone_name: str, n_cols: int = 25) -> Optional[np.ndarray]:
    ch = get_zone_channel(zone_name)
    if ch is None or ch not in SMAP_DATA:
        return None
    return SMAP_DATA[ch][:, :n_cols]


def get_zone_test(zone_name: str, n_cols: int = 25) -> Optional[np.ndarray]:
    ch = get_zone_channel(zone_name)
    if ch is None or ch not in SMAP_TEST_DATA:
        return None
    return SMAP_TEST_DATA[ch][:, :n_cols]
