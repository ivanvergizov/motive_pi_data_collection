from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .natnet_client import NatNetRigidBodyClient, NatNetRigidBodyFrame
from .testbed import MotivePlan


@dataclass(frozen=True)
class RigidBodySample:
    rigid_body_id: int
    name: str
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    tracking_valid: bool


@dataclass(frozen=True)
class MotiveFrame:
    frame_number: int
    received_time_ns: int
    bodies: dict[int, RigidBodySample]


class MotiveReceiver:
    """Receive the rigid-body NatNet information used by the application."""

    def __init__(
        self,
        plan: MotivePlan,
        *,
        client_ip: str,
        frame_callback: Callable[[MotiveFrame], None] | None = None,
    ) -> None:
        self.frame_callback = frame_callback
        self._latest_lock = threading.Lock()
        self._latest: MotiveFrame | None = None
        self._body_names: dict[int, str] | None = None
        self._client = NatNetRigidBodyClient(
            server_ip=plan.server_ip,
            client_ip=client_ip,
            use_multicast=plan.use_multicast,
            frame_callback=self._receive_frame,
            names_callback=self._receive_names,
        )

    def _receive_names(self, names: dict[int, str]) -> None:
        self._body_names = names

    def _receive_frame(self, frame_data: NatNetRigidBodyFrame) -> None:
        if self._body_names is None:
            return
        bodies = {
            body.rigid_body_id: RigidBodySample(
                rigid_body_id=body.rigid_body_id,
                name=self._body_names.get(body.rigid_body_id, f"Rigid Body {body.rigid_body_id}"),
                position=body.position,
                rotation=body.rotation,
                tracking_valid=body.tracking_valid,
            )
            for body in frame_data.bodies
        }
        frame = MotiveFrame(frame_data.frame_number, time.time_ns(), bodies)
        with self._latest_lock:
            self._latest = frame
        if self.frame_callback is not None:
            self.frame_callback(frame)

    def start(self) -> None:
        self._client.start()

    def stop(self) -> None:
        self._client.stop()

    def latest_frame(self) -> MotiveFrame | None:
        with self._latest_lock:
            return self._latest
