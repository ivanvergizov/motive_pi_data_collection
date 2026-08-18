# Position Plotter

Position Plotter is a PySide6 application for loading recorded Motive CSV data, plotting signals, viewing rigid-body motion in 3D, receiving live Motive and Raspberry Pi data, recording live CSV data, and exporting rendered video.

## Installation

Install Python dependencies from the project directory:

```powershell
py -m pip install -r requirements.txt
```

On Linux:

```bash
python3 -m pip install -r requirements.txt
```

For Raspberry Pi control from Windows, OpenSSH client tools must be available. Run the SSH setup helper once if the Pis do not already accept passwordless SSH:

```powershell
py setup_windows_ssh.py --nodes 116-120
```

## Start the GUI

Windows:

```powershell
py position_plotter_gui.pyw
```

Linux:

```bash
python3 position_plotter_gui.pyw
```

The main window contains Signal Plots, Recorded 3D, Live, and Export tabs.

## Data folders

- `csv_data/` contains CSV data files used with the program. `test2.csv` is included here.
- `csv_renders/` is an empty workspace for CSV-render outputs.
- `udp_output/` is the default live-recording directory. It is created when a recording is started.

## Recorded CSV workflow

Use the session/file controls in the Signal Plots or Recorded 3D tab to select a Motive CSV file such as:

```text
csv_data/test2.csv
```

The loader reads rigid-body positions and rotations, exposes the available bodies/signals, and supplies the data to the plotting and 3D playback controls.

## Live communication settings

The Live tab uses `testbed.json` as its saved configuration.

### Raspberry Pis / GNU Radio

Enable **Raspberry Pis / GNU Radio** to receive Pi prediction packets and control the selected Pi senders.

Default settings:

```text
Pi nodes:             116-120
Pi data network:      10.1.1
Pi sample rate:       200 Hz
Pi multicast group:   239.255.10.1
Pi data port:         7000
Pi clock-sync port:   7101
GNU Radio host:       127.0.0.1
GNU Radio ZMQ port:   55555
TC/local network IP:  10.1.1.51
```

`data_mode` in `testbed.json` selects the Pi measurement source:

- `test` sends the repeating values `-1, 0, 1`.
- `sdr` reads the latest float from the configured GNU Radio ZeroMQ publisher.

At the default Pi sample rate of 200 Hz, one packet is sent every 5 ms.

### Motive / NatNet

Enable **Motive / NatNet** to receive rigid-body data.

The bundled client reads NatNet 3.x rigid-body descriptions and rigid-body frames. Rigid-body names are obtained from Motive model definitions and matched to live poses by rigid-body ID.

NatNet ports and multicast group used by the client:

```text
Command port:        1510
Data port:           1511
Multicast group:     239.255.42.99
```

For same-machine unicast testing:

```text
Motive server IP:    127.0.0.1
Motive multicast:    unchecked
Motive transmission: Unicast
Motive interface:    Loopback
```

For multicast operation:

```text
Motive multicast:    checked
Motive transmission: Multicast
Motive multicast:    239.255.42.99
TC/local network IP: local TC network address, e.g. 10.1.1.51
```

When Motive is on another computer, set **Motive server IP** to that computer's normal network address. Each Testbed Controller uses its own local network IP to join the multicast stream.

## Live recording

Enable **Record CSV files** in the Live tab to record received data.

The **Recording rate** control is independent of the Live rendering frame rate. Available values are:

```text
None
120 Hz
60 Hz
30 Hz
15 Hz
10 Hz
5 Hz
1 Hz
```

`None` records every received Pi sample and Motive frame. A numeric value limits only the rows sent to the background CSV writer. Acquisition and Live visualization continue to consume incoming data at full speed.

For Pi data, the limit is applied independently to each Pi source. For Motive, the limit is applied per frame and all rigid bodies from each selected frame are written together.

Live recordings contain:

```text
pi_samples.csv
motive_rigid_bodies.csv
```

The default output directory is `udp_output`. Relative output paths are resolved relative to `testbed.json`.

## Live communication controls

- **Install/update Pi sender before start** copies the current Pi sender, protocol module, and generated device configuration to the selected Pis.
- **Set Pi clocks before start** performs the SSH-based coarse clock setting before acquisition.
- **Leave Pi senders running when stopped** prevents the GUI Stop action from stopping the selected remote senders.
- **Save settings to testbed.json** writes the current Live settings.
- **Start communication** starts the selected receivers and sources.
- **Stop** stops local receivers and, unless leave-running is selected, stops the selected Pi senders.

## Raspberry Pi command-line control

Install the sender on selected Pis:

```powershell
py rpi_udp_controller.py install --nodes 116-120
```

