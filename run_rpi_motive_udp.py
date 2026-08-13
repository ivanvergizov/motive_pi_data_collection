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
    parser.add_argument("--no-pis", action="store_true", help="do not run Pi receiver/senders")
    parser.add_argument("--motive", action="store_true", help="run Motive/NatNet receiver")
    parser.add_argument("--duration", type=float, default=0.0, help="seconds; 0 until Ctrl+C")
    parser.add_argument("--name", default="live", help="recording name")
    parser.add_argument("--output-directory", help="recording directory")
    parser.add_argument("--no-record", action="store_true", help="do not write CSV files")
    parser.add_argument("--install", action="store_true", help="install Pi sender files first")
    parser.add_argument("--set-time", action="store_true", help="set Pi clocks before start")
    parser.add_argument("--leave-running", action="store_true", help="leave Pi senders running on exit")
    parser.add_argument("--controller-ip", help="override controller destination IP")
    parser.add_argument("--bind-ip", help="override local Pi receiver bind IP")
    parser.add_argument("--data-port", type=int, help="override Pi UDP data port")
    parser.add_argument("--motive-server-ip", help="override Motive server IP")
    parser.add_argument("--motive-client-ip", help="override NatNet client IP")
    parser.add_argument("--unicast", action="store_true", help="use NatNet unicast")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_testbed(args.config)
    config = override_testbed(
        config,
        controller_ip=args.controller_ip,
        bind_ip=args.bind_ip,
        data_port=args.data_port,
        output_directory=args.output_directory,
        motive_enabled=args.motive,
        motive_server_ip=args.motive_server_ip,
        motive_client_ip=args.motive_client_ip,
        motive_multicast=False if args.unicast else None,
    )
    use_pis = not args.no_pis
    use_motive = args.motive
    if not use_pis and not use_motive:
        raise SystemExit("Nothing selected: enable Pis or pass --motive.")
    devices = config.select_devices(args.nodes) if use_pis else ()
    session = LiveAcquisitionSession(
        config,
        devices,
        use_pis=use_pis,
        use_motive=use_motive,
        record=not args.no_record,
        name=args.name,
        output_directory=args.output_directory,
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
                stats = session.pi_stats()
                total = sum(item["received"] for item in stats.values())
                missing = sum(item["missing"] for item in stats.values())
                parts.append(f"Pis={len(samples)}/{len(devices)} packets={total} missing={missing}")
            if use_motive:
                frame = session.latest_motive_frame()
                parts.append("Motive=waiting" if frame is None else f"Motive frame={frame.frame_number} bodies={len(frame.bodies)}")
            print(" | ".join(parts))
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
        if session.recorder is not None:
            print(f"CSV writer drops: {session.recorder.dropped_rows}")


if __name__ == "__main__":
    main()
