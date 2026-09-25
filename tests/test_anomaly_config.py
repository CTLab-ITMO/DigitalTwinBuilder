"""Tests for `anomaly_config` — the interview's devices as the anomaly stack's config.

The anomaly stack is configured by a zone-keyed JSON file that used to be
hand-written for the demo. `anomaly_config.build_anomaly_config` builds it from
the `requirements` document the interview produces, so the user's real Modbus
and RTSP devices reach the detector without anyone editing a file. There is no
LLM and no database in the mapping, so it is pinned directly here.

What is pinned here:

* the shape — one zone, `sensors` and `cameras` lists, and no zone at all when
  the requirements name no device;
* the addressing — a named ip/port/register/unit-id/data-type survives the
  mapping, and one the user never gave stays absent instead of being invented;
* the RTSP url — assembled only from a named host, with the stream path joined
  the way a capture loop can open it;
* the ids — slugified, stable for a device with no id, and de-duplicated;
* the input spellings — an object or the raw JSON text the client stored, and a
  dict-keyed device map as well as the list the prompt asks for.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "digital_twin_builder"))

import anomaly_config  # noqa: E402


REQ = {
    "production_type": "Линия розлива",
    "sensors": [
        {
            "id": "temperature_a",
            "name": "Датчик температуры",
            "ip": "192.168.1.10",
            "port": 502,
            "unit_id": 1,
            "register": 40001,
            "register_type": "holding",
            "data_type": "int16",
            "sensor_type": "temperature",
            "unit": "C",
        },
        {
            "id": "pressure_a",
            "name": "Датчик давления",
            "ip": "192.168.1.11",
            "register": "40002",
            "data_type": "float32",
            "sensor_type": "pressure",
        },
    ],
    "cameras": [
        {
            "id": "camera_bottle",
            "name": "Камера розлива",
            "ip": "192.168.1.20",
            "port": 8554,
            "stream_path": "/stream1",
            "category": "bottle",
        }
    ],
}


def test_maps_devices_into_one_zone():
    config = anomaly_config.build_anomaly_config(REQ, zone_name="session_42")

    assert list(config) == ["session_42"]
    zone = config["session_42"]
    assert zone["description"] == "Линия розлива"
    assert [s["id"] for s in zone["sensors"]] == ["temperature_a", "pressure_a"]
    assert [c["id"] for c in zone["cameras"]] == ["camera_bottle"]


def test_keeps_the_modbus_addressing():
    sensor = anomaly_config.build_anomaly_config(REQ)["линия_розлива"]["sensors"][0]

    assert sensor["protocol"] == "modbus"
    assert sensor["ip"] == "192.168.1.10"
    assert sensor["port"] == 502
    assert sensor["unit_id"] == 1
    assert sensor["register"] == 40001
    assert sensor["data_type"] == "int16"
    assert sensor["sensor_type"] == "temperature"
    assert sensor["unit"] == "C"


def test_invents_no_address_the_user_did_not_give():
    sensor = anomaly_config.build_anomaly_config(REQ)["линия_розлива"]["sensors"][1]

    assert "port" not in sensor  # no "typical" 502
    assert "unit_id" not in sensor  # no "typical" 1
    assert sensor["register"] == 40002  # a numeric string is still the register


def test_register_type_carries_through_and_stays_absent_when_unnamed():
    sensors = anomaly_config.build_anomaly_config(REQ)["линия_розлива"]["sensors"]

    assert sensors[0]["register_type"] == "holding"  # named -> kept
    assert "register_type" not in sensors[1]  # unnamed -> not invented as holding


def test_derives_the_rtsp_url_from_a_named_host_only():
    config = anomaly_config.build_anomaly_config(REQ)
    camera = config["линия_розлива"]["cameras"][0]

    assert camera["protocol"] == "rtsp"
    assert camera["rtsp_url"] == "rtsp://192.168.1.20:8554/stream1"
    assert camera["stream_path"] == "/stream1"
    assert camera["category"] == "bottle"


def test_camera_without_a_host_has_no_url():
    config = anomaly_config.build_anomaly_config(
        {"cameras": [{"id": "camera_1", "name": "Камера без адреса"}]}
    )
    camera = config["production_line"]["cameras"][0]

    assert "rtsp_url" not in camera
    assert "ip" not in camera
    assert camera["category"] == "камера_без_адреса"


def test_default_rtsp_port_and_joined_path():
    config = anomaly_config.build_anomaly_config(
        {"cameras": [{"id": "cam", "ip": "10.0.0.5", "stream_path": "live"}]}
    )
    assert config["production_line"]["cameras"][0]["rtsp_url"] == "rtsp://10.0.0.5:554/live"


def test_ids_are_slugged_unique_and_stable_without_one():
    config = anomaly_config.build_anomaly_config({
        "sensors": [
            {"name": "Датчик температуры", "sensor_type": "temperature"},
            {"name": "Датчик температуры", "sensor_type": "temperature"},
            {"sensor_type": "pressure"},
        ]
    })
    assert [s["id"] for s in config["production_line"]["sensors"]] == [
        "датчик_температуры",
        "датчик_температуры_2",
        "sensor_3",
    ]


def test_a_suffixed_id_does_not_collide_with_a_later_device():
    """`temp`, `temp`, `temp_2` — the name an earlier device was given counts too.

    Counting per base name alone hands `temp_2` to the second *and* the third
    device, and the detector would then poll one channel while dropping the
    other's readings.
    """
    config = anomaly_config.build_anomaly_config({
        "sensors": [{"id": "temp"}, {"id": "temp"}, {"id": "temp_2"}]
    })
    ids = [s["id"] for s in config["production_line"]["sensors"]]

    assert ids == ["temp", "temp_2", "temp_2_2"]
    assert len(ids) == len(set(ids))


def test_a_sensor_and_a_camera_never_share_an_id():
    """Sensors and cameras are one id namespace downstream.

    `registered_sources.source_id` is globally unique and `config_loader` keys
    on it, so if a sensor and a camera both keep `line1` the second write wins
    and one device's readings are attributed to the other.
    """
    config = anomaly_config.build_anomaly_config({
        "sensors": [{"id": "line1"}, {"id": "line1"}],
        "cameras": [{"id": "line1"}],
    })
    zone = config["production_line"]
    ids = [s["id"] for s in zone["sensors"]] + [c["id"] for c in zone["cameras"]]

    assert ids == ["line1", "line1_2", "line1_3"]
    assert len(ids) == len(set(ids))


def test_a_suffixed_id_still_fits_the_column():
    """`source_id` is VARCHAR(100); the suffix must not push an id over it."""
    long_id = "a" * 100
    config = anomaly_config.build_anomaly_config({
        "sensors": [{"id": long_id}, {"id": long_id, "ip": "1.1.1.1"}],
    })
    ids = [s["id"] for s in config["production_line"]["sensors"]]

    assert ids == ["a" * 100, "a" * 98 + "_2"]
    assert all(len(i) <= 100 for i in ids)
    assert len(ids) == len(set(ids))


def test_object_or_json_text_or_dict_keyed_map():
    as_text = anomaly_config.build_anomaly_config(json.dumps(REQ))
    as_map = anomaly_config.build_anomaly_config({
        "sensors": {"temperature_a": {"ip": "192.168.1.10", "register": 40001}}
    })

    assert as_text == anomaly_config.build_anomaly_config(REQ)
    assert as_map["production_line"]["sensors"] == [{
        "id": "temperature_a", "protocol": "modbus",
        "ip": "192.168.1.10", "register": 40001,
    }]


def test_no_devices_means_no_zone():
    assert anomaly_config.build_anomaly_config({"production_type": "x"}) == {}
    assert anomaly_config.build_anomaly_config({"sensors": [], "cameras": []}) == {}
    assert anomaly_config.build_anomaly_config(None) == {}
    assert anomaly_config.build_anomaly_config("not json") == {}


def test_zone_name_falls_back_to_production_type_then_a_constant():
    assert list(anomaly_config.build_anomaly_config(REQ)) == ["линия_розлива"]
    assert list(anomaly_config.build_anomaly_config(
        {"sensors": [{"id": "s"}]})) == ["production_line"]


def test_bools_and_non_numeric_strings_are_not_addresses():
    config = anomaly_config.build_anomaly_config(
        {"sensors": [{"id": "s", "ip": "1.2.3.4", "port": True, "register": "M40001"}]}
    )
    sensor = config["production_line"]["sensors"][0]

    assert "port" not in sensor
    assert "register" not in sensor
    assert sensor["ip"] == "1.2.3.4"


def test_non_object_entries_are_skipped():
    config = anomaly_config.build_anomaly_config({
        "sensors": [{"id": "good"}, "мусор", 42, None],
    })
    assert [s["id"] for s in config["production_line"]["sensors"]] == ["good"]
