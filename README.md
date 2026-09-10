# Motive + SDR Data Collection GUI

This project supports three ways to collect or inspect live data:

1. the full GUI,
2. the simple command-line live acquisition program,
3. the single-frame NatNet diagnostic.

The sections below describe how to use each one, the network communication they rely on, and the files that implement them.

## Single-frame NatNet check

For the quickest Motive/NatNet connectivity test, run the included single-frame utility from the project root:

```powershell
py motive_data_collection_single_frame/single_frame.py -s <SERVER_IP> -c <CONTROLLER_IP>
```

Example:

```powershell
py motive_data_collection_single_frame/single_frame.py -s 10.1.1.51 -c 10.1.1.52
```

`-s` is the IP address of the computer running Motive/NatNet. `-c` is the local IP address of the computer running the script on the NatNet network. Unicast is used by default. Add `-m` for multicast.

The program performs the NatNet connection handshake, waits for one rigid-body frame, prints the frame number, rigid-body IDs, tracking-valid values, positions, and quaternions, then exits.

## Full GUI usage

### Install dependencies

Windows:

```powershell
py -m pip install -r requirements.txt
```

Linux:

```bash
python3 -m pip install -r requirements.txt
```

### Start the GUI

Windows:

```powershell
py position_plotter_gui.pyw
```

Linux:

```bash
python3 position_plotter_gui.pyw
```

The GUI contains Signal Plots, Recorded 3D, Live, and Export workspaces.

### Live workspace

The Live workspace starts and monitors Motive and SDR acquisition.

#### SDR inputs

- **Enable SDR receivers** — enables the configured GNU Radio/ZeroMQ receivers for the run.
- **SDR recording rate** — controller-side rate used to snapshot the newest measurement from all configured SDR receivers.
- **Node** — numeric identity for an SDR receiver. It is also used in the SDR CSV column name.
- **Host** — IP address or hostname of the machine publishing that receiver's ZeroMQ data.
- **Port** — ZeroMQ TCP port for that receiver, normally `55555`.
- **Add receiver / Remove selected** — edits the receiver list.

Each SDR receiver must have a unique node number and endpoint.

#### Motive inputs

- **Enable Motive / NatNet** — enables Motive/NatNet acquisition for the run.
- **Motive server IP** — IP address of the computer running Motive/NatNet.
- **Controller interface IP** — local IP address of the computer running this program on the network used for NatNet communication.
- **Motive multicast** — unchecked for unicast; checked for multicast.
- **Motive recording rate** — limits how frequently received Motive frames are written. `None` records every received frame.

#### Recording inputs

- **Record CSV files** — enables live CSV recording.
- **Output directory** — parent directory for recording folders.
- **Run name** — prefix used in the recording directory name.

A run can produce:

```text
sdr_samples.csv
motive_rigid_bodies.csv
```

`sdr_samples.csv` contains elapsed time and one measurement column per configured SDR node. `motive_rigid_bodies.csv` contains Motive rigid-body position, quaternion, and tracking-valid data.

#### Starting and stopping

- **Save settings to testbed.json** saves the current live settings.
- **Start communication** starts the selected data sources.
- **Stop communication** stops the live session and finishes recording.

The status area reports the latest SDR receiver state and the newest Motive frame information.

### Signal Plots workspace

Use Signal Plots to inspect a recorded Motive CSV.

Main inputs:

- Motive CSV file
- rigid bodies and signals to plot
- raw, interpolated, or smoothed values
- smoothing window
- vertical scaling for position, Euler, and quaternion signals

### Recorded 3D workspace

Use Recorded 3D to play back a recorded Motive CSV.

Main inputs:

- Motive CSV file
- rigid bodies to display
- body display type
- smoothing settings
- playback time and speed
- preview frame rate

### Export workspace

Use Export to create a video from a recorded Motive CSV.

Main inputs:

- Motive CSV file
- output video file
- rigid bodies to include
- start and end time
- smoothing settings
- output resolution
- output frame rate
- MSAA/SSAA settings
- codec
- FFmpeg executable if it is not found automatically

## Simple command-line live acquisition

