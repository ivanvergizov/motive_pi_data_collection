from __future__ import annotations

import argparse
import json
import math
import select
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protocol import (
    SYNC_REQUEST_TYPE,
    SYNC_RESPONSE_TYPE,
    decode_sync_message,
    encode_sync_message,
    pack_data_packet,
)
from sdr_latest import LatestSdrMeasurement


@dataclass(frozen=True)
class SenderConfig:
    source_id: int
    source_name: str
    local_ip: str
    sync_port: int
    receiver_ip: str
    receiver_port: int
    sample_rate_hz: float
    sdr_enabled: bool
    sdr_ip: str
    sdr_port: int

    @property
    def sdr_endpoint(self) -> str:
        return f"tcp://{self.sdr_ip}:{self.sdr_port}"


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def load_config(path: Path) -> SenderConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = _mapping(raw, str(path))
    sdr = _mapping(data.get("sdr", {}), "sdr")
    config = SenderConfig(
        source_id=int(data["source_id"]),
        source_name=str(data["source_name"]),
        local_ip=str(data["local_ip"]),
        sync_port=int(data["sync_port"]),
        receiver_ip=str(data["receiver_ip"]),
        receiver_port=int(data["receiver_port"]),
        sample_rate_hz=float(data["sample_rate_hz"]),
        sdr_enabled=bool(sdr.get("enabled", False)),
        sdr_ip=str(sdr.get("ip", "127.0.0.1")),
        sdr_port=int(sdr.get("port", 55555)),
    )
    if not 1 <= config.source_id <= 65535:
        raise ValueError("source_id must be between 1 and 65535")
    if not 1024 <= config.sync_port <= 65535:
        raise ValueError("sync_port must be between 1024 and 65535")
    if not 1024 <= config.receiver_port <= 65535:
        raise ValueError("receiver_port must be between 1024 and 65535")
    if not 1024 <= config.sdr_port <= 65535:
        raise ValueError("sdr.port must be between 1024 and 65535")
    if config.sample_rate_hz <= 0.0:
        raise ValueError("sample_rate_hz must be positive")
    return config


def read_test_values(
    *,
    acquisition_time_ns: int,
    sequence: int,
) -> tuple[float, ...]:
    """Return one eight-value synthetic sample when SDR input is disabled."""
    time_s = acquisition_time_ns * 1.0e-9
    return (
        math.sin(2.0 * math.pi * 1.0 * time_s),
        math.cos(2.0 * math.pi * 0.5 * time_s),
        math.sin(2.0 * math.pi * 0.2 * time_s),
        float(sequence),
        0.0,
        0.0,
        0.0,
        0.0,
    )