Set their clocks:

```powershell
py rpi_udp_controller.py set-time --nodes 116-120
```

Start senders:

```powershell
py rpi_udp_controller.py start --nodes 116-120
```

Stop senders:

```powershell
py rpi_udp_controller.py stop --nodes 116-120
```

The controller performs operations in parallel. `ssh.max_parallel` defaults to `10`.

## Standalone live acquisition

Run live acquisition without the GUI using `run_rpi_motive_udp.py`.

Motive-only unicast test:

```powershell
py run_rpi_motive_udp.py --no-pis --motive --motive-unicast --duration 10 --name motive_test
```

Motive multicast:

```powershell
py run_rpi_motive_udp.py --no-pis --motive --motive-multicast --duration 10 --name motive_multicast
```

Pi-only acquisition:

```powershell
py run_rpi_motive_udp.py --pis --no-motive --nodes 116-120 --duration 10 --name pi_test
```

Run both sources:

```powershell
py run_rpi_motive_udp.py --pis --motive --nodes 116-120 --duration 30 --name combined
```

Limit CSV recording to 30 Hz:

```powershell
py run_rpi_motive_udp.py --pis --motive --recording-rate 30 --duration 30 --name combined_30hz
```

Record every received sample/frame:

```powershell
py run_rpi_motive_udp.py --pis --motive --recording-rate none --duration 30 --name combined_full
```

Use `--no-record` to disable CSV recording.

## `testbed.json`

The default configuration is:

```json
{
  "controller": {
    "ip": "10.1.1.51",
    "data_port": 7000,
    "multicast_group": "239.255.10.1",
    "output_directory": "udp_output"
  },
  "sync": {
    "device_port": 7101,
    "interval_s": 1.0
  },
  "devices": {
    "enabled": false,
    "network_prefix": "10.1.1",
    "sample_rate_hz": 200.0,
    "nodes": [116, 117, 118, 119, 120],
    "data_mode": "test"
  },
  "sdr": {
    "host": "127.0.0.1",
    "port": 55555
  },
  "motive": {
    "enabled": true,
    "server_ip": "127.0.0.1",
    "use_multicast": true
  },
  "ssh": {
    "username": "ucanlab",
    "password": "ucanlab",
    "connect_timeout_s": 5,
    "max_parallel": 10,
    "remote_directory": "/home/ucanlab/ucan_TB/udp_device_sender",
    "remote_python": "/usr/bin/python3"
  },
  "recording_rate_hz": null
}
```

`recording_rate_hz` may be `null`, `120`, `60`, `30`, `15`, `10`, `5`, or `1`.

## File and function reference

### Root files

| File | Purpose / primary entry points |
|---|---|
| `position_plotter_gui.pyw` | GUI entry point. `main()` creates the Qt application and `WorkspaceMainWindow`. |
| `run_rpi_motive_udp.py` | Standalone live receiver. `build_parser()` defines CLI options; `main()` loads settings and runs `LiveAcquisitionSession`. |
| `rpi_udp_controller.py` | Thin command-line entry point for the Pi controller implementation. |
| `setup_windows_ssh.py` | Thin command-line entry point for Windows SSH-key setup. |
| `testbed.json` | Saved Live acquisition, network, Pi, Motive, SSH, and recording-rate settings. |
| `rigid_body_types.csv` | Maps rigid-body names to application body types. |
| `requirements.txt` | Python package requirements. |

### `motion_app/core`

| File | Purpose / primary classes and functions |
|---|---|
| `app_types.py` | Shared data types: `PlotSignalSelection`, `CurveSpec`, `BodyDisplaySettings`, `BodyPose`, `SceneFrame`, `RoomBounds`. |
| `body_config.py` | `load_body_type_map()` loads rigid-body type mappings from CSV. |
| `constants.py` | Shared rendering constants plus `color_for_curve()` and `parse_preview_aa()`. |
| `motive_io.py` | Recorded Motive CSV loader. `load_motive_rigid_body_csv()` builds `TrackingSession`; `find_rotation_encoding()` identifies quaternion/Euler columns. |
| `playback_controller.py` | `PlaybackController` manages recorded playback time, frame position, play/pause, and looping. |
| `rigid_body_math.py` | Position-axis conversion and quaternion/Euler/rotation-matrix conversion functions. |
| `room_geometry.py` | `calculate_room_bounds()`, `calculate_room_axis_bounds()`, and tick-spacing calculations. |
| `signal_processing.py` | Missing-value filling, sample-rate estimation, position/quaternion smoothing, and smoothing-window conversion. |
| `tracking_data.py` | `TrackingDataProvider` supplies synchronized position/rotation samples; `nearest_sample_index()` locates samples by time. |

