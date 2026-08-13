from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from motion_app.core.body_config import load_body_type_map
from motion_app.core.constants import H264_RGB_LOSSLESS, H265_HIGH_QUALITY
from motion_app.core.motive_io import RigidBodyData, TrackingSession
from motion_app.core.room_geometry import calculate_room_bounds
from motion_app.core.tracking_data import TrackingDataProvider, nearest_sample_index
from motion_app.exporting.video_export import VideoEncodingSettings, build_ffmpeg_command, export_frame_count
from motion_app.geometry.body_geometry import body_dimensions, create_body_geometry


def make_body() -> RigidBodyData:
    time_count = 5
    qx = np.zeros(time_count)
    qy = np.zeros(time_count)
    qz = np.zeros(time_count)
    qw = np.ones(time_count)
    px = np.asarray([0.0, 0.1, 0.2, 0.3, 0.4])
    py = np.asarray([1.0, 1.1, 1.2, 1.3, 1.4])
    pz = np.asarray([2.0, 2.1, 2.2, 2.3, 2.4])
    zeros = np.zeros(time_count)
    return RigidBodyData(
        name="Body",
        rotation_x=qx,
        rotation_y=qy,
        rotation_z=qz,
        rotation_w=qw,
        rotation_xyz_x=zeros.copy(),
        rotation_xyz_y=zeros.copy(),
        rotation_xyz_z=zeros.copy(),
        position_x=px,
        position_y=py,
        position_z=pz,
        pre_interpolation_rotation_x=qx.copy(),
        pre_interpolation_rotation_y=qy.copy(),
        pre_interpolation_rotation_z=qz.copy(),
        pre_interpolation_rotation_w=qw.copy(),
        pre_interpolation_rotation_xyz_x=zeros.copy(),
        pre_interpolation_rotation_xyz_y=zeros.copy(),
        pre_interpolation_rotation_xyz_z=zeros.copy(),
        pre_interpolation_position_x=px.copy(),
        pre_interpolation_position_y=py.copy(),
        pre_interpolation_position_z=pz.copy(),
    )


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = TrackingSession(
            frames=np.arange(5),
            time=np.linspace(0.0, 0.4, 5),
            bodies={"Body": make_body()},
            source_rotation_encoding="Quaternion",
        )
        self.data = TrackingDataProvider(self.session)

    def test_display_coordinates_are_x_z_y(self) -> None:
        np.testing.assert_allclose(self.data.display_positions["Body"][0], [0.0, 2.0, 1.0])

    def test_2d_position_signals_remain_source_coordinates(self) -> None:
        np.testing.assert_allclose(
            self.data.signal_values("Body", "Position Y", "interpolated", 0.25),
            self.session.bodies["Body"].position_y,
        )
        smoothed_y = self.data.signal_values("Body", "Position Y", "smoothed", 0.25)
        self.assertEqual(smoothed_y.shape, self.session.bodies["Body"].position_y.shape)
        self.assertGreater(float(np.nanmean(smoothed_y)), 0.9)

    def test_scene_frame(self) -> None:
        frame = self.data.scene_frame(0.2, 2, {"Body"}, False, 0.25)
        self.assertEqual(frame.frame_number, 2)
        np.testing.assert_allclose(frame.poses["Body"].position, [0.2, 2.2, 1.2])
        np.testing.assert_allclose(frame.poses["Body"].quaternion_xyzw, [0.0, 0.0, 0.0, 1.0])
        hidden = self.data.scene_frame(0.2, 2, set(), False, 0.25)
        self.assertEqual(hidden.poses, {})

    def test_unmapped_body_defaults_to_tetrahedron(self) -> None:
        self.assertEqual(self.data.body_display_settings["Body"].body_type, "tetrahedron")

    def test_body_type_mapping_is_applied_when_session_is_created(self) -> None:
        with patch("motion_app.core.tracking_data.load_body_type_map", return_value={"Body": "tablet"}):
            data = TrackingDataProvider(self.session)
        self.assertEqual(data.body_display_settings["Body"].body_type, "tablet")

    def test_body_type_can_still_be_changed_programmatically(self) -> None:
        self.data.set_body_type("Body", "raspberry_pi")
        self.assertEqual(self.data.body_display_settings["Body"].body_type, "raspberry_pi")

    def test_body_geometry_shapes_and_dimensions(self) -> None:
        tetra_vertices, tetra_faces = create_body_geometry("tetrahedron")
        pi_vertices, pi_faces = create_body_geometry("raspberry_pi")
        tablet_vertices, tablet_faces = create_body_geometry("tablet")
        mobile_vertices, mobile_faces = create_body_geometry("mobile")
        self.assertEqual(tetra_vertices.shape, (4, 3))
        self.assertEqual(tetra_faces.shape, (4, 3))
        self.assertEqual(pi_vertices.shape, (8, 3))
        self.assertEqual(pi_faces.shape, (12, 3))
        self.assertEqual(tablet_vertices.shape, (8, 3))
        self.assertEqual(tablet_faces.shape, (12, 3))
        self.assertEqual(mobile_vertices.shape, (8, 3))
        self.assertEqual(mobile_faces.shape, (12, 3))

        pi = body_dimensions("raspberry_pi")
        tablet = body_dimensions("tablet")
        mobile = body_dimensions("mobile")
        self.assertAlmostEqual(tablet.length, pi.length * 3.0)
        self.assertAlmostEqual(tablet.width, pi.width * 3.0)
        self.assertAlmostEqual(tablet.height, pi.height * 0.5)
        self.assertAlmostEqual(mobile.length, tablet.length * 0.5)
        self.assertAlmostEqual(mobile.width, tablet.width * 0.5)
        self.assertAlmostEqual(mobile.height, tablet.height)

    def test_body_type_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rigid_body_types.csv"
            path.write_text(
                "rigid_body_name,body_type\nPi 1,raspberry_pi\nScreen 1,tablet\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_body_type_map(path),
                {"Pi 1": "raspberry_pi", "Screen 1": "tablet"},
            )

    def test_nearest_sample_index(self) -> None:
        self.assertEqual(nearest_sample_index(self.session.time, 0.14), 1)
        self.assertEqual(nearest_sample_index(self.session.time, 0.16), 2)

    def test_room_bounds_contain_all_display_positions(self) -> None:
        bounds = calculate_room_bounds(self.data.display_positions, minimum_padding=0.1)
        positions = self.data.display_positions["Body"]
        self.assertLessEqual(bounds.x_min, float(np.min(positions[:, 0])))
        self.assertGreaterEqual(bounds.x_max, float(np.max(positions[:, 0])))
        self.assertLessEqual(bounds.y_min, float(np.min(positions[:, 1])))
        self.assertGreaterEqual(bounds.y_max, float(np.max(positions[:, 1])))
        self.assertLessEqual(bounds.z_min, float(np.min(positions[:, 2])))
        self.assertGreaterEqual(bounds.z_max, float(np.max(positions[:, 2])))


class VideoExportCommandTests(unittest.TestCase):
    def test_lossless_rgb_command(self) -> None:
        settings = VideoEncodingSettings(
            codec_name=H264_RGB_LOSSLESS,
            fps=60,
            width=1920,
            height=1080,
        )
        command = build_ffmpeg_command("ffmpeg", "output.mp4", settings)
        self.assertIn("libx264rgb", command)
        self.assertIn("0", command)
        self.assertIn("1920x1080", command)

    def test_export_frame_count_is_inclusive(self) -> None:
        self.assertEqual(export_frame_count(0.0, 1.0, 60), 61)
        self.assertEqual(export_frame_count(2.0, 2.0, 60), 1)

    def test_h265_command(self) -> None:
        settings = VideoEncodingSettings(
            codec_name=H265_HIGH_QUALITY,
            fps=30,
            width=1280,
            height=720,
        )
        command = build_ffmpeg_command("ffmpeg", "output.mp4", settings)
        self.assertIn("libx265", command)
        self.assertIn("1280x720", command)


if __name__ == "__main__":
    unittest.main()
