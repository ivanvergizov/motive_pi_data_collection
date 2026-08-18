from __future__ import annotations

import socket
import struct
import threading
import unittest

from motion_app.live.natnet_client import (
    NAT_CONNECT,
    NAT_FRAMEOFDATA,
    NAT_MODELDEF,
    NAT_REQUEST_MODELDEF,
    NAT_SERVERINFO,
    NatNetRigidBodyClient,
)


_RIGID_BODY = struct.Struct("<i3f4ffh")


def _rigid_body_packet(body_id: int = 7) -> bytes:
    return _RIGID_BODY.pack(
        body_id,
        1.0, 2.0, 3.0,
        0.0, 0.0, 0.0, 1.0,
        0.0,
        1,
    )


def _legacy_rigid_body_description(name: str, body_id: int) -> bytes:
    # NatNet 3.x: name, ID, parent ID, offset XYZ, marker count,
    # then marker positions and active labels. Zero markers keeps the fixture tiny.
    return (
        name.encode("utf-8") + b"\0"
        + struct.pack("<ii3fi", body_id, 0, 0.0, 0.0, 0.0, 0)
    )


class MinimalNatNetParserTests(unittest.TestCase):
    def test_natnet_31_model_definition_walks_unsized_blocks(self) -> None:
        client = NatNetRigidBodyClient(server_ip="127.0.0.1", client_ip="127.0.0.1")
        client._natnet_version = (3, 1, 0, 0)

        marker_set = b"AllMarkers\0" + struct.pack("<i", 2) + b"A\0B\0"
        rigid_body = _legacy_rigid_body_description("Tablet", 7)
        camera = b"Prime13\0" + struct.pack("<3f4f", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        payload = (
            struct.pack("<i", 3)
            + struct.pack("<i", 0) + marker_set
            + struct.pack("<i", 1) + rigid_body
            + struct.pack("<i", 5) + camera
        )
        self.assertEqual(client._parse_model_definitions(memoryview(payload)), {7: "Tablet"})

    def test_natnet_31_frame_walks_unsized_marker_sections(self) -> None:
        client = NatNetRigidBodyClient(server_ip="127.0.0.1", client_ip="127.0.0.1")
        client._natnet_version = (3, 1, 0, 0)
        rigid_body = _rigid_body_packet()
        marker_set = (
            b"AllMarkers\0"
            + struct.pack("<i", 1)
            + struct.pack("<3f", 9.0, 8.0, 7.0)
        )
        unlabeled = struct.pack("<i3f", 1, 6.0, 5.0, 4.0)
        payload = (
            struct.pack("<ii", 42, 1)
            + marker_set
            + unlabeled
            + struct.pack("<i", 1)
            + rigid_body
        )
        frame = client._parse_frame(memoryview(payload))
        self.assertEqual(frame.frame_number, 42)
        self.assertEqual(len(frame.bodies), 1)
        self.assertEqual(frame.bodies[0].rigid_body_id, 7)
        self.assertTrue(frame.bodies[0].tracking_valid)
        self.assertEqual(frame.bodies[0].position, (1.0, 2.0, 3.0))

    def test_multicast_natnet_31_uses_same_parser(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        server.settimeout(2.0)
        server_port = server.getsockname()[1]
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        data_port = probe.getsockname()[1]
        probe.close()
        group = "239.255.42.99"
        names_received = threading.Event()
        frame_received = threading.Event()
        received_names = []
        received_frames = []

        model_payload = (
            struct.pack("<i", 1)
            + struct.pack("<i", 1)
            + _legacy_rigid_body_description("Tablet", 7)
        )
        frame_payload = (
            struct.pack("<i", 42)
            + struct.pack("<i", 0)
            + struct.pack("<i", 0)
            + struct.pack("<i", 1)
            + _rigid_body_packet()
        )

        def fake_motive() -> None:
            multicast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            multicast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
            multicast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            multicast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            try:
                packet, client_address = server.recvfrom(4096)
                message_id, _ = struct.unpack_from("<HH", packet, 0)
                self.assertEqual(message_id, NAT_CONNECT)
                server_info = bytearray(264)
                server_info[256:260] = bytes((2, 3, 0, 1))
                server_info[260:264] = bytes((3, 1, 0, 0))
                server.sendto(
                    struct.pack("<HH", NAT_SERVERINFO, len(server_info)) + server_info,
                    client_address,
                )
                packet, client_address = server.recvfrom(4096)
                message_id, _ = struct.unpack_from("<HH", packet, 0)
                self.assertEqual(message_id, NAT_REQUEST_MODELDEF)
                server.sendto(
                    struct.pack("<HH", NAT_MODELDEF, len(model_payload)) + model_payload,
                    client_address,
                )
                multicast.sendto(
                    struct.pack("<HH", NAT_FRAMEOFDATA, len(frame_payload)) + frame_payload,
                    (group, data_port),
                )
            finally:
                multicast.close()
                server.close()

        thread = threading.Thread(target=fake_motive, daemon=True)
        thread.start()
        client = NatNetRigidBodyClient(
            server_ip="127.0.0.1",
            client_ip="127.0.0.1",
            use_multicast=True,
            multicast_group=group,
            command_port=server_port,
            data_port=data_port,
            names_callback=lambda names: (received_names.append(names), names_received.set()),
            frame_callback=lambda frame: (received_frames.append(frame), frame_received.set()),
        )
        try:
            client.start()
            self.assertTrue(names_received.wait(1.0))
            self.assertTrue(frame_received.wait(1.0))
            self.assertEqual(received_names[0], {7: "Tablet"})
            self.assertEqual(received_frames[0].bodies[0].rigid_body_id, 7)
            self.assertIsNotNone(client._data_socket)
        finally:
            client.stop()
            thread.join(timeout=1.0)

    def test_unicast_natnet_31_server_end_to_end(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        server.settimeout(2.0)
        server_port = server.getsockname()[1]
        names_received = threading.Event()
        frame_received = threading.Event()
        received_names: list[dict[int, str]] = []
        received_frames = []

        model_payload = (
            struct.pack("<i", 1)
            + struct.pack("<i", 1)
            + _legacy_rigid_body_description("Tablet", 7)
        )
        frame_payload = (
            struct.pack("<i", 42)
            + struct.pack("<i", 0)   # marker sets
            + struct.pack("<i", 0)   # unlabeled markers
            + struct.pack("<i", 1)   # rigid bodies
            + _rigid_body_packet()
        )

        def fake_motive() -> None:
            try:
                packet, client_address = server.recvfrom(4096)
                message_id, _ = struct.unpack_from("<HH", packet, 0)
                self.assertEqual(message_id, NAT_CONNECT)

                server_info = bytearray(264)
                server_info[256:260] = bytes((2, 3, 0, 1))
                server_info[260:264] = bytes((3, 1, 0, 0))
                server.sendto(
                    struct.pack("<HH", NAT_SERVERINFO, len(server_info)) + server_info,
                    client_address,
                )

                packet, client_address = server.recvfrom(4096)
                message_id, _ = struct.unpack_from("<HH", packet, 0)
                self.assertEqual(message_id, NAT_REQUEST_MODELDEF)
                server.sendto(
                    struct.pack("<HH", NAT_MODELDEF, len(model_payload)) + model_payload,
                    client_address,
                )
                server.sendto(
                    struct.pack("<HH", NAT_FRAMEOFDATA, len(frame_payload)) + frame_payload,
                    client_address,
                )
            finally:
                server.close()

        thread = threading.Thread(target=fake_motive, daemon=True)
        thread.start()
        client = NatNetRigidBodyClient(
            server_ip="127.0.0.1",
            client_ip="10.1.1.51",
            use_multicast=False,
            command_port=server_port,
            names_callback=lambda names: (received_names.append(names), names_received.set()),
            frame_callback=lambda frame: (received_frames.append(frame), frame_received.set()),
        )
        try:
            client.start()
            self.assertTrue(names_received.wait(1.0))
            self.assertTrue(frame_received.wait(1.0))
            self.assertEqual(received_names[0], {7: "Tablet"})
            self.assertEqual(received_frames[0].bodies[0].rigid_body_id, 7)
            self.assertIsNone(client._data_socket)
            self.assertEqual(client.application_version, (2, 3, 0, 1))
            self.assertEqual(client.natnet_version, (3, 1, 0, 0))
        finally:
            client.stop()
            thread.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
