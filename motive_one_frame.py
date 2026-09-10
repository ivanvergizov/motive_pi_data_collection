#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import threading


def ipv4(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid IPv4 address: {value}") from exc
    if address.version != 4:
        raise argparse.ArgumentTypeError("IPv4 address required")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connect to NatNet, print one rigid-body frame, and exit."
    )
    parser.add_argument(
        "-s", "--server-ip",
        required=True,
        type=ipv4,
        help="IP address of the computer running the NatNet server",
    )
    parser.add_argument(
        "-c", "--controller-ip",
        required=True,
        type=ipv4,
        help="local IP address of this computer on the NatNet network",
    )
    parser.add_argument(
        "-m", "--multicast",
        action="store_true",
        help="use multicast instead of the default unicast mode",
    )
    parser.add_argument(
        "-t", "--timeout",
        type=float,
        default=5.0,
        help="seconds to wait for one frame after connecting (default: 5)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0")

    # Import only the Motive/NatNet communication code from the main project.
    from motion_app.live.natnet_client import NatNetRigidBodyClient

    first_frame = None
    body_names: dict[int, str] = {}
    frame_received = threading.Event()

    def on_names(names: dict[int, str]) -> None:
        body_names.clear()
        body_names.update(names)

    def on_frame(frame) -> None:
        nonlocal first_frame
        if first_frame is None:
            first_frame = frame
            frame_received.set()

    client = NatNetRigidBodyClient(
        server_ip=args.server_ip,
        client_ip=args.controller_ip,
        use_multicast=args.multicast,
        frame_callback=on_frame,
        names_callback=on_names,
    )

    mode = "multicast" if args.multicast else "unicast"
    print(
        f"Connecting to {args.server_ip}:1510 from {args.controller_ip} "
        f"using {mode}..."
    )

    try:
        # start() performs the NatNet handshake before returning.
        client.start()

        natnet = ".".join(map(str, client.natnet_version or ())) or "unknown"
        motive = ".".join(map(str, client.application_version or ())) or "unknown"
        print(f"Handshake succeeded. NatNet={natnet}, Motive={motive}")
        print(f"Waiting up to {args.timeout:g} seconds for one frame...")

        if not frame_received.wait(args.timeout):
            print("Connected successfully, but no rigid-body frame was received.")
            return 2

        frame = first_frame
        if frame is None:
            print("Frame callback fired without frame data.")
            return 3

        print()
        print(f"Frame number: {frame.frame_number}")
        print(f"Rigid bodies: {len(frame.bodies)}")

        for body in frame.bodies:
            name = body_names.get(body.rigid_body_id, f"Rigid Body {body.rigid_body_id}")
            px, py, pz = body.position
            qx, qy, qz, qw = body.rotation

            print()
            print(name)
            print(f"  ID: {body.rigid_body_id}")
            print(f"  Tracking valid: {body.tracking_valid}")
            print(f"  Position: X={px:.6f}, Y={py:.6f}, Z={pz:.6f}")
            print(
                "  Quaternion: "
                f"X={qx:.6f}, Y={qy:.6f}, Z={qz:.6f}, W={qw:.6f}"
            )

        return 0

    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        client.stop()


if __name__ == "__main__":
    raise SystemExit(main())
