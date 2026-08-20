# Position Plotter

Position Plotter is a PySide6 application for loading Motive CSV files, plotting rigid-body signals, viewing recorded motion in 3D, receiving live Motive and Raspberry Pi data, recording live data, and exporting video.

## Installation

Install the Python packages from the project directory.

Windows:

```powershell
py -m pip install -r requirements.txt
```

Linux:

```bash
python3 -m pip install -r requirements.txt
```

For Raspberry Pi administration from Windows, OpenSSH client tools must be available. To install the configured SSH key on the Pis:

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

- `csv_data/` contains CSV input files. `test2.csv` is included.
- `csv_renders/` is available for rendered CSV-related output.
- `udp_output/` is the default live-recording directory and is created when needed.

## Recorded Motive CSV files

The Signal Plots, Recorded 3D, and Export tabs use Motive-style rigid-body CSV files.

The loader expects seven header rows. Rigid-body transform columns are identified from the Type, Name, transform, and dimension header rows. Supported rotation encodings are Quaternion and XYZ.

The live recorder writes Quaternion data in the same seven-row layout. Each rigid body receives these transform columns:

```text
Rotation X
Rotation Y
Rotation Z
Rotation W
Position X
Position Y
Position Z
```

After all transform columns, each rigid body receives one `Tracking Valid` column. A value of `1` means the body was tracked for that recorded frame. A value of `0` means the body was not tracked. Transform cells are left blank when tracking is invalid.

Live-recorded Motive frame numbers start at `0`. Time starts at `0` seconds and uses the elapsed receive time between recorded frames. This makes the recorded file directly usable by the playback loader.

## Live Raspberry Pi data

Enable **Raspberry Pis / GNU Radio** in the Live tab to receive Pi measurement packets and administer the selected Pi senders.

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

`devices.data_mode` in `testbed.json` selects the Pi measurement source:

- `test`: sends the repeating sequence `-1, 0, 1`.
- `sdr`: reads the latest float from the configured GNU Radio ZeroMQ publisher.

At 200 Hz, each Pi sends one packet every 5 ms.

All selected Pis send UTB4 measurement packets to the same multicast group and port. The source ID in each packet identifies the Pi. Each TC joins the multicast group on its configured local network interface.

## Live Motive data

Enable **Motive / NatNet** in the Live tab to receive rigid-body data.

The NatNet client uses:

```text
Command port:        1510
Data port:           1511
Multicast group:     239.255.42.99
```

Rigid-body names are read from Motive model definitions and associated with live rigid-body poses by rigid-body ID.

For same-machine unicast operation:

```text
Motive server IP:    127.0.0.1
Motive multicast:    unchecked
Motive transmission: Unicast
Motive interface:    Loopback
```

For multicast operation:

```text
Motive multicast:       checked
Motive transmission:    Multicast
Motive multicast group: 239.255.42.99
TC/local network IP:    local TC address, such as 10.1.1.51
```

If Motive runs on another computer, set **Motive server IP** to that computer's normal network address.

## Live recording

Enable **Record CSV files** to create a recording directory containing:

```text
pi_samples.csv
motive_rigid_bodies.csv
```

The **Recording rate** setting controls how often received data is written to disk. It does not limit receiving or Live rendering.

Available values:

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

`None` records every received Pi sample and Motive frame. A numeric rate limits each Pi independently and limits Motive by complete frame.

### `motive_rigid_bodies.csv`

The file uses the Motive-style seven-row header described above. Every recorded row contains one complete Motive frame. Invalid rigid-body transforms are blank and the corresponding `Tracking Valid` value is `0`.

### `pi_samples.csv`

The first column is `time_ns`. Each configured Pi has one value column, for example:

```text
time_ns,rpi_116,rpi_117,rpi_118
```

Each incoming Pi sample creates one row. The value is written only in that Pi's column. Other Pi columns remain blank on that row. This preserves the corrected timestamp of each independently received sample without treating separate Pi transmissions as simultaneous.

Relative recording paths are resolved from the directory containing `testbed.json`.

## Live communication controls

- **Install/update Pi sender before start** copies the sender, protocol module, and device configuration to each selected Pi.
- **Set Pi clocks before start** performs coarse Pi clock setting over SSH.
- **Leave Pi senders running when stopped** leaves the selected remote sender processes running after local communication stops.
- **Save settings to testbed.json** stores the current Live settings.
- **Start communication** starts the selected receivers and sources.
- **Stop** stops local receivers and stops selected Pi senders unless leave-running is enabled.

Pi install, set-time, start, and stop operations run concurrently for all selected Pis.

## Raspberry Pi command-line control

Install:

```powershell
py rpi_udp_controller.py install --nodes 116-120
```

Set time:

```powershell
py rpi_udp_controller.py set-time --nodes 116-120
```

Start:

```powershell
py rpi_udp_controller.py start --nodes 116-120
```

Stop:

```powershell
py rpi_udp_controller.py stop --nodes 116-120
```

Node selectors accept ranges and comma-separated values, such as `116-120` or `116,118,120`.

## Standalone live acquisition

Motive unicast:

```powershell
py run_rpi_motive_udp.py --no-pis --motive --motive-unicast --duration 10 --name motive_test
```

Motive multicast:

```powershell
py run_rpi_motive_udp.py --no-pis --motive --motive-multicast --duration 10 --name motive_multicast
```

Pi only:

```powershell
py run_rpi_motive_udp.py --pis --no-motive --nodes 116-120 --duration 10 --name pi_test
```

Pis and Motive:

```powershell
py run_rpi_motive_udp.py --pis --motive --nodes 116-120 --duration 30 --name combined
```

Record at 30 Hz:

