from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motion_app.live.acquisition_session import LiveAcquisitionSession
from motion_app.live.motive_receiver import MotiveReceiver
from motion_app.live.rpi_udp_controller import NodeResult
from motion_app.live.recording import CsvSessionRecorder
from motion_app.live.pi_receiver import PiSample
from motion_app.live.natnet_client import NatNetRigidBody, NatNetRigidBodyFrame
from motion_app.live.testbed import MotivePlan, load_testbed, override_testbed


class LiveConfigurationTests(unittest.TestCase):
    def test_default_source_and_network_settings(self) -> None:
        config = load_testbed()
        self.assertFalse(config.devices_enabled)
        self.assertEqual(config.sdr.host, "127.0.0.1")
        self.assertTrue(config.motive.enabled)
        self.assertEqual(config.motive.server_ip, "127.0.0.1")
        self.assertTrue(config.motive.use_multicast)
        self.assertEqual(config.controller.ip, "10.1.1.51")
        self.assertEqual(config.device_network_prefix, "10.1.1")
        self.assertEqual(config.device_data_mode, "test")
        self.assertEqual(config.controller.multicast_group, "239.255.10.1")
        self.assertEqual(config.devices[0].data_ip, "10.1.1.116")
        self.assertIsNone(config.recording_rate_hz)
        self.assertEqual(config.ssh.max_parallel, 10)

    def test_pi_network_override_updates_pi_ips(self) -> None:
        config = override_testbed(load_testbed(), device_network_prefix="10.5.0")
        self.assertEqual(config.devices[0].data_ip, "10.5.0.116")

    def test_motive_transport_can_be_temporarily_switched_to_unicast(self) -> None:
        config = override_testbed(load_testbed(), motive_use_multicast=False)
        self.assertFalse(config.motive.use_multicast)

    def test_relative_output_directory_is_relative_to_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "testbed.json"
            config_path.write_text(
                '{"controller":{"output_directory":"udp_output"}}',
                encoding="utf-8",
            )
            config = load_testbed(config_path)
            self.assertEqual(config.controller.output_directory, Path(directory) / "udp_output")
            recorder = CsvSessionRecorder(config.controller.output_directory, "test")
            try:
                self.assertEqual(recorder.paths.directory.parent, Path(directory) / "udp_output")
            finally:
                recorder.close()

    def test_recording_rate_limits_disk_rows_without_changing_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = CsvSessionRecorder(directory, "rate", 120)
            times = [0, 5_000_000, 10_000_000, 15_000_000, 20_000_000, 25_000_000]
            try:
                with patch("motion_app.live.recording.time.monotonic_ns", side_effect=times):
                    for index in range(len(times)):
                        recorder.record_pi(PiSample(116, index, float(index)))
            finally:
                recorder.close()
            with recorder.paths.pi_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([float(row["value"]) for row in rows], [0.0, 2.0, 4.0, 5.0])


class PiRuntimeBehaviorTests(unittest.TestCase):
    def test_stop_stops_all_selected_pis_even_if_they_were_already_running(self) -> None:
        config = load_testbed()
        devices = config.select_devices("116-117")
        session = LiveAcquisitionSession(
            config,
            devices,
            use_pis=True,
            use_motive=False,
            record=False,
            name="test",
        )

        class FakeRemote:
            def __init__(self) -> None:
                self.stopped = ()

            def stop(self, device):
                return NodeResult(device.node, "stopped")

            def run_parallel(self, selected, operation):
                self.stopped = tuple(selected)
                return [operation(device) for device in self.stopped]

        fake = FakeRemote()
        session.remote = fake
        session.stop()
        self.assertEqual(fake.stopped, devices)

    def test_leave_running_skips_remote_stop(self) -> None:
        config = load_testbed()
        devices = config.select_devices("116")
        session = LiveAcquisitionSession(
            config,
            devices,
            use_pis=True,
            use_motive=False,
            record=False,
            name="test",
            leave_pis_running=True,
        )

        class FakeRemote:
            def run_parallel(self, selected, operation):
                raise AssertionError("remote stop should not run")

        session.remote = FakeRemote()
        session.stop()


class MotiveNameTests(unittest.TestCase):
    @staticmethod
    def _frame(body_id: int) -> NatNetRigidBodyFrame:
        return NatNetRigidBodyFrame(
            frame_number=1,
            bodies=(NatNetRigidBody(body_id, (1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0), True),),
        )

    def test_model_definition_name_is_used_in_live_frame(self) -> None:
        receiver = MotiveReceiver(MotivePlan(True, "127.0.0.1", True), client_ip="10.1.1.51")
        receiver._receive_names({7: "Tablet"})
        receiver._receive_frame(self._frame(7))
        self.assertEqual(receiver.latest_frame().bodies[7].name, "Tablet")


if __name__ == "__main__":
    unittest.main()
