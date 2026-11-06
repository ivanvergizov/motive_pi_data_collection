from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "testbed.json"
RECORDING_RATES = (120, 60, 30, 15, 10, 5, 1)
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class ControllerConfig:
    output_directory: Path


@dataclass(frozen=True)
class SdrReceiverPlan:
    node: int
    host: str
    port: int

    @property
    def endpoint(self) -> str:
        return f"tcp://{self.host}:{self.port}"


@dataclass(frozen=True)
class SdrConfig:
    enabled: bool
    recording_rate_hz: float
    receivers: tuple[SdrReceiverPlan, ...]


@dataclass(frozen=True)
class MotivePlan:
    enabled: bool
    server_ip: str
    interface_ip: str
    use_multicast: bool
    recording_rate_hz: int | None


@dataclass(frozen=True)
class TestbedConfig:
    path: Path
    controller: ControllerConfig
    sdr: SdrConfig
    motive: MotivePlan


def _port(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer port")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} must be between 1 and 65535")
    return port


def _ip(value: object, label: str) -> str:
    text = str(value).strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid IP address: {text!r}") from exc
    if address.version != 4:
        raise ValueError(f"{label} must be IPv4")
    return text


def _host(value: object, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if "://" in text:
        raise ValueError(f"{label} must contain only a host name or IP address, not a URL")
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        if not _HOSTNAME_RE.fullmatch(text) or ".." in text:
            raise ValueError(f"{label} is not a valid host name or IP address: {text!r}")
        return text
    if address.version != 4:
        raise ValueError(f"{label} must be IPv4 when an IP address is used")
    return text


def _recording_rate(value: object) -> int | None:
    if value is None or str(value).strip().lower() == "none":
        return None
    if isinstance(value, bool):
        raise ValueError("recording_rate_hz must be a numeric rate or null")
    rate = int(value)
    if rate not in RECORDING_RATES:
        choices = ", ".join(map(str, RECORDING_RATES))
        raise ValueError(f"recording_rate_hz must be null or one of: {choices}")
    return rate


def _positive_rate(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive number")
    rate = float(value)
    if not 0.0 < rate <= 100000.0:
        raise ValueError(f"{label} must be greater than 0 and no more than 100000 Hz")
    return rate


def _output_path(config_path: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _receiver_from_value(value: object, index: int) -> SdrReceiverPlan:
    if isinstance(value, SdrReceiverPlan):
        node, host, port = value.node, value.host, value.port
    elif isinstance(value, Mapping):
        try:
            node, host, port = value["node"], value["host"], value["port"]
        except KeyError as exc:
            raise ValueError(f"sdr.receivers[{index}] is missing {exc.args[0]!r}") from exc
    elif isinstance(value, (tuple, list)) and len(value) == 3:
        node, host, port = value
    else:
        raise ValueError(f"sdr.receivers[{index}] must contain node, host, and port")

    if isinstance(node, bool):
        raise ValueError(f"sdr.receivers[{index}].node must be an integer")
    node_number = int(node)
    if not 1 <= node_number <= 65535:
        raise ValueError(f"sdr.receivers[{index}].node must be between 1 and 65535")
    return SdrReceiverPlan(
        node=node_number,
        host=_host(host, f"sdr.receivers[{index}].host"),
        port=_port(port, f"sdr.receivers[{index}].port"),
    )


def _sdr_receivers(values: object) -> tuple[SdrReceiverPlan, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("sdr.receivers must be a list")
    receivers = tuple(_receiver_from_value(value, index) for index, value in enumerate(values))

    nodes = [receiver.node for receiver in receivers]
    duplicate_nodes = sorted({node for node in nodes if nodes.count(node) > 1})
    if duplicate_nodes:
        raise ValueError("sdr.receivers contains duplicate node IDs: " + ", ".join(map(str, duplicate_nodes)))

    endpoints = [receiver.endpoint for receiver in receivers]
    duplicate_endpoints = sorted({endpoint for endpoint in endpoints if endpoints.count(endpoint) > 1})
    if duplicate_endpoints:
        raise ValueError("sdr.receivers contains duplicate endpoints: " + ", ".join(duplicate_endpoints))
    return receivers


def load_testbed(path: Path | str = DEFAULT_CONFIG_PATH) -> TestbedConfig:
    config_path = Path(path).expanduser().resolve()
    root = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict):
        raise ValueError("testbed configuration must be a JSON object")

    removed = [key for key in ("devices", "sync", "ssh") if key in root]
    if removed:
        names = ", ".join(removed)
        raise ValueError(
            f"Legacy testbed section(s) {names} are no longer supported. "
            "Configure controller-side SDR collection with sdr.enabled, "
            "sdr.recording_rate_hz, and sdr.receivers."
        )

    controller_raw = dict(root.get("controller", {}))
    sdr_raw = dict(root.get("sdr", {}))
    motive_raw = dict(root.get("motive", {}))

    if "host" in sdr_raw or "port" in sdr_raw:
        raise ValueError(
            "Legacy sdr.host/sdr.port configuration is no longer supported. "
            "Use sdr.receivers with one {node, host, port} object per receiver."
        )

    if "ip" in controller_raw:
        raise ValueError(
            "controller.ip has moved to motive.interface_ip because it is used only by NatNet networking."
        )
    controller = ControllerConfig(
        output_directory=_output_path(config_path, controller_raw.get("output_directory", "live_csv_output")),
    )

    sdr = SdrConfig(
        enabled=bool(sdr_raw.get("enabled", False)),
        recording_rate_hz=_positive_rate(sdr_raw.get("recording_rate_hz", 10.0), "sdr.recording_rate_hz"),
        receivers=_sdr_receivers(sdr_raw.get("receivers", [])),
    )
    if sdr.enabled and not sdr.receivers:
        raise ValueError("SDR acquisition is enabled but sdr.receivers is empty")

    if "recording_rate_hz" in root:
        raise ValueError(
            "Top-level recording_rate_hz has moved to motive.recording_rate_hz; "
            "SDR uses sdr.recording_rate_hz."
        )
    motive = MotivePlan(
        enabled=bool(motive_raw.get("enabled", True)),
        server_ip=_ip(motive_raw.get("server_ip", "127.0.0.1"), "motive.server_ip"),
        interface_ip=_ip(motive_raw.get("interface_ip", "10.1.1.51"), "motive.interface_ip"),
        use_multicast=bool(motive_raw.get("use_multicast", True)),
        recording_rate_hz=_recording_rate(motive_raw.get("recording_rate_hz")),
    )

    return TestbedConfig(
        path=config_path,
        controller=controller,
        sdr=sdr,
        motive=motive,
    )


def override_testbed(
    config: TestbedConfig,
    *,
    motive_interface_ip: str | None = None,
    output_directory: str | Path | None = None,
    sdr_enabled: bool | None = None,
    sdr_recording_rate_hz: float | None = None,
    sdr_receivers: Iterable[object] | None = None,
    motive_enabled: bool | None = None,
    motive_server_ip: str | None = None,
    motive_use_multicast: bool | None = None,
    motive_recording_rate_hz: int | None | str = "unchanged",
) -> TestbedConfig:
    controller = replace(
        config.controller,
        output_directory=(
            _output_path(config.path, output_directory)
            if output_directory is not None
            else config.controller.output_directory
        ),
    )
    receivers = config.sdr.receivers if sdr_receivers is None else _sdr_receivers(list(sdr_receivers))
    sdr = replace(
        config.sdr,
        enabled=config.sdr.enabled if sdr_enabled is None else bool(sdr_enabled),
        recording_rate_hz=(
            config.sdr.recording_rate_hz
            if sdr_recording_rate_hz is None
            else _positive_rate(sdr_recording_rate_hz, "sdr.recording_rate_hz")
        ),
        receivers=receivers,
    )
    if sdr.enabled and not sdr.receivers:
        raise ValueError("SDR acquisition is enabled but no SDR receivers are configured")

    motive = replace(
        config.motive,
        enabled=config.motive.enabled if motive_enabled is None else bool(motive_enabled),
        server_ip=_ip(motive_server_ip, "motive.server_ip") if motive_server_ip else config.motive.server_ip,
        interface_ip=(
            _ip(motive_interface_ip, "motive.interface_ip")
            if motive_interface_ip
            else config.motive.interface_ip
        ),
        use_multicast=config.motive.use_multicast if motive_use_multicast is None else bool(motive_use_multicast),
        recording_rate_hz=(
            config.motive.recording_rate_hz
            if motive_recording_rate_hz == "unchanged"
            else _recording_rate(motive_recording_rate_hz)
        ),
    )
    return replace(
        config,
        controller=controller,
        sdr=sdr,
        motive=motive,
    )


def save_testbed(config: TestbedConfig, path: Path | str | None = None) -> Path:
    target = Path(path or config.path).resolve()
    try:
        output_directory = config.controller.output_directory.relative_to(target.parent)
    except ValueError:
        output_directory = config.controller.output_directory

    payload = {
        "controller": {
            "output_directory": str(output_directory),
        },
        "sdr": {
            "enabled": config.sdr.enabled,
            "recording_rate_hz": config.sdr.recording_rate_hz,
            "receivers": [
                {"node": receiver.node, "host": receiver.host, "port": receiver.port}
                for receiver in config.sdr.receivers
            ],
        },
        "motive": {
            "enabled": config.motive.enabled,
            "server_ip": config.motive.server_ip,
            "interface_ip": config.motive.interface_ip,
            "use_multicast": config.motive.use_multicast,
            "recording_rate_hz": config.motive.recording_rate_hz,
        },
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
