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
DEPLOY_FILES = (HERE / "pi_sender.py", HERE / "protocol.py", HERE / "sdr_latest.py")
REMOTE_CONFIG_NAME = "device_config.json"
REMOTE_PID_NAME = "sender.pid"
REMOTE_LOG_NAME = "sender.log"


@dataclass(frozen=True)
class NodeResult:
    node: int
    state: str
    message: str
    error: str = ""

    @property
    def success(self) -> bool:
        return self.state not in {"failed", "unreachable"}


class RemoteController:
    """Deploy and control Pi sender processes through the system SSH client."""

    def __init__(self, config: TestbedConfig) -> None:
        self.config = config

    @staticmethod
    def _require_executable(name: str) -> str:
        path = shutil.which(name)
        if path is None:
            raise RuntimeError(
                f"{name!r} was not found on PATH. Install or enable the "
                "OpenSSH client in the environment running this command."
            )
        return path

    def _ssh_base(self) -> list[str]:
        ssh = self.config.ssh
        return [
            self._require_executable("ssh"),
            "-o",
            f"ConnectTimeout={ssh.connect_timeout_s}",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]

    def _scp_base(self) -> list[str]:
        ssh = self.config.ssh
        return [
            self._require_executable("scp"),
            "-o",
            f"ConnectTimeout={ssh.connect_timeout_s}",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]

    def _run(
        self,
        command: list[str],
        *,
        timeout_s: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if timeout_s is None:
            timeout_s = max(15.0, float(self.config.ssh.connect_timeout_s) * 4.0)
        try:
            return subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            detail = f"command timed out after {timeout_s:g} seconds"
            if stderr.strip():
                detail = f"{detail}: {stderr.strip()}"
            return subprocess.CompletedProcess(command, 124, stdout or "", detail)

    def _ssh(self, device: DevicePlan, remote_command: str) -> subprocess.CompletedProcess[str]:
        return self._run(
            [
                *self._ssh_base(),
                "-n",
                device.ssh_host(self.config.ssh),
                remote_command,
            ]
        )

    def _remote_paths(self) -> dict[str, str]:
        directory = self.config.ssh.remote_directory.rstrip("/")
        return {
            "directory": directory,
            "config": f"{directory}/{REMOTE_CONFIG_NAME}",
            "pid": f"{directory}/{REMOTE_PID_NAME}",
            "log": f"{directory}/{REMOTE_LOG_NAME}",
            "sender": f"{directory}/pi_sender.py",
            "protocol": f"{directory}/protocol.py",
            "sdr_latest": f"{directory}/sdr_latest.py",
        }

    def sender_config(self, device: DevicePlan) -> dict[str, object]:
        return {
            "source_id": device.source_id,
            "source_name": device.name,
            "local_ip": device.data_ip,
            "sync_port": device.sync_port,
            "receiver_ip": self.config.controller.ip,
            "receiver_port": self.config.controller.data_port,
            "sample_rate_hz": device.sample_rate_hz,
            "sdr": {
                "enabled": device.sdr_enabled,
                "ip": device.sdr_ip,
                "port": device.sdr_port,
            },
        }

    def show(self, device: DevicePlan) -> NodeResult:
        return NodeResult(
            node=device.node,
            state="configured",
            message=(
                f"ssh={device.ssh_host(self.config.ssh)} "
                f"source_id={device.source_id} data_ip={device.data_ip} "
                f"data_destination={self.config.controller.ip}:"
                f"{self.config.controller.data_port} "
                f"sync_port={device.sync_port} rate={device.sample_rate_hz:g}Hz "
                f"sdr={'tcp://' + device.sdr_ip + ':' + str(device.sdr_port) if device.sdr_enabled else 'disabled'}"
            ),
        )

    def check(self, device: DevicePlan) -> NodeResult:
        python = shlex.quote(self.config.ssh.remote_python)
        completed = self._ssh(device, f"hostname; {python} --version")
        if completed.returncode != 0:
            return NodeResult(
                device.node,
                "unreachable",
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        return NodeResult(device.node, "reachable", completed.stdout.strip())

    def install(self, device: DevicePlan) -> NodeResult:
        paths = self._remote_paths()
        for local_file in DEPLOY_FILES:
            if not local_file.exists():
                return NodeResult(
                    device.node,
                    "failed",
                    "",
                    f"missing local deployment file: {local_file}",
                )

        mkdir = self._ssh(
            device,
            f"mkdir -p {shlex.quote(paths['directory'])}",
        )
        if mkdir.returncode != 0:
            return NodeResult(
                device.node,
                "failed",
                mkdir.stdout.strip(),
                mkdir.stderr.strip(),
            )

        for local_file in DEPLOY_FILES:
            completed = self._run(
                [
                    *self._scp_base(),
                    str(local_file),
                    f"{device.ssh_host(self.config.ssh)}:"
                    f"{paths['directory']}/",
                ]
            )
            if completed.returncode != 0:
                return NodeResult(
                    device.node,
                    "failed",
                    completed.stdout.strip(),
                    completed.stderr.strip(),
                )

        payload = (
            json.dumps(self.sender_config(device), indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_config = Path(temporary_directory) / REMOTE_CONFIG_NAME
            local_config.write_bytes(payload)
            remote_temp = f"{paths['config']}.tmp"
            completed = self._run(
                [
                    *self._scp_base(),
                    str(local_config),
                    f"{device.ssh_host(self.config.ssh)}:{remote_temp}",
                ]
            )
            if completed.returncode != 0:
                return NodeResult(
                    device.node,
                    "failed",
                    completed.stdout.strip(),
                    completed.stderr.strip(),
                )

        python = shlex.quote(self.config.ssh.remote_python)
        validation = f"""
set -eu
cd {shlex.quote(paths['directory'])}
{python} pi_sender.py --config {shlex.quote(REMOTE_CONFIG_NAME + '.tmp')} --check-config >/dev/null
mv {shlex.quote(REMOTE_CONFIG_NAME + '.tmp')} {shlex.quote(REMOTE_CONFIG_NAME)}
{python} -m py_compile pi_sender.py protocol.py sdr_latest.py
""".strip()
        completed = self._ssh(device, validation)
        if completed.returncode != 0:
            return NodeResult(
                device.node,
                "failed",
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        return NodeResult(
            device.node,
            "installed",
            "files and configuration installed and validated",
        )

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
        subprocess.run(
            ["sudo", "-n", "timedatectl", "set-ntp", "false"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        offset_seconds = abs(offset_ns) / 1_000_000_000.0
        if offset_ns >= 0:
            adjustment = f"{offset_seconds:.9f} seconds ago"
        else:
            adjustment = f"{offset_seconds:.9f} seconds"
        subprocess.run(
            ["sudo", "-n", "date", "-u", "-s", adjustment],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        print("SET OK", flush=True)
        continue
    if command == "QUIT":
        break
""".strip()

        process = subprocess.Popen(
            [
                *self._ssh_base(),
                device.ssh_host(self.config.ssh),
                f"{python} -u -c {shlex.quote(remote_script)}",
            ],
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )

        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            return NodeResult(device.node, "failed", "", "could not open SSH clock session")

        def exchange_time() -> tuple[int, int]:
            t0 = time.time_ns()
            process.stdin.write("TIME\n")
            process.stdin.flush()
            line = process.stdout.readline().strip()
            t3 = time.time_ns()
            if not line.startswith("TIME "):
                error = process.stderr.read().strip() if process.poll() is not None else ""
                raise RuntimeError(error or f"unexpected clock response: {line!r}")
            remote_time_ns = int(line.split()[1])
            round_trip_ns = t3 - t0
            midpoint_ns = t0 + round_trip_ns // 2
            return remote_time_ns - midpoint_ns, round_trip_ns

        try:
            samples = [exchange_time() for _ in range(3)]
            offset_ns, round_trip_ns = min(samples, key=lambda sample: sample[1])

            process.stdin.write(f"SET {offset_ns}\n")
            process.stdin.flush()
            set_response = process.stdout.readline().strip()
            if set_response != "SET OK":
                error = process.stderr.read().strip() if process.poll() is not None else ""
                raise RuntimeError(error or f"unexpected set-time response: {set_response!r}")

            residual_offset_ns, residual_round_trip_ns = exchange_time()
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
            return NodeResult(device.node, "failed", "", str(exc))

        return NodeResult(
            device.node,
            "time_set",
            (
                f"pre-set offset={offset_ns / 1_000_000.0:.3f} ms "
                f"(SSH RTT={round_trip_ns / 1_000_000.0:.3f} ms)\n"
                f"post-set offset={residual_offset_ns / 1_000_000.0:.3f} ms "
                f"(SSH RTT={residual_round_trip_ns / 1_000_000.0:.3f} ms)"
            ),
        )

    def start(self, device: DevicePlan) -> NodeResult:
        paths = self._remote_paths()
        python = shlex.quote(self.config.ssh.remote_python)
        command = f"""
set -eu
cd {shlex.quote(paths['directory'])}
if [ -f {shlex.quote(REMOTE_PID_NAME)} ]; then
    old_pid=$(cat {shlex.quote(REMOTE_PID_NAME)})
    if kill -0 "$old_pid" 2>/dev/null; then
        echo "$old_pid"
        exit 10
    fi
    rm -f {shlex.quote(REMOTE_PID_NAME)}
fi
nohup {python} -u pi_sender.py --config {shlex.quote(REMOTE_CONFIG_NAME)} > {shlex.quote(REMOTE_LOG_NAME)} 2>&1 < /dev/null &
pid=$!
echo "$pid" > {shlex.quote(REMOTE_PID_NAME)}
sleep {2.5 if device.sdr_enabled else 0.5}
if ! kill -0 "$pid" 2>/dev/null; then
    tail -n 50 {shlex.quote(REMOTE_LOG_NAME)} >&2 || true
    exit 1
fi
echo "$pid"
exit 0
""".strip()
        completed = self._ssh(device, command)
        if completed.returncode == 10:
            return NodeResult(
                device.node,
                "already_running",
                f"already running pid={completed.stdout.strip()}",
            )
        if completed.returncode != 0:
            return NodeResult(
                device.node,
                "failed",
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        return NodeResult(
            device.node,
            "started",
            f"started pid={completed.stdout.strip()}",
        )

    def stop(self, device: DevicePlan) -> NodeResult:
        paths = self._remote_paths()
        command = f"""
set -eu
cd {shlex.quote(paths['directory'])} 2>/dev/null || {{ echo "not installed"; exit 20; }}
if [ ! -f {shlex.quote(REMOTE_PID_NAME)} ]; then
    echo "no pid file"
    exit 20
fi
pid=$(cat {shlex.quote(REMOTE_PID_NAME)})
if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    count=0
    while kill -0 "$pid" 2>/dev/null && [ "$count" -lt 30 ]; do
        sleep 0.1
        count=$((count+1))
    done
fi
rm -f {shlex.quote(REMOTE_PID_NAME)}
echo "$pid"
""".strip()
        completed = self._ssh(device, command)
        if completed.returncode == 20:
            return NodeResult(device.node, "stopped", completed.stdout.strip())
        if completed.returncode != 0:
            return NodeResult(
                device.node,
                "failed",
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        return NodeResult(
            device.node,
            "stopped",
            f"stopped pid={completed.stdout.strip()}",
        )

    def status(self, device: DevicePlan) -> NodeResult:
        paths = self._remote_paths()
        command = f"""
cd {shlex.quote(paths['directory'])} 2>/dev/null || {{ echo "not installed"; exit 20; }}
if [ -f {shlex.quote(REMOTE_PID_NAME)} ]; then
    pid=$(cat {shlex.quote(REMOTE_PID_NAME)})
    if kill -0 "$pid" 2>/dev/null; then
        echo "$pid"
        exit 0
    fi
fi
echo "stopped"
exit 20
""".strip()
        completed = self._ssh(device, command)
        if completed.returncode == 20:
            return NodeResult(device.node, "stopped", completed.stdout.strip())
        if completed.returncode != 0:
            return NodeResult(
                device.node,
                "failed",
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        return NodeResult(
            device.node,
            "running",
            f"running pid={completed.stdout.strip()}",
        )

    def logs(self, device: DevicePlan, lines: int) -> NodeResult:
        paths = self._remote_paths()
        completed = self._ssh(
            device,
            f"tail -n {max(1, int(lines))} {shlex.quote(paths['log'])}",
        )
        if completed.returncode != 0:
            return NodeResult(
                device.node,
                "failed",
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        return NodeResult(device.node, "logs", completed.stdout.rstrip())

    def run_parallel(
        self,
        devices: Iterable[DevicePlan],
        operation: Callable[[DevicePlan], NodeResult],
    ) -> list[NodeResult]:
        device_list = list(devices)
        results: list[NodeResult] = []
        with ThreadPoolExecutor(
            max_workers=self.config.ssh.max_parallel
        ) as executor:
            futures = {
                executor.submit(operation, device): device
                for device in device_list
            }
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda result: result.node)


def print_results(results: Iterable[NodeResult]) -> int:
    failures = 0
    for result in results:
        marker = "OK" if result.success else "FAIL"
        print(f"[{marker}] node {result.node}: {result.state}")
        if result.message:
            for line in result.message.splitlines():
                print(f"  {line}")
        if result.error:
            for line in result.error.splitlines():
                print(f"  error: {line}")
        if not result.success:
            failures += 1
    return failures


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="testbed JSON file",
    )
    parser.add_argument(
        "--nodes",
        help="node list/range; default: all Pis",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Raspberry Pi UDP senders.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    command_help = {
        "show": "show resolved settings",
        "check": "check SSH and remote Python",
        "install": "install sender files and configuration",
        "set-time": "set Pi clocks from the controller",
        "start": "start senders",
        "stop": "stop senders",
        "restart": "restart senders",
        "status": "show sender status",
        "logs": "show recent sender log lines",
    }
    for name, help_text in command_help.items():
        subparser = subparsers.add_parser(name, help=help_text)
        add_common_arguments(subparser)
        if name == "logs":
            subparser.add_argument(
                "--lines",
                type=int,
                default=40,
                help="number of trailing lines (default: 40)",
            )
    return parser

def main() -> None:
    arguments = build_parser().parse_args()
    try:
        config = load_testbed(arguments.config)
        devices = config.select_devices(arguments.nodes)
        controller = RemoteController(config)
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Configuration/setup error: {exc}") from exc

    if arguments.command == "show":
        results = [controller.show(device) for device in devices]
    elif arguments.command == "check":
        results = controller.run_parallel(devices, controller.check)
    elif arguments.command == "install":
        results = controller.run_parallel(devices, controller.install)
    elif arguments.command == "set-time":
        results = controller.run_parallel(devices, controller.set_time)
    elif arguments.command == "start":
        results = controller.run_parallel(devices, controller.start)
    elif arguments.command == "stop":
        results = controller.run_parallel(devices, controller.stop)
    elif arguments.command == "restart":
        stop_results = controller.run_parallel(devices, controller.stop)
        print("Stop phase")
        print_results(stop_results)
        print("Start phase")
        results = controller.run_parallel(devices, controller.start)
    elif arguments.command == "status":
        results = controller.run_parallel(devices, controller.status)
    elif arguments.command == "logs":
        results = controller.run_parallel(
            devices,
            lambda device: controller.logs(device, arguments.lines),
        )
    else:
        raise AssertionError(arguments.command)

    raise SystemExit(1 if print_results(results) else 0)


if __name__ == "__main__":
    main()
