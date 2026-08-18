from __future__ import annotations

import socket
import threading
import unittest
from dataclasses import replace

from motion_app.live.pi_receiver import PiReceiver
from motion_app.live.protocol import (
    DATA_MAGIC,
    pack_data_packet,
    pack_sync_request,
    pack_sync_response,
    unpack_data_packet,
    unpack_sync_request,
    unpack_sync_response,
)
from motion_app.live.testbed import DevicePlan, load_testbed


class ProtocolTests(unittest.TestCase):
    def test_scalar_packet_round_trip(self) -> None:
        packet = unpack_data_packet(pack_data_packet(source_id=116, sender_time_ns=123456789, value=1.25))
        self.assertEqual(DATA_MAGIC, b"UTB4")
        self.assertEqual(packet.source_id, 116)
        self.assertEqual(packet.sender_time_ns, 123456789)
        self.assertAlmostEqual(packet.value, 1.25)

    def test_sync_round_trip(self) -> None:
        self.assertEqual(unpack_sync_request(pack_sync_request(10)), 10)
        response = unpack_sync_response(
            pack_sync_response(
                source_id=116,
                t0_receiver_send_ns=10,
                t1_sender_receive_ns=20,
                t2_sender_send_ns=21,
            )
        )
        self.assertEqual(response, (116, 10, 20, 21))

    def test_pi_multicast_receiver_accepts_shared_utb4_stream(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        data_port = probe.getsockname()[1]
        probe.close()
        config = load_testbed()
        config = replace(
            config,
            controller=replace(
                config.controller,
                ip="127.0.0.1",
                data_port=data_port,
                multicast_group="239.255.10.1",
            ),
            sync=replace(config.sync, device_port=data_port + 1),
        )
        received = []
        ready = threading.Event()
        receiver = PiReceiver(
            config,
            (DevicePlan(116, "127.0.0.1"),),
            sample_callback=lambda sample: (received.append(sample), ready.set()),
        )
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        try:
            receiver.start()
            sender.sendto(
                pack_data_packet(source_id=116, sender_time_ns=123, value=-1.0),
                (config.controller.multicast_group, data_port),
            )
            self.assertTrue(ready.wait(1.0))
            self.assertEqual(received[0].source_id, 116)
            self.assertEqual(received[0].value, -1.0)
        finally:
            receiver.stop()
            sender.close()


if __name__ == "__main__":
    unittest.main()
