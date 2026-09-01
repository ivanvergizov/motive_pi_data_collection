from __future__ import annotations

import argparse
import time
from pathlib import Path

from motion_app.live.acquisition_session import LiveAcquisitionSession
from motion_app.live.testbed import DEFAULT_CONFIG_PATH, load_testbed, override_testbed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run controller-side SDR and Motive acquisition without the GUI.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="override default testbed JSON path")
    parser.add_argument("--sdr", dest="use_sdr", action="store_true", help="run configured SDR ZMQ receivers")
    parser.add_argument("--motive", dest="use_motive", action="store_true", help="run Motive/NatNet receiver")
    parser.add_argument("--motive-multicast", dest="motive_use_multicast", action="store_true", help="override motive.use_multicast and receive Motive frames by multicast")
    parser.add_argument("--motive-unicast", dest="motive_use_multicast", action="store_false", help="override motive.use_multicast and receive Motive frames by unicast")
    parser.set_defaults(motive_use_multicast=None)
    parser.add_argument("--duration", type=float, default=0.0, help="seconds; 0 until Ctrl+C")
    parser.add_argument("--name", default="live", help="recording name")
    parser.add_argument("--output-directory", help="override controller.output_directory")
    parser.add_argument("--no-record", action="store_true", help="do not write CSV files")
    parser.add_argument(
        "--motive-recording-rate",
        choices=["none", "120", "60", "30", "15", "10", "5", "1"],
        help="override motive.recording_rate_hz; none records every received Motive frame",
    )
    parser.add_argument("--sdr-recording-rate", type=float, help="override sdr.recording_rate_hz")
    parser.add_argument("--motive-interface-ip", help="override motive.interface_ip")
    parser.add_argument("--motive-server-ip", help="override motive.server_ip")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_testbed(args.config)
    use_sdr = args.use_sdr
    use_motive = args.use_motive
    recording_rate = (
        "unchanged"
        if args.motive_recording_rate is None
        else (None if args.motive_recording_rate == "none" else int(args.motive_recording_rate))
    )
    config = override_testbed(
        config,
        motive_interface_ip=args.motive_interface_ip,
        output_directory=args.output_directory,
        sdr_enabled=use_sdr,
        sdr_recording_rate_hz=args.sdr_recording_rate,
        motive_enabled=use_motive,
        motive_server_ip=args.motive_server_ip,
        motive_use_multicast=args.motive_use_multicast,
        motive_recording_rate_hz=recording_rate,
    )
    if not use_sdr and not use_motive:
        raise SystemExit("Nothing selected: pass --sdr, --motive, or both.")

    session = LiveAcquisitionSession(
        config,
        use_sdr=use_sdr,
        use_motive=use_motive,
        record=not args.no_record,
        name=args.name,
    )
    result = session.start()
    if result.recording_directory is not None:
        print(f"Recording: {result.recording_directory}")
    started = time.monotonic()
    try:
        while args.duration <= 0 or time.monotonic() - started < args.duration:
            time.sleep(1.0)
            parts = []
            if use_sdr:
                samples = session.latest_sdr_samples()
                receiver_count = len(config.sdr.receivers)
                values = ", ".join(f"{node}={sample.value:.6g}" for node, sample in sorted(samples.items()))
                parts.append(f"SDR={len(samples)}/{receiver_count}" + (f" [{values}]" if values else ""))
                errors = [
                    f"{node}: {status.error}"
                    for node, status in session.sdr_status().items()
                    if status.error
                ]
                if errors:
                    parts.append("SDR errors=" + "; ".join(errors))
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
