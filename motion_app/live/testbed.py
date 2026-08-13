from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "testbed.json"


@dataclass(frozen=True)
class ControllerConfig:
    ip: str
    bind_ip: str
    data_port: int
    output_directory: Path


@dataclass(frozen=True)
class SyncConfig:
    device_port: int
    interval_s: float
    sample_window: int
    ready_timeout_s: float


@dataclass(frozen=True)
class SdrConfig:
    enabled: bool
    port: int


@dataclass(frozen=True)
class SshConfig:
    username: str
    password: str
    management_prefix: str
    connect_timeout_s: int
    max_parallel: int
    remote_directory: str
    remote_python: str


@dataclass(frozen=True)
class DevicePlan:
    node: int
    source_id: int
    name: str
    management_ip: str
    data_ip: str
    sample_rate_hz: float
    sync_port: int
    sdr_enabled: bool
    sdr_ip: str
    sdr_port: int

    def ssh_host(self, ssh: SshConfig) -> str:
        return f"{ssh.username}@{self.management_ip}"


@dataclass(frozen=True)
class MotivePlan:
    enabled: bool
    server_ip: str
    client_ip: str
    use_multicast: bool
    body_names: dict[int, str]


@dataclass(frozen=True)
class TestbedConfig:
    path: Path
    controller: ControllerConfig
    sync: SyncConfig
    sdr: SdrConfig
    ssh: SshConfig
    device_network_prefix: str
    default_sample_rate_hz: float
    devices: tuple[DevicePlan, ...]
    motive: MotivePlan

    def select_devices(self, selector: str | None) -> tuple[DevicePlan, ...]:
        if selector is None:
            return self.devices
        selected = parse_node_selector(selector)
        by_node = {device.node: device for device in self.devices}
        missing = sorted(selected - by_node.keys())
        if missing:
            raise ValueError("Unknown or disabled node(s): " + ", ".join(map(str, missing)))
        return tuple(by_node[node] for node in sorted(selected))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return value


def _port(value: object, label: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError(f"{label} must be between 1024 and 65535")
    return port


def _ip(value: object, label: str, *, allow_any: bool = False) -> str:
    text = str(value)
    if allow_any and text == "0.0.0.0":
        return text
    try:
        ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid IP address: {text!r}") from exc
    return text


def parse_node_selector(text: str) -> set[int]:
    selected: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                raise ValueError(f"Descending node range is invalid: {token!r}")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(token))
    if not selected:
        raise ValueError("Node selector did not contain any nodes")
    return selected


def load_testbed(path: Path | str = DEFAULT_CONFIG_PATH) -> TestbedConfig:
    config_path = Path(path).expanduser().resolve()
    root = _mapping(json.loads(config_path.read_text(encoding="utf-8")), str(config_path))
    controller_raw = _mapping(root.get("controller"), "controller")
    sync_raw = _mapping(root.get("sync"), "sync")
    ssh_raw = _mapping(root.get("ssh"), "ssh")
    devices_raw = _mapping(root.get("devices"), "devices")
    sdr_raw = _mapping(root.get("sdr", {}), "sdr")
    motive_raw = _mapping(root.get("motive", {}), "motive")

    controller = ControllerConfig(
        ip=_ip(controller_raw.get("ip"), "controller.ip"),
        bind_ip=_ip(controller_raw.get("bind_ip", "0.0.0.0"), "controller.bind_ip", allow_any=True),
        data_port=_port(controller_raw.get("data_port", 7000), "controller.data_port"),
        output_directory=Path(str(controller_raw.get("output_directory", "udp_output"))).expanduser(),
    )
    sync = SyncConfig(
        device_port=_port(sync_raw.get("device_port", 7101), "sync.device_port"),
        interval_s=float(sync_raw.get("interval_s", 1.0)),
        sample_window=int(sync_raw.get("sample_window", 60)),
        ready_timeout_s=float(sync_raw.get("ready_timeout_s", 12.0)),
    )
    if sync.interval_s <= 0 or sync.sample_window < 5 or sync.ready_timeout_s <= 0:
        raise ValueError("Invalid sync settings")
    sdr = SdrConfig(
        enabled=bool(sdr_raw.get("enabled", True)),
        port=_port(sdr_raw.get("port", 55555), "sdr.port"),
    )
    ssh = SshConfig(
        username=str(ssh_raw.get("username", "ucanlab")),
        password=str(ssh_raw.get("password", "")),
        management_prefix=str(ssh_raw.get("management_prefix", "192.168.2")).rstrip("."),
        connect_timeout_s=int(ssh_raw.get("connect_timeout_s", 5)),
        max_parallel=int(ssh_raw.get("max_parallel", 8)),
        remote_directory=str(ssh_raw.get("remote_directory", "/home/ucanlab/ucan_TB/udp_device_sender")),
        remote_python=str(ssh_raw.get("remote_python", "/usr/bin/python3")),
    )
    prefix = str(devices_raw.get("network_prefix", "192.168.2")).rstrip(".")
    default_rate = float(devices_raw.get("sample_rate_hz", 200.0))
    entries = _list(devices_raw.get("nodes"), "devices.nodes")
    devices: list[DevicePlan] = []
    seen_nodes: set[int] = set()
    seen_ids: set[int] = set()
    for entry in entries:
        node_data = {"node": entry} if isinstance(entry, int) and not isinstance(entry, bool) else _mapping(entry, "device node")
        node = int(node_data["node"])
        if not bool(node_data.get("enabled", True)):
            continue
        if node in seen_nodes:
            raise ValueError(f"Duplicate device node {node}")
        seen_nodes.add(node)
        source_id = int(node_data.get("source_id", node))
        if source_id in seen_ids:
            raise ValueError(f"Duplicate source_id {source_id}")
        seen_ids.add(source_id)
        data_ip = _ip(node_data.get("data_ip", f"{prefix}.{node}"), f"node {node} data_ip")
        management_ip = _ip(node_data.get("management_ip", f"{ssh.management_prefix}.{node}"), f"node {node} management_ip")
        rate = float(node_data.get("sample_rate_hz", default_rate))
        devices.append(DevicePlan(
            node=node,
            source_id=source_id,
            name=str(node_data.get("name", f"rpi_{node}")),
            management_ip=management_ip,
            data_ip=data_ip,
            sample_rate_hz=rate,
            sync_port=_port(node_data.get("sync_port", sync.device_port), f"node {node} sync_port"),
            sdr_enabled=bool(node_data.get("sdr_enabled", sdr.enabled)),
            sdr_ip=data_ip,
            sdr_port=int(node_data.get("sdr_port", sdr.port)),
        ))
    if not devices:
        raise ValueError("No enabled Raspberry Pi nodes are configured")

    names_raw = motive_raw.get("body_names", {})
    if not isinstance(names_raw, dict):
        raise ValueError("motive.body_names must be a JSON object")
    body_names = {int(key): str(value) for key, value in names_raw.items()}
    motive = MotivePlan(
        enabled=bool(motive_raw.get("enabled", False)),
        server_ip=_ip(motive_raw.get("server_ip", "127.0.0.1"), "motive.server_ip"),
        client_ip=_ip(motive_raw.get("client_ip", controller.ip), "motive.client_ip"),
        use_multicast=bool(motive_raw.get("use_multicast", True)),
        body_names=body_names,
    )
    return TestbedConfig(
        path=config_path,
        controller=controller,
        sync=sync,
        sdr=sdr,
        ssh=ssh,
        device_network_prefix=prefix,
        default_sample_rate_hz=default_rate,
        devices=tuple(sorted(devices, key=lambda d: d.node)),
        motive=motive,
    )


