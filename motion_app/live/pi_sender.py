from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from protocol import pack_data_packet, pack_sync_response, unpack_sync_request


@dataclass(frozen=True)
class SenderConfig:
    source_id: int
    local_ip: str
    sync_port: int
    multicast_group: str
    data_port: int
    sample_rate_hz: float
    data_mode: str
    sdr_endpoint: str


def load_config(path: Path) -> SenderConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return SenderConfig(
        source_id=int(data["source_id"]),
        local_ip=str(data["local_ip"]),
        sync_port=int(data["sync_port"]),
        multicast_group=str(data["multicast_group"]),
        data_port=int(data["data_port"]),
        sample_rate_hz=float(data["sample_rate_hz"]),
        data_mode=str(data.get("data_mode", "test")).strip().lower(),
        sdr_endpoint=str(data["sdr_endpoint"]),
    )


def _answer_sync_requests(sock: socket.socket, source_id: int) -> None:
    while True:
        try:
            data, requester = sock.recvfrom(256)
        except BlockingIOError:
            return
        t1 = time.time_ns()
        try:
            t0 = unpack_sync_request(data)
        except ValueError:
            continue
        sock.sendto(
            pack_sync_response(
                source_id=source_id,
                t0_receiver_send_ns=t0,
                t1_sender_receive_ns=t1,
                t2_sender_send_ns=time.time_ns(),
            ),
            requester,
        )


TEST_VALUES = (-1.0, 0.0, 1.0)


def run_sender(config: SenderConfig) -> None:
    if config.data_mode not in {"test", "sdr"}:
        raise ValueError("data_mode must be either 'test' or 'sdr'")

    period_ns = int(round(1_000_000_000.0 / config.sample_rate_hz))
    destination = (config.multicast_group, config.data_port)

    zmq_socket = None
    zmq_module = None
    if config.data_mode == "sdr":
        import zmq

        zmq_module = zmq
        zmq_socket = zmq.Context.instance().socket(zmq.SUB)
        zmq_socket.setsockopt(zmq.SUBSCRIBE, b"")
        zmq_socket.setsockopt(zmq.CONFLATE, 1)
        zmq_socket.connect(config.sdr_endpoint)

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(config.local_ip))
    udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    udp.bind((config.local_ip, config.sync_port))
    udp.setblocking(False)

    latest_time_ns: int | None = None
    latest_value: float | None = None
    next_sample_ns = time.perf_counter_ns()
    test_index = 0

    print(
        f"sender started source_id={config.source_id} mode={config.data_mode} "
        f"destination={config.multicast_group}:{config.data_port}",
        flush=True,
    )

    try:
        while True:
            _answer_sync_requests(udp, config.source_id)

            if zmq_socket is not None and zmq_module is not None:
                try:
                    message = zmq_socket.recv(flags=zmq_module.NOBLOCK)
                except zmq_module.Again:
                    message = None
                if message is not None and len(message) >= 4 and len(message) % 4 == 0:
                    latest_value = float(struct.unpack_from("<f", message, len(message) - 4)[0])
                    latest_time_ns = time.time_ns()

            now_ns = time.perf_counter_ns()
            if now_ns >= next_sample_ns:
                if config.data_mode == "test":
                    sample_time_ns = time.time_ns()
                    sample_value = TEST_VALUES[test_index]
                    test_index = (test_index + 1) % len(TEST_VALUES)
                    udp.sendto(
                        pack_data_packet(
                            source_id=config.source_id,
                            sender_time_ns=sample_time_ns,
                            value=sample_value,
                        ),
                        destination,
                    )
                elif latest_time_ns is not None and latest_value is not None:
                    udp.sendto(
                        pack_data_packet(
                            source_id=config.source_id,
                            sender_time_ns=latest_time_ns,
                            value=latest_value,
                        ),
                        destination,
                    )
                next_sample_ns += period_ns
                if now_ns - next_sample_ns > period_ns:
                    next_sample_ns = now_ns + period_ns

            sleep_ns = next_sample_ns - time.perf_counter_ns()
            if sleep_ns > 0:
                time.sleep(min(sleep_ns * 1e-9, 0.002))
    except KeyboardInterrupt:
        pass
    finally:
        if zmq_socket is not None:
            zmq_socket.close(0)
        udp.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Raspberry Pi GNU Radio multicast sender.")
    parser.add_argument("--config", type=Path, default=Path("device_config.json"))
    config = load_config(parser.parse_args().config)
    run_sender(config)


if __name__ == "__main__":
    main()