The same live Motive and SDR acquisition can be run without the GUI using `run_sdr_motive.py`.

At least one source must be selected explicitly.

### SDR only

```powershell
py run_sdr_motive.py --sdr
```

### Motive only

```powershell
py run_sdr_motive.py --motive
```

### SDR and Motive together

```powershell
py run_sdr_motive.py --sdr --motive
```

### Main flags

```text
--config PATH                 override the default testbed.json path
--sdr                         run the configured SDR receivers
--motive                      run the Motive/NatNet receiver
--motive-multicast            override Motive transport to multicast
--motive-unicast              override Motive transport to unicast
--output-directory PATH       override controller.output_directory
--duration SECONDS            stop after the specified duration; 0 runs until Ctrl+C
--name NAME                   recording/run name
--no-record                   run without writing CSV files
--motive-recording-rate RATE  override motive.recording_rate_hz
--sdr-recording-rate RATE     override sdr.recording_rate_hz
--motive-interface-ip IP      override motive.interface_ip
--motive-server-ip IP         override motive.server_ip
--status-interval SECONDS     set how often status is printed
```

The source-selection flags determine what is started for that command. Configuration values that are not overridden are read from `testbed.json`.

### Example with explicit Motive addresses

```powershell
py run_sdr_motive.py --motive --motive-unicast --motive-server-ip 10.1.1.51 --motive-interface-ip 10.1.1.52
```

### Example with both sources and a fixed duration

```powershell
py run_sdr_motive.py --sdr --motive --duration 30 --name test_run
```

### Run without recording

```powershell
py run_sdr_motive.py --sdr --motive --no-record
```

## Single-frame command-line inputs

The included single-frame utility can be used independently of both the GUI and `run_sdr_motive.py`.

Show its help:

```powershell
py motive_data_collection_single_frame/single_frame.py --help
```

Required flags:

```text
-s, --server-ip IP       NatNet server IP
-c, --controller-ip IP   local IPv4 address of this computer on the NatNet network
```

Optional flags:

```text
-m, --multicast          use multicast; unicast is the default
-t, --timeout SECONDS    frame wait timeout; default 5 seconds
--command-port PORT      NatNet command port; default 1510
--data-port PORT         NatNet data port; default 1511
--multicast-group IP     NatNet multicast group; default 239.255.42.99
```

Unicast example:

```powershell
py motive_data_collection_single_frame/single_frame.py -s 10.1.1.51 -c 10.1.1.52
```

Multicast example:

```powershell
py motive_data_collection_single_frame/single_frame.py -s 10.1.1.51 -c 10.1.1.52 -m
```

The program prints the NatNet/Motive versions after a successful handshake, waits for one frame, prints the rigid-body information from that frame, and exits.

## `testbed.json` inputs

The GUI and simple command-line live acquisition use `testbed.json`.

```json
{
  "controller": {
    "output_directory": "live_csv_output"
  },
  "sdr": {
    "enabled": true,
    "recording_rate_hz": 10.0,
    "receivers": [
      {"node": 165, "host": "10.1.1.165", "port": 55555},
      {"node": 166, "host": "10.1.1.166", "port": 55555}
    ]
  },
  "motive": {
    "enabled": true,
    "server_ip": "10.1.1.51",
    "interface_ip": "10.1.1.52",
    "use_multicast": false,
    "recording_rate_hz": null
  }
}
```

Main values:

- `controller.output_directory` — parent directory for live recordings.
- `sdr.enabled` — saved GUI SDR enabled state.
- `sdr.recording_rate_hz` — controller SDR snapshot/recording rate.
- `sdr.receivers[].node` — receiver identity and CSV column identity.
- `sdr.receivers[].host` — receiver's ZeroMQ host/IP.
- `sdr.receivers[].port` — receiver's ZeroMQ TCP port.
- `motive.enabled` — saved GUI Motive enabled state.
- `motive.server_ip` — Motive/NatNet server address.
- `motive.interface_ip` — local interface used for NatNet traffic.
- `motive.use_multicast` — `false` for unicast or `true` for multicast.
- `motive.recording_rate_hz` — Motive CSV recording-rate limit; `null` records every received frame.

