# Position Plotter

Position Plotter is a PySide6 application for loading Motive CSV files, plotting rigid-body signals, viewing recorded motion in 3D, receiving live Motive data and SDR power measurements, recording live data, and exporting video.

Live SDR acquisition is controller-native. The controller opens one ZeroMQ SUB connection for every configured SDR receiver Pi, keeps each receiver as a distinct source, and snapshots the latest value from every receiver at the configured controller-side SDR measurement rate. The previous Raspberry Pi UDP sender, clock-sync, SSH deployment, and `devices` configuration path is no longer used.

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

`pyzmq` is required for SDR acquisition because the controller connects directly to the GNU Radio ZeroMQ power publishers.

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

`csv_data/` contains Motive CSV input files such as `test2.csv`. `csv_renders/` is available for rendered CSV-related output. `live_csv_output/` is the default directory for live SDR and Motive CSV recordings.

## Live SDR power acquisition

Enable `SDR / GNU Radio power receivers` in the Live tab to collect power measurements directly from one or more receiver Pis.

Each configured receiver has three fields: a stable numeric `node` ID used for source attribution, a `host` name or IPv4 address, and the GNU Radio ZeroMQ `port`. The controller connects to each receiver at `tcp://host:port` simultaneously.

The receiver expects GNU Radio power messages containing one or more little-endian float32 values. For each newly received ZMQ message, the controller computes the arithmetic mean of every float32 value in that message. This matches `SDR_control/get_power_measurements.py`, which converts the newest ZMQ message to a float32 array and applies `np.average()`. The previous last-float decoder is retained only as a legacy helper and is not used for live values, recording, status, or display.

Incoming ZeroMQ data is consumed as quickly as it arrives and the newest per-message average is retained independently for each receiver. `get_power_measurements.py` does not contain a configurable averaging-duration/window: its `-t` option only delays repeated measurement reads. The number of float32 values inside each GNU Radio ZMQ message determines what is averaged by this application. `sdr.recording_rate_hz` is a controller-side sampling rate: at each sampling tick, the controller snapshots the newest available averaged value for every receiver. A slow receiver therefore retains its most recent value until it publishes another measurement; a receiver that has not produced its first valid value remains blank in the recording and is reported as waiting.

Receiver identity is never inferred from message arrival order. Every socket is permanently associated with the configured `node`, so measurements remain attributable to the correct Pi even when streams publish at different rates.

## SDR status and errors

The Live tab and standalone runner report how many configured SDR receivers have produced sampled data. The GUI also reports each receiver node as waiting, receiving with its current value, or in an error state.

ZeroMQ `connect()` is asynchronous, so a receiver that is powered off or has no publisher normally appears as waiting rather than producing an immediate connection error. Invalid payload sizes are reported against the specific receiver node without mixing that receiver with any other source.

## Live Motive data

Enable `Motive / NatNet` in the Live tab to receive rigid-body data.

The NatNet client uses command port 1510, data port 1511, and multicast group 239.255.42.99. Rigid-body names are read from Motive model definitions and associated with live poses by rigid-body ID.

In the Live tab, `Motive server IP` is the address of the computer running Motive/NatNet. `Controller interface IP` is the local controller address/interface used for NatNet traffic and multicast membership. For same-machine unicast operation, use a Motive server IP of `127.0.0.1`, disable Motive multicast, and use loopback networking. For multicast operation, enable Motive multicast and set `motive.interface_ip` to the controller address on the Motive network.

## Live recording

Enable `Record CSV files` to create a recording directory. Files are created only for the live sources selected for that run.

An SDR run writes:

```text
sdr_samples.csv
```

A Motive run writes:

```text
motive_rigid_bodies.csv
```

A combined run writes both files.

### `sdr_samples.csv`

The SDR file records one controller-side snapshot per sampling tick after at least one receiver has produced a measurement. Columns are permanently tied to receiver node IDs. For example:

```text
time_s,sdr_165,sdr_166
0.000000000,-41.25,-39.875
0.100000000,-41.50,-39.875
```

`time_s` is elapsed decimal seconds for the SDR recording and starts at `0.000000000` on the first recorded SDR snapshot, matching the relative-time convention used by the recorded Motive file. Every receiver represented in a row is sampled at the same controller tick. If a configured receiver has not produced any value yet, its cell is blank. `sdr.recording_rate_hz` controls this sampling and recording cadence and accepts any positive value up to 100000 Hz.

### `motive_rigid_bodies.csv`

The Motive file retains the existing Motive-style seven-row Quaternion layout. Every recorded row contains one complete Motive frame. Invalid rigid-body transforms are blank and the corresponding `Tracking Valid` value is `0`.

`motive.recording_rate_hz` controls only Motive CSV rate limiting. It accepts `null`, `120`, `60`, `30`, `15`, `10`, `5`, or `1`. `null` records every received Motive frame. This is intentionally separate from the SDR measurement rate.

The two rates do different jobs. `sdr.recording_rate_hz` controls how often the controller snapshots the latest averaged SDR value and therefore sets the SDR CSV row cadence. `motive.recording_rate_hz` only limits which already-received Motive frames are written to the Motive CSV; it does not change the NatNet receive rate or SDR cadence.

Relative recording paths are resolved from the directory containing `testbed.json`.

## Live GUI controls

The Live tab provides one SDR enable control, an SDR recording-rate control, and an editable receiver table. Use `Add receiver` to create another receiver row and `Remove selected` to delete selected rows. Each row exposes node, host, and ZeroMQ port directly.