### `motion_app/live`

| File | Purpose / primary classes and functions |
|---|---|
| `acquisition_session.py` | `LiveAcquisitionSession` coordinates recorder, Pi receiver/controller, and Motive receiver. `start()` and `stop()` control a live session. |
| `motive_receiver.py` | `MotiveReceiver` combines NatNet model names and rigid-body frames into application `MotiveFrame` objects. |
| `natnet_client.py` | `NatNetRigidBodyClient` implements NatNet 3.x command, unicast, multicast, rigid-body model-definition, and rigid-body frame handling. |
| `pi_receiver.py` | `PiReceiver` joins the Pi multicast group, receives UTB4 measurements, runs the RTT clock exchange, and stores latest `PiSample` values. |
| `pi_sender.py` | Raspberry Pi sender. `run_sender()` emits test or SDR values to the shared multicast group and answers clock-sync requests. |
| `protocol.py` | Binary UTB4 data and UTBS synchronization packet pack/unpack functions. |
| `recording.py` | `CsvSessionRecorder` performs optional rate limiting and background CSV writing for Pi and Motive data. |
| `rpi_udp_controller.py` | `RemoteController` performs Pi install, set-time, start, and stop operations through SSH/SCP. |
| `setup_windows_ssh.py` | Windows OpenSSH key creation, installation, and verification helpers. |
| `testbed.py` | Configuration dataclasses plus `load_testbed()`, `override_testbed()`, `save_testbed()`, and node-selector parsing. |

### `motion_app/ui`

| File | Purpose / primary classes and functions |
|---|---|
| `main_window.py` | `WorkspaceMainWindow` creates the application tabs and shared toolbar behavior. |
| `tabs/signal_plot_tab.py` | `SignalPlotTab` controls recorded signal selection and plotting. |
| `tabs/recorded_3d_tab.py` | `Recorded3DPlaybackTab` controls recorded rigid-body 3D playback. |
| `tabs/live_tab.py` | `LivePlaybackTab` owns Live settings, communication controls, Live rendering, and current source status. |
| `tabs/export_tab.py` | `ExportTab` configures and starts video export. |
| `plotting/multi_axis_signal_plot.py` | `MultiAxisSignalPlot` renders one or more selected signals with independent axes. |
| `widgets/body_selection.py` | `BodySelectionWidget` selects displayed rigid bodies. |
| `widgets/playback_controls.py` | `PlaybackControlsWidget` contains playback-time controls. |
| `widgets/render_settings.py` | `RenderSettingsWidget` contains Live/preview rendering controls. |
| `widgets/session_source.py` | `SessionSourceWidget` selects and loads recorded sessions/files. |
| `widgets/sidebar.py` | `configure_sidebar()` applies shared scroll/wrapping behavior to sidebars. |
| `widgets/signal_selection.py` | `SignalSelectionWidget` selects plotted signal fields. |
| `widgets/smoothing_controls.py` | `SmoothingControlsWidget` configures smoothing enable/window values. |

### `motion_app/rendering`

| File | Purpose / primary classes and functions |
|---|---|
| `pyvista_scene.py` | `PyVistaRigidBodyScene` manages the interactive PyVista scene, body actors, labels, camera, and frame updates. |
| `pyvista_helpers.py` | Creates and updates body actors, labels, room bounds, camera framing, and DPI-sensitive annotations. |
| `scene_style.py` | Shared scene styling constants. |

### `motion_app/geometry`

| File | Purpose / primary classes and functions |
|---|---|
| `body_geometry.py` | `BodyDimensions`, `body_dimensions()`, and `create_body_geometry()` define supported rigid-body geometry. |

### `motion_app/exporting`

| File | Purpose / primary classes and functions |
|---|---|
| `video_export.py` | FFmpeg discovery, encoding settings, frame-count calculation, command construction, process start/finalization, and frame writing. |
| `export_worker.py` | Off-screen PyVista rendering, asynchronous GPU readback/compositing, FFmpeg queueing, and `run_export()`. |

### `motion_app/support`

| File | Purpose / primary classes and functions |
|---|---|
| `dependency_check.py` | Reads `requirements.txt`, checks required imports, and presents the dependency-install prompt when required packages are missing. |

### `tests`

| File | Purpose |
|---|---|
| `test_core.py` | Core coordinate, body geometry, frame-count, and related application tests. |
| `test_live_config.py` | Live configuration, recording path/rate, Pi stop behavior, and Motive-name tests. |
| `test_live_protocol.py` | UTB4/UTBS packet and Pi multicast receiver tests. |
| `test_natnet_minimal.py` | NatNet 3.x rigid-body model/frame parsing plus unicast and multicast transport tests. |
