from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "testbed.json"


@dataclass(frozen=True)
class ControllerConfig:
    ip: str
    data_port: int
    multicast_group: str
    output_directory: Path


@dataclass(frozen=True)
class SyncConfig:
    device_port: int
    interval_s: float


@dataclass(frozen=True)
class SdrConfig:
    host: str
    port: int


@dataclass(frozen=True)
class SshConfig:
    username: str
    password: str
    connect_timeout_s: int
    remote_directory: str
    remote_python: str


@dataclass(frozen=True)
class DevicePlan:
    node: int
    data_ip: str

    def ssh_host(self, ssh: SshConfig) -> str:
        return f"{ssh.username}@{self.data_ip}"


@dataclass(frozen=True)
class MotivePlan:
    enabled: bool
    server_ip: str
    use_multicast: bool


@dataclass(frozen=True)
class TestbedConfig:
    path: Path
    controller: ControllerConfig
    sync: SyncConfig
    sdr: SdrConfig
    ssh: SshConfig
    recording_rate_hz: int | None
    devices_enabled: bool
    device_network_prefix: str
    default_sample_rate_hz: float
    device_data_mode: str
    devices: tuple[DevicePlan, ...]
    motive: MotivePlan

    def select_devices(self, selector: str | None) -> tuple[DevicePlan, ...]:
        if selector is None:
            return self.devices
        selected = parse_node_selector(selector)
        by_node = {device.node: device for device in self.devices}
        missing = sorted(selected - by_node.keys())
        if missing:
            raise ValueError("Unknown node(s): " + ", ".join(map(str, missing)))
        return tuple(by_node[node] for node in sorted(selected))


def _port(value: object, label: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} must be between 1 and 65535")
    return port


def _ip(value: object, label: str) -> str:
    text = str(value)
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid IP address: {text!r}") from exc
    if address.version != 4:
        raise ValueError(f"{label} must be IPv4")
    return text


def _multicast_ip(value: object, label: str) -> str:
    text = _ip(value, label)
    if not ipaddress.ip_address(text).is_multicast:
        raise ValueError(f"{label} must be a multicast address")
    return text


RECORDING_RATES = (120, 60, 30, 15, 10, 5, 1)


def _recording_rate(value: object) -> int | None:
    if value is None or str(value).strip().lower() == "none":
        return None
    rate = int(value)
    if rate not in RECORDING_RATES:
        raise ValueError("recording_rate_hz must be one of: None, 120, 60, 30, 15, 10, 5, 1")
    return rate


def _output_path(config_path: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()

def parse_node_selector(text: str) -> set[int]:
    selected: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first, last = (int(part) for part in token.split("-", 1))
            if last < first:
                raise ValueError(f"Descending node range is invalid: {token!r}")
            selected.update(range(first, last + 1))
        else:
            selected.add(int(token))
    if not selected:
        raise ValueError("Node selector did not contain any nodes")
    return selected


def _build_devices(nodes: list[int], prefix: str) -> tuple[DevicePlan, ...]:
    return tuple(
        DevicePlan(node=node, data_ip=_ip(f"{prefix}.{node}", f"node {node} IP"))
        for node in sorted(set(nodes))
    )


def load_testbed(path: Path | str = DEFAULT_CONFIG_PATH) -> TestbedConfig:
    config_path = Path(path).expanduser().resolve()
    root = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict):
        raise ValueError("testbed configuration must be a JSON object")

    controller_raw = dict(root.get("controller", {}))
    sync_raw = dict(root.get("sync", {}))
    devices_raw = dict(root.get("devices", {}))
    sdr_raw = dict(root.get("sdr", {}))
    motive_raw = dict(root.get("motive", {}))
    ssh_raw = dict(root.get("ssh", {}))
    recording_rate_hz = _recording_rate(root.get("recording_rate_hz"))

    controller = ControllerConfig(
        ip=_ip(controller_raw.get("ip", "10.1.1.51"), "controller.ip"),
        data_port=_port(controller_raw.get("data_port", 7000), "controller.data_port"),
        multicast_group=_multicast_ip(controller_raw.get("multicast_group", "239.255.10.1"), "controller.multicast_group"),
        output_directory=_output_path(config_path, controller_raw.get("output_directory", "udp_output")),
    )
    sync = SyncConfig(
        device_port=_port(sync_raw.get("device_port", 7101), "sync.device_port"),
        interval_s=float(sync_raw.get("interval_s", 1.0)),
    )
    if sync.interval_s <= 0:
        raise ValueError("sync.interval_s must be positive")

    sdr = SdrConfig(
        host=_ip(sdr_raw.get("host", "127.0.0.1"), "sdr.host"),
        port=_port(sdr_raw.get("port", 55555), "sdr.port"),
    )

    prefix = str(devices_raw.get("network_prefix", "10.1.1")).rstrip(".")
    sample_rate = float(devices_raw.get("sample_rate_hz", 200.0))
    if sample_rate <= 0:
        raise ValueError("devices.sample_rate_hz must be positive")
    data_mode = str(devices_raw.get("data_mode", "test")).strip().lower()
    if data_mode not in {"test", "sdr"}:
        raise ValueError("devices.data_mode must be either 'test' or 'sdr'")
    nodes_raw = devices_raw.get("nodes", [])
    if not isinstance(nodes_raw, list) or any(isinstance(node, bool) or not isinstance(node, int) for node in nodes_raw):
        raise ValueError("devices.nodes must be a list of integer node numbers")
    devices = _build_devices(nodes_raw, prefix)
    devices_enabled = bool(devices_raw.get("enabled", False))
    if devices_enabled and not devices:
        raise ValueError("Raspberry Pi acquisition is enabled but no Pi nodes are configured")

    motive = MotivePlan(
        enabled=bool(motive_raw.get("enabled", True)),
        server_ip=_ip(motive_raw.get("server_ip", "127.0.0.1"), "motive.server_ip"),
        use_multicast=bool(motive_raw.get("use_multicast", True)),
    )

    ssh = SshConfig(
        username=str(ssh_raw.get("username", "ucanlab")),
        password=str(ssh_raw.get("password", "")),
        connect_timeout_s=int(ssh_raw.get("connect_timeout_s", 5)),
        remote_directory=str(ssh_raw.get("remote_directory", "/home/ucanlab/ucan_TB/udp_device_sender")),
        remote_python=str(ssh_raw.get("remote_python", "/usr/bin/python3")),
    )

    return TestbedConfig(
        path=config_path,
        controller=controller,
        sync=sync,
        sdr=sdr,
        ssh=ssh,
        recording_rate_hz=recording_rate_hz,
        devices_enabled=devices_enabled,
        device_network_prefix=prefix,
        default_sample_rate_hz=sample_rate,
        device_data_mode=data_mode,
        devices=devices,
        motive=motive,
    )