The same tab contains the Motive settings, recording destination and Motive recording rate, save/start/stop controls, smoothing, and preview settings. `Save settings to testbed.json` writes the same configuration model used by the standalone acquisition command.

The former Pi-node range, Pi multicast network, Pi sample-rate, Pi clock setting, SSH install/update, and leave-sender-running controls have been removed because the controller no longer launches or receives from a separate Pi UDP sender process.

## Standalone live acquisition

The non-GUI entry point uses the same `LiveAcquisitionSession` and `SdrReceiver` implementation as the GUI.

SDR only:

```powershell
py run_sdr_motive.py --sdr --duration 10 --name sdr_test
```

Motive only:

```powershell
py run_sdr_motive.py --motive --motive-unicast --duration 10 --name motive_test
```

SDR and Motive:

```powershell
py run_sdr_motive.py --sdr --motive --duration 30 --name combined
```

Override the controller-side SDR sampling rate for one run:

```powershell
py run_sdr_motive.py --sdr --sdr-recording-rate 25 --duration 30 --name sdr_25hz
```

Limit Motive CSV recording to 30 Hz while leaving SDR at its configured rate:

```powershell
py run_sdr_motive.py --sdr --motive --motive-recording-rate 30 --duration 30 --name combined
```

Use `--motive-recording-rate none` to record every received Motive frame. Configuration-derived command-line options are described as overrides in `--help`; for example, `--sdr-recording-rate`, `--motive-recording-rate`, `--motive-interface-ip`, `--motive-server-ip`, and `--output-directory` replace the corresponding `testbed.json` value for that run. Use `--no-record` to disable CSV recording. There are intentionally no `--no-sdr` or `--no-motive` flags: the standalone runner starts only the sources explicitly named with `--sdr` and/or `--motive`, regardless of the saved GUI enabled state. Receiver node/host/port definitions still come from `sdr.receivers` in the selected config file, which prevents the GUI and command-line paths from maintaining separate receiver implementations.

## `testbed.json`

The current configuration shape is:

```json
{
  "controller": {
    "output_directory": "live_csv_output"
  },
  "sdr": {
    "enabled": true,
    "recording_rate_hz": 10.0,
    "receivers": [
      {
        "node": 165,
        "host": "10.1.1.165",
        "port": 55555
      },
      {
        "node": 166,
        "host": "10.1.1.166",
        "port": 55555
      }
    ]
  },
  "motive": {
    "enabled": true,
    "server_ip": "10.1.1.51",
    "interface_ip": "10.1.1.51",
    "use_multicast": false,
    "recording_rate_hz": null
  }
}
```

`testbed.schema.json` documents the machine-readable JSON Schema for the configuration. Runtime validation additionally rejects duplicate receiver node IDs and duplicate ZeroMQ endpoints, checks host/port/rate ranges, requires at least one receiver when SDR is enabled, and gives explicit migration errors for the removed `devices`, `sync`, `ssh`, `sdr.host`, `sdr.port`, top-level `recording_rate_hz`, and old `controller.ip` formats.

The old `devices` subsystem is intentionally not preserved as hidden compatibility configuration. Existing custom configs must migrate SDR endpoints into `sdr.receivers`. The old generic top-level `recording_rate_hz` becomes `motive.recording_rate_hz`; SDR always uses `sdr.recording_rate_hz`. The old `controller.ip` field is now `motive.interface_ip` because that local interface address is used only by NatNet networking.

## Recorded Motive CSV files

The Signal Plots, Recorded 3D, and Export tabs use Motive-style rigid-body CSV files. The loader expects seven header rows. Rigid-body transform columns are identified from the Type, Name, transform, and dimension header rows. Supported rotation encodings are Quaternion and XYZ.

The live Motive recorder writes Quaternion data in the same seven-row layout. Each rigid body receives Rotation X/Y/Z/W and Position X/Y/Z columns followed by a `Tracking Valid` column.

## Video export

Video export behavior is unchanged by the SDR refactor. The Export tab uses the recorded Motive CSV path, PyVista/VTK rendering, and FFmpeg encoding settings already present in the application.

## File and function reference

The SDR-related live implementation is now centered on these files:

`motion_app/live/testbed.py` defines the controller, SDR receiver list, Motive configuration, validation, load/override/save behavior, and migration errors.

`motion_app/live/sdr_receiver.py` owns all ZeroMQ receiver sockets, computes the per-message float32 average used everywhere in the application, retains the latest average per receiver, and runs the single controller-side SDR sampling scheduler.

`motion_app/live/acquisition_session.py` is the shared GUI/headless live backend and starts/stops SDR, Motive, and recording.

`motion_app/live/recording.py` writes attributed SDR snapshots to `sdr_samples.csv` and Motive frames to `motive_rigid_bodies.csv`.

`motion_app/ui/widgets/sdr_receivers.py` implements the add/remove/edit receiver table used by the Live tab.

`motion_app/ui/tabs/live_tab.py` binds GUI controls to the shared configuration and acquisition backend.

`run_sdr_motive.py` is the standalone controller-side SDR/Motive entry point.

The following legacy transport files are removed because no active feature depends on them: root `rpi_udp_controller.py`, root `setup_windows_ssh.py`, root `run_rpi_motive_udp.py`, `motion_app/live/pi_receiver.py`, `motion_app/live/pi_sender.py`, `motion_app/live/protocol.py`, `motion_app/live/rpi_udp_controller.py`, and `motion_app/live/setup_windows_ssh.py`.

All recorded-data plotting, 3D playback, Motive NatNet receiving, rendering, geometry, signal processing, and video export modules remain otherwise unchanged.
