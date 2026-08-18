from __future__ import annotations

import argparse
import time
from pathlib import Path

from motion_app.live.acquisition_session import LiveAcquisitionSession
from motion_app.live.testbed import DEFAULT_CONFIG_PATH, load_testbed, override_testbed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pi/GNU Radio and Motive acquisition without the GUI.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="testbed JSON")
    parser.add_argument("--nodes", help="Pi nodes, e.g. 116-120")
    parser.add_argument("--pis", dest="use_pis", action="store_true", help="run Pi receiver/senders")
    parser.add_argument("--no-pis", dest="use_pis", action="store_false", help="do not run Pi receiver/senders")
    parser.add_argument("--motive", dest="use_motive", action="store_true", help="run Motive/NatNet receiver")
    parser.add_argument("--no-motive", dest="use_motive", action="store_false", help="do not run Motive/NatNet receiver")
    parser.add_argument("--motive-multicast", dest="motive_use_multicast", action="store_true", help="receive Motive frames by multicast")
    parser.add_argument("--motive-unicast", dest="motive_use_multicast", action="store_false", help="temporarily receive Motive frames by unicast")
    parser.set_defaults(use_pis=None, use_motive=None, motive_use_multicast=None)
    parser.add_argument("--duration", type=float, default=0.0, help="seconds; 0 until Ctrl+C")
    parser.add_argument("--name", default="live", help="recording name")
    parser.add_argument("--output-directory", help="recording directory")
    parser.add_argument("--no-record", action="store_true", help="do not write CSV files")
    parser.add_argument(
        "--recording-rate",
        choices=["none", "120", "60", "30", "15", "10", "5", "1"],
        help="limit CSV recording rate in Hz; none records every received sample",
    )
    parser.add_argument("--install", action="store_true", help="install Pi sender files first")
    parser.add_argument("--set-time", action="store_true", help="set Pi clocks before start")
    parser.add_argument("--leave-running", action="store_true", help="leave Pi senders running on exit")
    parser.add_argument("--controller-ip", help="override this TC local network IP")
    parser.add_argument("--data-port", type=int, help="override Pi UDP data port")
    parser.add_argument("--multicast-group", help="override Pi multicast group")
    parser.add_argument("--motive-server-ip", help="override Motive server IP")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_testbed(args.config)
    use_pis = config.devices_enabled if args.use_pis is None else args.use_pis
    use_motive = config.motive.enabled if args.use_motive is None else args.use_motive
    recording_rate = (
        "unchanged"
        if args.recording_rate is None
        else (None if args.recording_rate == "none" else int(args.recording_rate))
    )
    config = override_testbed(
        config,
        controller_ip=args.controller_ip,
        data_port=args.data_port,
        multicast_group=args.multicast_group,
        devices_enabled=use_pis,
        motive_enabled=use_motive,
        motive_server_ip=args.motive_server_ip,
        motive_use_multicast=args.motive_use_multicast,
        recording_rate_hz=recording_rate,
    )
    if not use_pis and not use_motive:
        raise SystemExit("Nothing selected: enable Pis or Motive in testbed.json or with command-line options.")
    devices = config.select_devices(args.nodes) if use_pis else ()
    session = LiveAcquisitionSession(
        config,
        devices,
        use_pis=use_pis,
        use_motive=use_motive,
        record=not args.no_record,
        name=args.name,
        install_pis=args.install,
        set_pi_time=args.set_time,
        leave_pis_running=args.leave_running,
    )
    result = session.start()
    if result.recording_directory is not None:
        print(f"Recording: {result.recording_directory}")
    started = time.monotonic()
    try:
        while args.duration <= 0 or time.monotonic() - started < args.duration:
            time.sleep(1.0)
            parts = []
            if use_pis:
                samples = session.latest_pi_samples()
                parts.append(f"Pis={len(samples)}/{len(devices)}")
            if use_motive:
                frame = session.latest_motive_frame()
                parts.append("Motive=waiting" if frame is None else f"Motive frame={frame.frame_number} bodies={len(frame.bodies)}")
            print(" | ".join(parts))
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()