## Network structure and communication

### Motive / NatNet

The computer running this program acts as the NatNet client. The computer running Motive acts as the NatNet server.

```text
Controller / client                         Motive / server
motive.interface_ip                         motive.server_ip
        |                                          |
        |------ NatNet command traffic ---------->| UDP 1510
        |<----- server/command responses ----------|
        |                                          |
        |<----- NatNet frame data -----------------|
```

The default NatNet command port is UDP `1510`. The default NatNet data port is UDP `1511`.

At connection startup the NatNet client sends a connection request and waits for server information. The full live client then obtains model definitions so rigid-body IDs can be associated with names and processes the incoming rigid-body frames.

Each rigid body provides:

- rigid-body ID
- X/Y/Z position
- quaternion X/Y/Z/W
- tracking-valid state

The application timestamps received Motive frames on the controller.

#### Unicast

With unicast selected, communication is directed between the configured client and server addresses. `motive.interface_ip` identifies the local controller interface and `motive.server_ip` identifies the Motive computer.

#### Multicast

With multicast selected, the client joins the NatNet multicast group `239.255.42.99` through `motive.interface_ip` and receives NatNet data on the multicast data path.

### Single-frame NatNet communication

The single-frame utility uses the same basic command-side connection information:

```text
single_frame.py
     |
     | NAT_CONNECT / UDP command traffic
     v
NatNet server
     |
     | server information
     v
single_frame.py
     |
     | first rigid-body frame
     v
print frame and exit
```

The utility does not record data or run the rest of the application. Its output is limited to the first frame it receives.

### SDR / GNU Radio

Each SDR receiver publishes measurement data through a ZeroMQ TCP endpoint.

```text
Receiver 165 / GNU Radio ---- TCP/ZMQ ----\
                                         \
Receiver 166 / GNU Radio ---- TCP/ZMQ -----> Controller
                                         /
Receiver N / GNU Radio ------ TCP/ZMQ ----/
```

The controller creates one ZeroMQ SUB socket for each configured receiver. Each socket remains associated with that receiver's configured node number.

A received ZMQ message is interpreted as an array of `float32` values. The values in the newest message are averaged to produce that receiver's current power measurement. The newest average is retained independently for each receiver.

`sdr.recording_rate_hz` controls how often the controller creates a snapshot of all current SDR values. It does not change the GNU Radio publication rate. If a receiver has not produced a newer value by the next snapshot, its most recently received value remains the current value.

### Recording

Live Motive and SDR recording is coordinated by the same acquisition session.

```text
SDR ZMQ receivers ----\
                       >---- LiveAcquisitionSession ---- CsvSessionRecorder ---- CSV files
Motive NatNet --------/
```

SDR rows use controller-side snapshot timing. Motive rows use controller receive timing. Recorded CSV time is represented as elapsed decimal seconds.

## Project folders, files, and main functions

### Top-level files

- `position_plotter_gui.pyw` — GUI entry point. Creates the Qt application and opens the main window.
- `run_sdr_motive.py` — simple command-line live acquisition entry point. Parses flags, loads configuration, starts the requested sources, prints status, and stops the session.
- `testbed.json` — Motive, SDR, and recording configuration used by the GUI and simple live runner.
- `testbed.schema.json` — schema for validating the configuration file.
- `requirements.txt` — Python package requirements for the full application.
- `rigid_body_types.csv` — mapping from Motive rigid-body names to display body types.
- `motive_data_collection_single_frame/` — standalone one-frame NatNet diagnostic included with the project.

### `motion_app/live/`

This folder contains the communication and live recording backend used by both the GUI and the simple command-line runner.

- `testbed.py` — configuration loading, validation, temporary overrides, and saving.
  - `load_testbed()` reads `testbed.json`.
  - `override_testbed()` applies command-line or GUI overrides.
  - `save_testbed()` writes current settings.
- `natnet_client.py` — low-level NatNet UDP communication and packet parsing.
  - creates command/data sockets,
  - performs the NatNet connection handshake,
  - receives server information and model definitions,
  - parses streamed rigid-body frames.