def sdr_values(prediction: float) -> tuple[float, ...]:
    """Map the newest GNU Radio prediction into the UTB4 payload."""
    return (
        float(prediction),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def _handle_sync_requests(
    socket_udp: socket.socket,
    source_id: int,
    source_name: str,
) -> None:
    while True:
        try:
            data, requester = socket_udp.recvfrom(4096)
        except BlockingIOError:
            return

        t1_sender_receive_ns = time.time_ns()
        try:
            message = decode_sync_message(data)
        except (UnicodeDecodeError, ValueError):
            continue

        if message.get("type") != SYNC_REQUEST_TYPE:
            continue

        nonce = message.get("nonce")
        t0 = message.get("t0_receiver_send_ns")
        if not isinstance(nonce, str):
            continue
        if isinstance(t0, bool) or not isinstance(t0, int):
            continue

        response = {
            "type": SYNC_RESPONSE_TYPE,
            "source_id": source_id,
            "source_name": source_name,
            "nonce": nonce,
            "t0_receiver_send_ns": t0,
            "t1_sender_receive_ns": t1_sender_receive_ns,
            "t2_sender_send_ns": time.time_ns(),
        }
        socket_udp.sendto(encode_sync_message(response), requester)


def run_sender(config: SenderConfig) -> None:
    period_ns = int(round(1_000_000_000.0 / config.sample_rate_hz))
    destination = (config.receiver_ip, config.receiver_port)

    sdr_reader: LatestSdrMeasurement | None = None
    if config.sdr_enabled:
        sdr_reader = LatestSdrMeasurement(config.sdr_endpoint)
        print(f"Waiting for SDR prediction from {config.sdr_endpoint}", flush=True)
        first_time_ns, first_prediction = sdr_reader.wait()
        print(
            f"SDR input ready: prediction={first_prediction:g} "
            f"timestamp_ns={first_time_ns}",
            flush=True,
        )

    socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    socket_udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    socket_udp.bind((config.local_ip, config.sync_port))
    socket_udp.setblocking(False)

    print(
        f"{config.source_name} source_id={config.source_id} "
        f"bound to {config.local_ip}:{config.sync_port}",
        flush=True,
    )
    data_label = "SDR prediction data" if config.sdr_enabled else "test data"
    print(
        f"Sending {data_label} to {config.receiver_ip}:{config.receiver_port} "
        f"at {config.sample_rate_hz:.3f} Hz",
        flush=True,
    )
    print("Press Ctrl+C to stop.", flush=True)

    sequence = 0
    sent = 0
    send_errors = 0
    reschedule_events = 0
    started_ns = time.perf_counter_ns()
    next_sample_ns = started_ns
    next_status_ns = started_ns + 5_000_000_000

    try:
        while True:
            now_ns = time.perf_counter_ns()
            wait_s = max(0.0, (next_sample_ns - now_ns) * 1.0e-9)
            readable, _, _ = select.select(
                [socket_udp],
                [],
                [],
                min(wait_s, 0.05),
            )
            if readable:
                _handle_sync_requests(
                    socket_udp,
                    config.source_id,
                    config.source_name,
                )

            now_ns = time.perf_counter_ns()
            if now_ns < next_sample_ns:
                continue

            if sdr_reader is not None:
                measurement = sdr_reader.latest()
                if measurement is None:
                    continue
                acquisition_time_ns, prediction = measurement
                values = sdr_values(prediction)
            else:
                acquisition_time_ns = time.time_ns()
                values = read_test_values(
                    acquisition_time_ns=acquisition_time_ns,
                    sequence=sequence,
                )

            packet = pack_data_packet(
                source_id=config.source_id,
                sequence=sequence,
                sender_time_ns=acquisition_time_ns,
                values=values,
            )
            try:
                socket_udp.sendto(packet, destination)
                sent += 1
            except OSError as exc:
                send_errors += 1
                print(f"UDP send error: {exc}", flush=True)

            sequence += 1
            next_sample_ns += period_ns
            after_send_ns = time.perf_counter_ns()

            if after_send_ns - next_sample_ns > period_ns:
                reschedule_events += 1
                next_sample_ns = after_send_ns + period_ns

            if after_send_ns >= next_status_ns:
                elapsed_s = (after_send_ns - started_ns) * 1.0e-9
                print(
                    f"status elapsed={elapsed_s:.1f}s sent={sent} "
                    f"send_errors={send_errors} "
                    f"reschedules={reschedule_events}",
                    flush=True,
                )
                next_status_ns = after_send_ns + 5_000_000_000

    except KeyboardInterrupt:
        pass
    finally:
        socket_udp.close()

    elapsed_s = max(
        (time.perf_counter_ns() - started_ns) * 1.0e-9,
        1.0e-12,
    )
    print(f"Stopped {config.source_name}", flush=True)
    print(f"  Sent: {sent}", flush=True)
    print(f"  Send errors: {send_errors}", flush=True)
    print(f"  Reschedule events: {reschedule_events}", flush=True)
    print(f"  Effective rate: {sent / elapsed_s:.3f} Hz", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Raspberry Pi UDP sender.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("device_config.json"),
        help="sender JSON file (default: device_config.json)",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration and exit",
    )
    return parser

def main() -> None:
    arguments = build_parser().parse_args()
    config = load_config(arguments.config)
    if arguments.check_config:
        print("Configuration is valid")
        print(config)
        return
    run_sender(config)


if __name__ == "__main__":
    main()