def override_testbed(
    config: TestbedConfig,
    *,
    controller_ip: str | None = None,
    bind_ip: str | None = None,
    data_port: int | None = None,
    output_directory: str | Path | None = None,
    device_network_prefix: str | None = None,
    management_prefix: str | None = None,
    sample_rate_hz: float | None = None,
    sdr_enabled: bool | None = None,
    sdr_port: int | None = None,
    motive_enabled: bool | None = None,
    motive_server_ip: str | None = None,
    motive_client_ip: str | None = None,
    motive_multicast: bool | None = None,
) -> TestbedConfig:
    controller = replace(
        config.controller,
        ip=controller_ip or config.controller.ip,
        bind_ip=bind_ip or config.controller.bind_ip,
        data_port=data_port if data_port is not None else config.controller.data_port,
        output_directory=Path(output_directory) if output_directory is not None else config.controller.output_directory,
    )
    ssh = replace(config.ssh, management_prefix=(management_prefix or config.ssh.management_prefix).rstrip("."))
    prefix = (device_network_prefix or config.device_network_prefix).rstrip(".")
    rate = sample_rate_hz if sample_rate_hz is not None else config.default_sample_rate_hz
    sdr = replace(
        config.sdr,
        enabled=config.sdr.enabled if sdr_enabled is None else sdr_enabled,
        port=sdr_port if sdr_port is not None else config.sdr.port,
    )
    devices = tuple(
        replace(
            device,
            data_ip=f"{prefix}.{device.node}",
            management_ip=f"{ssh.management_prefix}.{device.node}",
            sample_rate_hz=rate,
            sdr_enabled=sdr.enabled,
            sdr_ip=f"{prefix}.{device.node}",
            sdr_port=sdr.port,
        )
        for device in config.devices
    )
    motive = replace(
        config.motive,
        enabled=config.motive.enabled if motive_enabled is None else motive_enabled,
        server_ip=motive_server_ip or config.motive.server_ip,
        client_ip=motive_client_ip or config.motive.client_ip,
        use_multicast=config.motive.use_multicast if motive_multicast is None else motive_multicast,
    )
    return replace(
        config,
        controller=controller,
        ssh=ssh,
        sdr=sdr,
        device_network_prefix=prefix,
        default_sample_rate_hz=rate,
        devices=devices,
        motive=motive,
    )


def save_testbed(config: TestbedConfig, path: Path | str | None = None) -> Path:
    target = Path(path or config.path)
    payload = {
        "controller": {
            "ip": config.controller.ip,
            "bind_ip": config.controller.bind_ip,
            "data_port": config.controller.data_port,
            "output_directory": str(config.controller.output_directory),
        },
        "sync": {
            "device_port": config.sync.device_port,
            "interval_s": config.sync.interval_s,
            "sample_window": config.sync.sample_window,
            "ready_timeout_s": config.sync.ready_timeout_s,
        },
        "devices": {
            "network_prefix": config.device_network_prefix,
            "sample_rate_hz": config.default_sample_rate_hz,
            "nodes": [device.node for device in config.devices],
        },
        "sdr": {"enabled": config.sdr.enabled, "port": config.sdr.port},
        "motive": {
            "enabled": config.motive.enabled,
            "server_ip": config.motive.server_ip,
            "client_ip": config.motive.client_ip,
            "use_multicast": config.motive.use_multicast,
            "body_names": {str(k): v for k, v in sorted(config.motive.body_names.items())},
        },
        "ssh": {
            "username": config.ssh.username,
            "password": config.ssh.password,
            "management_prefix": config.ssh.management_prefix,
            "connect_timeout_s": config.ssh.connect_timeout_s,
            "max_parallel": config.ssh.max_parallel,
            "remote_directory": config.ssh.remote_directory,
            "remote_python": config.ssh.remote_python,
        },
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
