# Motive + SDR data collection

One project with three entry points and one shared acquisition backend.

| Program | Entry point | Python dependencies |
| --- | --- | --- |
| Print one Motive frame and exit | `motive_one_frame.py` | Standard library only |
| Record Motive and/or SDR without a GUI | `run_sdr_motive.py` | `requirements.txt`: NumPy and pyzmq |
| Collect, plot, play back, and export with a GUI | `position_plotter_gui.py` | `requirements-gui.txt`, which includes `requirements.txt` |

Use Python 3.10 or newer. The commands below use the Windows `py` launcher;
on Linux, replace `py` with `python3`. Run commands from the project root.

## 1. Single-frame version

No package installation or `testbed.json` is needed.

```powershell
py motive_one_frame.py -s 10.1.1.51 -c 10.1.1.100
```

- `-s` / `--server-ip`: the computer running Motive.
- `-c` / `--controller-ip`: this computer's local IPv4 address on the NatNet network.
- `-m` / `--multicast`: use multicast; the default is unicast.
- `-t` / `--timeout`: seconds to wait for a frame after connecting; default `5`.
- `--command-port`: NatNet command port; default `1510`.
- `--data-port`: NatNet data port; default `1511` for multicast reception.
- `--multicast-group`: default `239.255.42.99`.

The program connects, prints the reported NatNet/Motive versions, prints the
first frame's rigid-body IDs, positions, quaternions, and tracking validity,
then exits. Body names are shown when model definitions have arrived.
The shared client supports NatNet 3.x.

```powershell
py motive_one_frame.py --help
```

## 2. Non-GUI version

Install only the acquisition dependencies:

```powershell
py -m pip install -r requirements.txt
```

Edit `testbed.json` for your network, then select the sources to run:

```powershell
py run_sdr_motive.py --motive
py run_sdr_motive.py --sdr
py run_sdr_motive.py --sdr --motive --duration 30 --name test_run
```

The program prints status once per second and records CSV files by default.
Stop with `Ctrl+C`, or use `--duration` for a timed run. Source selection is
explicit: the JSON `enabled` fields do not replace `--sdr` / `--motive` here.

| Flag | Purpose |
| --- | --- |
| `--config PATH` | Use a different configuration file |
| `--sdr` | Start the configured SDR receivers |
| `--motive` | Start the NatNet receiver |
| `--motive-unicast` / `--motive-multicast` | Override Motive transport |
| `--motive-server-ip IP` | Override the Motive computer's address |
| `--motive-interface-ip IP` | Override this computer's NatNet interface |
| `--sdr-recording-rate RATE` | Set the SDR snapshot rate in Hz |
| `--motive-recording-rate RATE` | `none`, `120`, `60`, `30`, `15`, `10`, `5`, or `1` |
| `--output-directory PATH` | Override the recording parent directory |
| `--name NAME` | Recording folder prefix; default `live` |
| `--duration SECONDS` | Stop after this duration; `0` runs until interrupted |
| `--no-record` | Receive and print status without saving CSVs |

```powershell
py run_sdr_motive.py --help
```

## 3. GUI version

Install the GUI requirements. This also installs the acquisition requirements:

```powershell
py -m pip install -r requirements-gui.txt
py position_plotter_gui.py
```

Use **New tab** to open a workspace:

- **Signals plot**: load a Motive CSV, select signals, and compare raw,
  interpolated, or smoothed values.
- **Recorded 3D playback**: load a Motive CSV and play back selected bodies.
- **Live playback**: select SDR and/or Motive, edit their settings, choose
  recording options, and start/stop communication. **Save settings to
  testbed.json** saves the live configuration.
- **Video export**: load a Motive CSV, select bodies and a time range, and
  export an MP4 with the selected resolution, frame rate, and rendering settings.

Live status updates twice per second. Hidden 3D previews skip drawing while
collection, recording, and the playback clock continue. Switching back to a
preview shows its current position.

Video export also requires FFmpeg with `libx264rgb` or `libx265` for the selected
codec. Put FFmpeg on `PATH` or select its executable in the Export workspace.
FFmpeg is not needed for collection, plotting, or playback.

## Shared backend and folder layout

```text
motive_one_frame.py ----------> motion_app/natnet_client.py
                                         ^
                                         |
run_sdr_motive.py ----------> motion_app/live/ <---------- GUI Live workspace
                              |          |
                         SDR / ZMQ    CSV recording
```

`motion_app/natnet_client.py` is the single NatNet transport/parser used by all
three programs. It imports only the standard library. `motion_app/live/`
adds SDR reception, configuration, and CSV recording; it imports no GUI code.
Both the non-GUI collector and GUI Live workspace use `LiveAcquisitionSession`.
The single-frame script uses the NatNet client directly, without a recording
session or SDR imports.