def override_testbed(
    config: TestbedConfig,
    *,
    controller_ip: str | None = None,
    data_port: int | None = None,
    multicast_group: str | None = None,
    output_directory: str | Path | None = None,
    devices_enabled: bool | None = None,
    device_network_prefix: str | None = None,
    sample_rate_hz: float | None = None,
    device_data_mode: str | None = None,
    sdr_host: str | None = None,
    sdr_port: int | None = None,
    motive_enabled: bool | None = None,
    motive_server_ip: str | None = None,
    motive_use_multicast: bool | None = None,
    recording_rate_hz: int | None | str = "unchanged",
) -> TestbedConfig:
    controller = replace(
        config.controller,
        ip=_ip(controller_ip, "controller.ip") if controller_ip else config.controller.ip,
        data_port=_port(data_port, "controller.data_port") if data_port is not None else config.controller.data_port,
        multicast_group=_multicast_ip(multicast_group, "controller.multicast_group") if multicast_group else config.controller.multicast_group,
        output_directory=_output_path(config.path, output_directory) if output_directory is not None else config.controller.output_directory,
    )
    prefix = (device_network_prefix or config.device_network_prefix).rstrip(".")
    rate = sample_rate_hz if sample_rate_hz is not None else config.default_sample_rate_hz
    if rate <= 0:
        raise ValueError("sample rate must be positive")
    data_mode = config.device_data_mode if device_data_mode is None else str(device_data_mode).strip().lower()
    if data_mode not in {"test", "sdr"}:
        raise ValueError("device data mode must be either 'test' or 'sdr'")
    sdr = replace(
        config.sdr,
        host=_ip(sdr_host, "sdr.host") if sdr_host else config.sdr.host,
        port=_port(sdr_port, "sdr.port") if sdr_port is not None else config.sdr.port,
    )
    devices = _build_devices([device.node for device in config.devices], prefix)
    motive = replace(
        config.motive,
        enabled=config.motive.enabled if motive_enabled is None else motive_enabled,
        server_ip=_ip(motive_server_ip, "motive.server_ip") if motive_server_ip else config.motive.server_ip,
        use_multicast=config.motive.use_multicast if motive_use_multicast is None else motive_use_multicast,
    )
    new_recording_rate = (
        config.recording_rate_hz
        if recording_rate_hz == "unchanged"
        else _recording_rate(recording_rate_hz)
    )
    return replace(
        config,
        controller=controller,
        sdr=sdr,
        recording_rate_hz=new_recording_rate,
        devices_enabled=config.devices_enabled if devices_enabled is None else devices_enabled,
        device_network_prefix=prefix,
        default_sample_rate_hz=rate,
        device_data_mode=data_mode,
        devices=devices,
        motive=motive,
    )


def save_testbed(config: TestbedConfig, path: Path | str | None = None) -> Path:
    target = Path(path or config.path).resolve()
    try:
        output_directory = config.controller.output_directory.relative_to(target.parent)
    except ValueError:
        output_directory = config.controller.output_directory
    payload = {
        "recording_rate_hz": config.recording_rate_hz,
        "controller": {
            "ip": config.controller.ip,
            "data_port": config.controller.data_port,
            "multicast_group": config.controller.multicast_group,
            "output_directory": str(output_directory),
        },
        "sync": {
            "device_port": config.sync.device_port,
            "interval_s": config.sync.interval_s,
        },
        "devices": {
            "enabled": config.devices_enabled,
            "network_prefix": config.device_network_prefix,
            "sample_rate_hz": config.default_sample_rate_hz,
            "data_mode": config.device_data_mode,
            "nodes": [device.node for device in config.devices],
        },
        "sdr": {
            "host": config.sdr.host,
            "port": config.sdr.port,
        },
        "motive": {
            "enabled": config.motive.enabled,
            "server_ip": config.motive.server_ip,
            "use_multicast": config.motive.use_multicast,
        },
        "ssh": {
            "username": config.ssh.username,
            "password": config.ssh.password,
            "connect_timeout_s": config.ssh.connect_timeout_s,
            "remote_directory": config.ssh.remote_directory,
            "remote_python": config.ssh.remote_python,
        },
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
