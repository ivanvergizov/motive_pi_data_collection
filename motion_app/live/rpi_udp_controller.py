from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .testbed import DEFAULT_CONFIG_PATH, DevicePlan, TestbedConfig, load_testbed


HERE = Path(__file__).resolve().parent
DEPLOY_FILES = (HERE / "pi_sender.py", HERE / "protocol.py")
REMOTE_CONFIG_NAME = "device_config.json"
REMOTE_PID_NAME = "sender.pid"
REMOTE_LOG_NAME = "sender.log"


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class NodeResult:
    node: int
    state: str
    message: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return self.state != "failed"


class RemoteController:
    """Install, start, stop, and set time on Raspberry Pi sender nodes."""

    def __init__(self, config: TestbedConfig) -> None:
        self.config = config

    @staticmethod
    def _require_executable(name: str) -> str:
        path = shutil.which(name)
        if path is None:
            raise RuntimeError(f"{name!r} was not found on PATH")
        return path

    def _ssh_base(self) -> list[str]:
        return [
            self._require_executable("ssh"),
            "-o", f"ConnectTimeout={self.config.ssh.connect_timeout_s}",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
        ]

    def _scp_base(self) -> list[str]:
        return [
            self._require_executable("scp"),
            "-o", f"ConnectTimeout={self.config.ssh.connect_timeout_s}",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
        ]

    def _run(self, command: list[str], timeout_s: float | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_s or max(15.0, self.config.ssh.connect_timeout_s * 4.0),
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(command, 124, exc.stdout or "", "command timed out")

    def _ssh(self, device: DevicePlan, command: str) -> subprocess.CompletedProcess[str]:
        return self._run([*self._ssh_base(), "-n", device.ssh_host(self.config.ssh), command])

    def _remote_directory(self) -> str:
        return self.config.ssh.remote_directory.rstrip("/")

    def sender_config(self, device: DevicePlan) -> dict[str, object]:
        return {
            "source_id": device.node,
            "local_ip": device.data_ip,
            "sync_port": self.config.sync.device_port,
            "multicast_group": self.config.controller.multicast_group,
            "data_port": self.config.controller.data_port,
            "sample_rate_hz": self.config.default_sample_rate_hz,
            "data_mode": self.config.device_data_mode,
            "sdr_endpoint": f"tcp://{self.config.sdr.host}:{self.config.sdr.port}",
        }

    def install(self, device: DevicePlan) -> NodeResult:
        directory = self._remote_directory()
        created = self._ssh(device, f"mkdir -p {shlex.quote(directory)}")
        if created.returncode != 0:
            return NodeResult(device.node, "failed", created.stdout.strip(), created.stderr.strip())

        for local_file in DEPLOY_FILES:
            copied = self._run([
                *self._scp_base(),
                str(local_file),
                f"{device.ssh_host(self.config.ssh)}:{directory}/",
            ])
            if copied.returncode != 0:
                return NodeResult(device.node, "failed", copied.stdout.strip(), copied.stderr.strip())

        with tempfile.TemporaryDirectory() as temporary_directory:
            local_config = Path(temporary_directory) / REMOTE_CONFIG_NAME
            local_config.write_text(json.dumps(self.sender_config(device), indent=2) + "\n", encoding="utf-8")
            copied = self._run([
                *self._scp_base(),
                str(local_config),
                f"{device.ssh_host(self.config.ssh)}:{directory}/{REMOTE_CONFIG_NAME}",
            ])
        if copied.returncode != 0:
            return NodeResult(device.node, "failed", copied.stdout.strip(), copied.stderr.strip())
        return NodeResult(device.node, "installed", "sender files installed")

    def set_time(self, device: DevicePlan) -> NodeResult:
        """Measure and correct the Pi clock through one SSH session."""
        python = shlex.quote(self.config.ssh.remote_python)
        remote_script = """
import subprocess
import sys
import time

for raw_line in sys.stdin:
    command = raw_line.strip()
    if command == "TIME":
        print(f"TIME {time.time_ns()}", flush=True)
        continue
    if command.startswith("SET "):
        offset_ns = int(command.split()[1])
        subprocess.run(["sudo", "-n", "timedatectl", "set-ntp", "false"], check=True, stdout=subprocess.DEVNULL)
        seconds = abs(offset_ns) / 1_000_000_000.0
        adjustment = f"{seconds:.9f} seconds ago" if offset_ns >= 0 else f"{seconds:.9f} seconds"
        subprocess.run(["sudo", "-n", "date", "-u", "-s", adjustment], check=True, stdout=subprocess.DEVNULL)
        print("SET OK", flush=True)
        continue
    if command == "QUIT":
        break
""".strip()
        process = subprocess.Popen(
            [*self._ssh_base(), device.ssh_host(self.config.ssh), f"{python} -u -c {shlex.quote(remote_script)}"],
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            creationflags=_creation_flags(),
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            return NodeResult(device.node, "failed", error="could not open SSH clock session")

        def exchange_time() -> tuple[int, int]:
            t0 = time.time_ns()
            process.stdin.write("TIME\n")
            process.stdin.flush()
            line = process.stdout.readline().strip()
            t3 = time.time_ns()
            if not line.startswith("TIME "):
                raise RuntimeError(line or "no clock response")
            remote_time_ns = int(line.split()[1])
            rtt_ns = t3 - t0
            return remote_time_ns - (t0 + rtt_ns // 2), rtt_ns

        try:
            offset_ns, rtt_ns = min((exchange_time() for _ in range(3)), key=lambda sample: sample[1])
            process.stdin.write(f"SET {offset_ns}\n")
            process.stdin.flush()
            if process.stdout.readline().strip() != "SET OK":
                raise RuntimeError("Pi clock set failed")
            residual_ns, residual_rtt_ns = exchange_time()
            process.stdin.write("QUIT\n")
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=max(2, self.config.ssh.connect_timeout_s))
            if process.returncode != 0:
                raise RuntimeError(process.stderr.read().strip() or "SSH clock session failed")
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            try:
                process.kill()
            except OSError:
                pass
            return NodeResult(device.node, "failed", error=str(exc))

        return NodeResult(
            device.node,
            "time_set",
            f"offset {offset_ns / 1e6:.3f} ms -> {residual_ns / 1e6:.3f} ms "
            f"(SSH RTT {rtt_ns / 1e6:.3f}/{residual_rtt_ns / 1e6:.3f} ms)",
        )

    def start(self, device: DevicePlan) -> NodeResult:
        directory = self._remote_directory()
        python = shlex.quote(self.config.ssh.remote_python)
        command = f"""
set -eu
cd {shlex.quote(directory)}
if [ -f {REMOTE_PID_NAME} ]; then
    old_pid=$(cat {REMOTE_PID_NAME})
    if kill -0 "$old_pid" 2>/dev/null; then
        echo "$old_pid"
        exit 10
    fi
    rm -f {REMOTE_PID_NAME}
fi
nohup {python} -u pi_sender.py --config {REMOTE_CONFIG_NAME} > {REMOTE_LOG_NAME} 2>&1 < /dev/null &
pid=$!
echo "$pid" > {REMOTE_PID_NAME}
sleep 0.5
if ! kill -0 "$pid" 2>/dev/null; then
    tail -n 30 {REMOTE_LOG_NAME} >&2 || true
    exit 1
fi
echo "$pid"
""".strip()
        completed = self._ssh(device, command)
        if completed.returncode == 10:
            return NodeResult(device.node, "already_running", f"already running pid={completed.stdout.strip()}")
        if completed.returncode != 0:
            return NodeResult(device.node, "failed", completed.stdout.strip(), completed.stderr.strip())
        return NodeResult(device.node, "started", f"started pid={completed.stdout.strip()}")

    def stop(self, device: DevicePlan) -> NodeResult:
        directory = self._remote_directory()
        command = f"""
cd {shlex.quote(directory)} 2>/dev/null || exit 20
[ -f {REMOTE_PID_NAME} ] || exit 20
pid=$(cat {REMOTE_PID_NAME})
if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    count=0
    while kill -0 "$pid" 2>/dev/null && [ "$count" -lt 30 ]; do
        sleep 0.1
        count=$((count+1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "sender pid $pid did not stop" >&2
        exit 1
    fi
fi
rm -f {REMOTE_PID_NAME}
echo "$pid"
""".strip()
        completed = self._ssh(device, command)
        if completed.returncode == 20:
            return NodeResult(device.node, "stopped")
        if completed.returncode != 0:
            return NodeResult(device.node, "failed", completed.stdout.strip(), completed.stderr.strip())
        return NodeResult(device.node, "stopped", f"stopped pid={completed.stdout.strip()}")

    def run_parallel(
        self,
        devices: Iterable[DevicePlan],
        operation: Callable[[DevicePlan], NodeResult],
    ) -> list[NodeResult]:
        device_list = list(devices)
        if not device_list:
            return []
        with ThreadPoolExecutor(max_workers=len(device_list)) as executor:
            futures = [executor.submit(operation, device) for device in device_list]
            return sorted((future.result() for future in as_completed(futures)), key=lambda result: result.node)


def print_results(results: Iterable[NodeResult]) -> int:
    failures = 0
    for result in results:
        marker = "OK" if result.success else "FAIL"
        print(f"[{marker}] node {result.node}: {result.state}")
        if result.message:
            print(f"  {result.message}")
        if result.error:
            print(f"  error: {result.error}")
        failures += int(not result.success)
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administer Raspberry Pi multicast senders.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("install", "set-time", "start", "stop"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
        subparser.add_argument("--nodes", help="node list/range; default: all Pis")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    config = load_testbed(arguments.config)
    devices = config.select_devices(arguments.nodes)
    controller = RemoteController(config)
    operation = {
        "install": controller.install,
        "set-time": controller.set_time,
        "start": controller.start,
        "stop": controller.stop,
    }[arguments.command]
    results = controller.run_parallel(devices, operation)
    raise SystemExit(1 if print_results(results) else 0)


if __name__ == "__main__":
    main()