| File or folder | Role | Needed for |
| --- | --- | --- |
| `motion_app/__init__.py` | Package marker; deliberately empty | All three |
| `motion_app/natnet_client.py` | NatNet UDP transport and rigid-body parsing | All three |
| `motion_app/live/` | Live acquisition, SDR, configuration, CSV recording | Non-GUI and GUI |
| `motion_app/core/` | Recorded CSV loading, math, smoothing, playback | GUI |
| `motion_app/ui/` | Qt window, workspaces, and widgets | GUI |
| `motion_app/rendering/` | Shared PyVista scenes and rendering helpers | GUI |
| `motion_app/geometry/` | Display meshes and dimensions | GUI |
| `motion_app/exporting/` | Video rendering worker and FFmpeg integration | GUI |
| `motion_app/support/` | GUI dependency check | GUI |
| `testbed.json` | Network and recording settings | Non-GUI and GUI live collection |
| `rigid_body_types.csv` | Body-name to display-shape mapping | GUI; optional, defaults to tetrahedrons |
| `csv_data/` | Example Motive recording | Optional sample data |
| `live_csv_output/` | Generated recordings, when using the default output path | Runtime output |

### Keep only the single-frame version

Copy just these three files, preserving their relative paths:

```text
motive_one_frame.py
motion_app/
    __init__.py
    natnet_client.py
```

Everything else can be omitted, including the entire `motion_app/live/` folder,
all GUI folders, both requirements files, and configuration/sample CSV files.
This reduced copy runs with the Python standard library alone.

### Keep only the non-GUI version

Keep this tree:

```text
run_sdr_motive.py
motive_one_frame.py            # optional connectivity check
testbed.json
requirements.txt
motion_app/
    __init__.py
    natnet_client.py
    live/
        __init__.py
        acquisition_session.py
        motive_receiver.py
        recording.py
        sdr_receiver.py
        testbed.py
```

You can drop `position_plotter_gui.py`, `requirements-gui.txt`,
`rigid_body_types.csv`, `csv_data/`, and these entire folders:

```text
motion_app/core/
motion_app/ui/
motion_app/rendering/
motion_app/geometry/
motion_app/exporting/
motion_app/support/
```

Only NumPy and pyzmq are installed by `requirements.txt`. Qt, pandas, PyVista,
VTK, OpenGL, and FFmpeg are not required by this version. A recording output
directory is created when collection starts; it does not need to be copied.

The GUI uses all of the application folders above. Keep both requirements
files when using it. This README is useful with any of the three copies;
Git metadata is not needed to run any version.

## Configuration

The GUI Live workspace and non-GUI collector share `testbed.json`. Example:

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
    "interface_ip": "10.1.1.100",
    "use_multicast": false,
    "recording_rate_hz": null
  }
}
```

- `controller.output_directory`: recording parent directory. Relative paths
  are resolved beside the configuration file.
- `sdr.enabled` / `motive.enabled`: saved source selections for the GUI.
- `sdr.receivers`: one node ID and ZMQ host/port per receiver. Node IDs and
  endpoints must be unique.
- `sdr.recording_rate_hz`: how often the controller snapshots the latest SDR
  values; this does not change the GNU Radio publisher rate.
- `motive.server_ip`: the computer running Motive.
- `motive.interface_ip`: this computer's address on the NatNet network.
- `motive.use_multicast`: `false` for unicast, `true` for multicast.
- `motive.recording_rate_hz`: limit the recorded Motive frame rate, or `null`
  to record every received frame. Available limits are `120`, `60`, `30`,
  `15`, `10`, `5`, and `1` Hz.

Command-line overrides apply to the current run and do not save the JSON.

## Communication and recorded data

Motive uses NatNet UDP command traffic on port `1510`. In unicast mode the
client receives replies/frames on its command socket's local port; in
multicast mode it also listens on data port `1511` and joins `239.255.42.99`
through the configured local interface.

Each SDR node publishes a ZeroMQ TCP stream, normally on port `55555`.
The controller averages the `float32` values in the newest message and keeps
that measurement until another arrives. It snapshots all configured nodes at
`sdr.recording_rate_hz`.

A recorded run creates a folder containing the selected source files:

- `sdr_samples.csv`: elapsed seconds and one measurement column per SDR node.
- `motive_rigid_bodies.csv`: a Motive-style CSV with positions, XYZW
  quaternions, and tracking-valid columns, readable by the GUI.

SDR rows use controller snapshot time. Motive rows use controller receive
time. Each file currently measures elapsed seconds from its own first sample;
the two files do not yet preserve a common session time origin.