- `motive_receiver.py` — application-level Motive receiver.
  - associates body IDs with names,
  - timestamps frames,
  - stores the newest frame,
  - forwards frames to recording callbacks.
- `sdr_receiver.py` — ZeroMQ SDR receiver manager.
  - creates one SUB socket per receiver,
  - reads newest messages,
  - averages the `float32` values in each message,
  - retains the latest measurement per node,
  - creates controller-rate SDR snapshots.
- `acquisition_session.py` — shared live coordinator.
  - `start()` starts recording and the selected receivers.
  - `stop()` shuts down receivers and recording.
  - latest-value methods provide current Motive and SDR status to the GUI or CLI.
- `recording.py` — background CSV writer.
  - writes SDR snapshots to `sdr_samples.csv`,
  - writes Motive frames to `motive_rigid_bodies.csv`,
  - closes files after queued writes finish.

### `motive_data_collection_single_frame/`

- `single_frame.py` — parses the one-frame command-line flags, starts the minimal NatNet client, waits for one frame, prints it, and exits.
  - `ipv4()` validates IPv4 inputs.
  - `port()` validates UDP ports.
  - `build_parser()` defines the CLI flags.
  - `main()` controls the connection, wait, print, and shutdown sequence.
- `natnet_client.py` — minimal NatNet transport/parser for the diagnostic.
  - `NatNetSingleFrameClient.start()` creates sockets and performs the handshake.
  - `stop()` closes the connection resources.
  - `_send_connect()` sends the NatNet connection request.
  - `_send_keepalive()` maintains the unicast command connection while waiting.
  - `_receive_loop()` receives UDP packets.
  - `_process_packet()` routes supported NatNet packet types.
  - `_parse_server_info()` reads Motive/NatNet version information.
  - `_parse_frame()` extracts rigid-body information from one frame.
- `requirements.txt` — dependency information for the standalone single-frame diagnostic.

### `motion_app/ui/`

- `main_window.py` — main GUI window and workspace creation.
- `tabs/live_tab.py` — live acquisition controls, configuration saving, start/stop handling, and live status.
- `tabs/signal_plot_tab.py` — recorded Motive signal plotting.
- `tabs/recorded_3d_tab.py` — recorded 3D playback.
- `tabs/export_tab.py` — video export controls and worker management.
- `plotting/multi_axis_signal_plot.py` — multi-axis position, Euler, and quaternion plotting.
- `widgets/sdr_receivers.py` — SDR node/host/port editing table.
- `widgets/body_selection.py` — rigid-body selection controls.
- `widgets/signal_selection.py` — signal selection controls.
- `widgets/playback_controls.py` — playback time, speed, play, pause, and seek controls.
- `widgets/render_settings.py` — preview/export frame-rate and rendering inputs.
- `widgets/smoothing_controls.py` — smoothing enable and window inputs.
- `widgets/session_source.py` — Motive CSV file selection.
- `widgets/sidebar.py` — shared GUI sidebar behavior.

### `motion_app/core/`

- `app_types.py` — shared types used across the application.
- `motive_io.py` — loads recorded Motive CSV files.
- `tracking_data.py` — supplies tracking data to plotting, playback, and export.
- `signal_processing.py` — interpolation and smoothing of tracking signals.
- `rigid_body_math.py` — coordinate, quaternion, and Euler conversions.
- `playback_controller.py` — playback time, seek, and speed control.
- `body_config.py` — loads rigid-body display-type mappings.
- `room_geometry.py` — calculates room/display bounds.
- `constants.py` — shared plotting, rendering, and export constants.

### `motion_app/rendering/`

- `pyvista_scene.py` — interactive 3D scene used by live and recorded views.
- `pyvista_helpers.py` — body, room, camera, label, and scene-update helpers.
- `scene_style.py` — shared 3D scene style and sizing constants.

### `motion_app/geometry/`

- `body_geometry.py` — creates the body meshes displayed in 3D.

### `motion_app/exporting/`

- `video_export.py` — FFmpeg command construction and video frame delivery.
- `export_worker.py` — offscreen rendering process used during export.

### `motion_app/support/`

- `dependency_check.py` — checks the GUI/runtime Python dependencies before startup.
