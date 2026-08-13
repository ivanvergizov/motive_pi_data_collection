from __future__ import annotations

import statistics
import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class SyncObservation:
    receiver_time_ns: int
    offset_sender_minus_receiver_ns: int
    round_trip_delay_ns: int


@dataclass(frozen=True)
class ClockEstimate:
    reference_receiver_time_ns: int
    offset_sender_minus_receiver_ns: int
    round_trip_delay_ns: int
    drift_ppm: float
    sample_count: int

    def offset_at(self, receiver_time_ns: int) -> int:
        elapsed_ns = receiver_time_ns - self.reference_receiver_time_ns
        drift_ns = int(round(elapsed_ns * self.drift_ppm * 1.0e-6))
        return self.offset_sender_minus_receiver_ns + drift_ns

    def correct_sender_time(
        self,
        sender_time_ns: int,
        receiver_reference_time_ns: int,
    ) -> int:
        return sender_time_ns - self.offset_at(receiver_reference_time_ns)


class ClockSynchronizer:
    """Estimate sender clock offset and slow drift from NTP-style exchanges.

    Positive offset means the sender clock is ahead of the receiver clock.
    A sender timestamp is converted to receiver time by subtracting the
    estimated offset.
    """

    def __init__(self, max_samples: int = 60) -> None:
        if max_samples < 5:
            raise ValueError("max_samples must be at least 5")
        self._samples: deque[SyncObservation] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    @staticmethod
    def observation_from_exchange(
        *,
        t0_receiver_send_ns: int,
        t1_sender_receive_ns: int,
        t2_sender_send_ns: int,
        t3_receiver_receive_ns: int,
    ) -> SyncObservation:
        offset_ns = int(
            round(
                (
                    (t1_sender_receive_ns - t0_receiver_send_ns)
                    + (t2_sender_send_ns - t3_receiver_receive_ns)
                )
                / 2.0
            )
        )
        rtt_ns = (
            (t3_receiver_receive_ns - t0_receiver_send_ns)
            - (t2_sender_send_ns - t1_sender_receive_ns)
        )
        return SyncObservation(
            receiver_time_ns=(t0_receiver_send_ns + t3_receiver_receive_ns) // 2,
            offset_sender_minus_receiver_ns=offset_ns,
            round_trip_delay_ns=max(0, rtt_ns),
        )

    def add_exchange(
        self,
        *,
        t0_receiver_send_ns: int,
        t1_sender_receive_ns: int,
        t2_sender_send_ns: int,
        t3_receiver_receive_ns: int,
    ) -> SyncObservation:
        observation = self.observation_from_exchange(
            t0_receiver_send_ns=t0_receiver_send_ns,
            t1_sender_receive_ns=t1_sender_receive_ns,
            t2_sender_send_ns=t2_sender_send_ns,
            t3_receiver_receive_ns=t3_receiver_receive_ns,
        )
        with self._lock:
            self._samples.append(observation)
        return observation

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def estimate(self) -> ClockEstimate | None:
        with self._lock:
            samples = list(self._samples)

        if not samples:
            return None

        # Low-RTT exchanges are least affected by queueing. Use up to the
        # best half, while retaining at least five samples when available.
        ordered = sorted(samples, key=lambda item: item.round_trip_delay_ns)
        keep_count = min(len(ordered), max(5, len(ordered) // 2))
        best = ordered[:keep_count]
        reference_time_ns = int(
            statistics.median(item.receiver_time_ns for item in best)
        )
        median_offset_ns = int(
            statistics.median(
                item.offset_sender_minus_receiver_ns for item in best
            )
        )
        minimum_rtt_ns = min(item.round_trip_delay_ns for item in best)

        drift_ppm = 0.0
        # Drift needs time coverage more than minimum RTT. Use the full rolling
        # window for the slope, while anchoring the offset at the robust
        # low-RTT median above. This avoids a low-RTT subset that happens to
        # cluster in only one short part of the recording.
        if len(samples) >= 8:
            span_ns = max(item.receiver_time_ns for item in samples) - min(
                item.receiver_time_ns for item in samples
            )
            if span_ns >= 5_000_000_000:
                x = [
                    (item.receiver_time_ns - reference_time_ns) * 1.0e-9
                    for item in samples
                ]
                y = [
                    float(item.offset_sender_minus_receiver_ns)
                    for item in samples
                ]
                mean_x = statistics.fmean(x)
                mean_y = statistics.fmean(y)
                denominator = sum((value - mean_x) ** 2 for value in x)
                if denominator > 0.0:
                    slope_ns_per_s = sum(
                        (x_value - mean_x) * (y_value - mean_y)
                        for x_value, y_value in zip(x, y)
                    ) / denominator
                    drift_ppm = slope_ns_per_s / 1000.0
                    # Protect correction from a pathological transient fit.
                    drift_ppm = max(-500.0, min(500.0, drift_ppm))

        return ClockEstimate(
            reference_receiver_time_ns=reference_time_ns,
            offset_sender_minus_receiver_ns=median_offset_ns,
            round_trip_delay_ns=minimum_rtt_ns,
            drift_ppm=drift_ppm,
            sample_count=len(samples),
        )