```powershell
py run_rpi_motive_udp.py --pis --motive --recording-rate 30 --duration 30 --name combined_30hz
```

Record every received sample and frame:

```powershell
py run_rpi_motive_udp.py --pis --motive --recording-rate none --duration 30 --name combined_full
```

Use `--no-record` to disable CSV recording.

## `testbed.json`

The default configuration is:

```json
{
  "recording_rate_hz": null,
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
    "data_mode": "test",
    "nodes": [116, 117, 118, 119, 120]
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
    "remote_directory": "/home/ucanlab/ucan_TB/udp_device_sender",
    "remote_python": "/usr/bin/python3"
  }
}
```

`recording_rate_hz` accepts `null`, `120`, `60`, `30`, `15`, `10`, `5`, or `1`.

## File and function reference

### Root files

| File | Purpose and main entry points |
|---|---|
| `position_plotter_gui.pyw` | GUI entry point. `main()` creates the Qt application and main window. |
| `run_rpi_motive_udp.py` | Standalone live acquisition. `build_parser()` defines CLI settings and `main()` runs `LiveAcquisitionSession`. |
| `rpi_udp_controller.py` | Command-line entry point for Pi install, set-time, start, and stop operations. |
| `setup_windows_ssh.py` | Windows OpenSSH key setup entry point. |
| `testbed.json` | Live acquisition, network, Pi, Motive, SSH, and recording settings. |
| `rigid_body_types.csv` | Maps rigid-body names to application body types. |
| `requirements.txt` | Python package requirements. |

### `motion_app/core`

| File | Purpose and main functions |
|---|---|
| `app_types.py` | Shared data types including `BodyPose`, `SceneFrame`, and `RoomBounds`. |
| `body_config.py` | `load_body_type_map()` loads rigid-body type mappings. |
| `constants.py` | Shared signal and rendering constants. |
| `motive_io.py` | `load_motive_rigid_body_csv()` loads Motive-style recorded CSV data into a `TrackingSession`. |
| `playback_controller.py` | `PlaybackController` manages playback time, seek, play, pause, speed, and looping. |
| `rigid_body_math.py` | Position-axis, quaternion, Euler, and rotation-matrix conversions. |
| `room_geometry.py` | Calculates 3D room bounds and tick spacing from recorded positions. |
| `signal_processing.py` | Missing-value interpolation, sample-rate estimation, and smoothing. |
| `tracking_data.py` | `TrackingDataProvider` supplies positions, rotations, signals, scene frames, and room bounds. |

### `motion_app/live`

| File | Purpose and main functions |
|---|---|
| `acquisition_session.py` | `LiveAcquisitionSession` coordinates Pi, Motive, and recording start/stop behavior. |
| `motive_receiver.py` | Converts NatNet model names and rigid-body frames into application `MotiveFrame` objects. |
| `natnet_client.py` | NatNet rigid-body command, unicast, multicast, model-definition, and frame handling. |
| `pi_receiver.py` | Joins the Pi multicast group, receives UTB4 data, performs RTT time synchronization, and stores latest samples. |
| `pi_sender.py` | Runs on each Pi, obtains test or GNU Radio values, multicasts UTB4 data, and responds to sync requests. |
| `protocol.py` | UTB4 data and UTBS synchronization packet encoding and decoding. |
| `recording.py` | Recording-rate limiting and background writing of Motive-style and Pi CSV files. |
| `rpi_udp_controller.py` | `RemoteController` performs Pi install, set-time, start, and stop through SSH/SCP. |
| `setup_windows_ssh.py` | Windows SSH key creation and installation helpers. |
| `testbed.py` | Configuration types plus load, override, save, and node-selector functions. |

### `motion_app/ui`

| File | Purpose and main classes |
|---|---|
| `main_window.py` | Creates the main application tabs and shared toolbar. |
| `tabs/signal_plot_tab.py` | Recorded signal plotting controls. |
| `tabs/recorded_3d_tab.py` | Recorded rigid-body 3D playback controls. |
| `tabs/live_tab.py` | Live source settings, communication controls, recording controls, and Live rendering. |
| `tabs/export_tab.py` | Video-export settings, preview, process control, and progress display. |
| `plotting/multi_axis_signal_plot.py` | Multi-axis signal rendering. |
| `widgets/body_selection.py` | Rigid-body selection controls. |
| `widgets/playback_controls.py` | Playback controls. |
| `widgets/render_settings.py` | Rendering settings. |
| `widgets/session_source.py` | Recorded file selection and loading. |
| `widgets/sidebar.py` | Shared sidebar sizing and text wrapping. |
| `widgets/signal_selection.py` | Signal selection controls. |
| `widgets/smoothing_controls.py` | Smoothing controls. |

### `motion_app/rendering`

| File | Purpose and main functions |
|---|---|
| `pyvista_scene.py` | Interactive PyVista rigid-body scene and frame updates. |
| `pyvista_helpers.py` | Body actors, labels, room axes, room box, camera framing, and annotation sizing. |
| `scene_style.py` | Scene styling constants. |

### `motion_app/geometry`

| File | Purpose and main functions |
|---|---|
| `body_geometry.py` | Supported rigid-body dimensions and mesh generation. |

### `motion_app/exporting`

| File | Purpose and main functions |
|---|---|
| `video_export.py` | FFmpeg discovery, encoding configuration, frame count, process creation, and frame writing. |
| `export_worker.py` | Off-screen PyVista rendering, GPU readback/compositing, and export execution. |

### `motion_app/support`

| File | Purpose and main functions |
|---|---|
| `dependency_check.py` | Reads `requirements.txt` and checks required Python imports before the GUI starts. |
