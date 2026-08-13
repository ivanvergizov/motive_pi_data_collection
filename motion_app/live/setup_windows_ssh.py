from __future__ import annotations

import argparse
import getpass
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from .testbed import DEFAULT_CONFIG_PATH, load_testbed


def ensure_key(private_key: Path) -> tuple[Path, Path]:
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        raise SystemExit(
            "ssh-keygen was not found. Enable the Windows OpenSSH Client first."
        )

    private_key = private_key.expanduser().resolve()
    public_key = Path(str(private_key) + ".pub")
    private_key.parent.mkdir(parents=True, exist_ok=True)

    if not private_key.exists():
        subprocess.run(
            [
                ssh_keygen,
                "-t",
                "ed25519",
                "-f",
                str(private_key),
                "-N",
                "",
            ],
            check=True,
        )

    if not public_key.exists():
        completed = subprocess.run(
            [ssh_keygen, "-y", "-f", str(private_key)],
            text=True,
            capture_output=True,
            check=True,
        )
        public_key.write_text(completed.stdout.strip() + "\n", encoding="utf-8")

    return private_key, public_key


def require_ssh() -> str:
    ssh = shutil.which("ssh")
    if ssh is None:
        raise SystemExit(
            "ssh was not found. Enable the Windows OpenSSH Client first."
        )
    return ssh


def make_askpass_environment(password: str, directory: Path) -> dict[str, str]:
    """Create a temporary Windows SSH_ASKPASS helper for one setup run."""
    helper = directory / "udp_testbed_askpass.cmd"
    helper.write_text(
        "@echo off\r\n"
        'powershell.exe -NoProfile -NonInteractive -Command '
        '"[Console]::Out.Write($env:UDP_TESTBED_SSH_PASSWORD)"\r\n',
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["UDP_TESTBED_SSH_PASSWORD"] = password
    env["SSH_ASKPASS"] = str(helper)
    env["SSH_ASKPASS_REQUIRE"] = "force"
    # OpenSSH traditionally requires DISPLAY to be set before using SSH_ASKPASS.
    env.setdefault("DISPLAY", "1")
    return env


def install_key_on_pi(
    *,
    ssh: str,
    host: str,
    username: str,
    public_key_text: str,
    timeout_s: int,
    askpass_env: dict[str, str],
) -> tuple[bool, str]:
    quoted_key = shlex.quote(public_key_text.strip())
    command = (
        "umask 077; "
        "mkdir -p ~/.ssh; "
        "touch ~/.ssh/authorized_keys; "
        "chmod 700 ~/.ssh; "
        "chmod 600 ~/.ssh/authorized_keys; "
        f"grep -qxF {quoted_key} ~/.ssh/authorized_keys || "
        f"printf '%s\\n' {quoted_key} >> ~/.ssh/authorized_keys; "
        "hostname"
    )

    try:
        completed = subprocess.run(
            [
                ssh,
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"ConnectTimeout={timeout_s}",
                "-o",
                "NumberOfPasswordPrompts=1",
                f"{username}@{host}",
                command,
            ],
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=askpass_env,
            check=False,
            timeout=max(15, timeout_s * 4),
        )
    except subprocess.TimeoutExpired:
        return False, "SSH key installation timed out"
    detail = completed.stdout.strip() if completed.returncode == 0 else (
        completed.stderr.strip() or completed.stdout.strip()
    )
    return completed.returncode == 0, detail


def verify_windows_ssh(
    *,
    ssh: str,
    host: str,
    username: str,
    private_key: Path,
    timeout_s: int,
) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [
                ssh,
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"ConnectTimeout={timeout_s}",
                "-i",
                str(private_key),
                f"{username}@{host}",
                "hostname",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=max(15, timeout_s * 4),
        )
    except subprocess.TimeoutExpired:
        return False, "passwordless SSH verification timed out"
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    return False, completed.stderr.strip() or completed.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Set up passwordless Windows SSH to the Pis.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="testbed JSON file")
    parser.add_argument("--nodes", help="node list/range; default: all Pis")
    parser.add_argument("--username", help="override ssh.username")
    parser.add_argument("--password", help="override ssh.password")
    return parser

def main() -> None:
    args = build_parser().parse_args()
    if os.name != "nt":
        raise SystemExit(
            "setup_windows_ssh.py is intended to be run from native Windows PowerShell."
        )

    config = load_testbed(args.config)
    devices = config.select_devices(args.nodes)

    username = args.username or config.ssh.username
    if not username:
        raise SystemExit(
            "No SSH username is configured. Set ssh.username in testbed.json "
            "or pass --username."
        )

    if args.password is not None:
        password = args.password
    elif config.ssh.password:
        password = config.ssh.password
    else:
        password = getpass.getpass("RPi password: ")

    if not password:
        raise SystemExit(
            "No SSH password is available. Set ssh.password in testbed.json, "
            "pass --password, or enter it when prompted."
        )

    key_path = Path.home() / ".ssh" / "id_ed25519"

    ssh = require_ssh()
    private_key, public_key = ensure_key(key_path)
    public_key_text = public_key.read_text(encoding="utf-8").strip()

    print(f"\nWindows key: {private_key}")
    print("Using the same password for all selected Pis during this setup run.")

    failures = 0
    with tempfile.TemporaryDirectory() as temporary_directory:
        askpass_env = make_askpass_environment(
            password,
            Path(temporary_directory),
        )

        for device in devices:
            host = device.management_ip
            print(f"\nNode {device.node} ({host})")

            installed, detail = install_key_on_pi(
                ssh=ssh,
                host=host,
                username=username,
                public_key_text=public_key_text,
                timeout_s=config.ssh.connect_timeout_s,
                askpass_env=askpass_env,
            )
            if not installed:
                failures += 1
                print(f"  FAILED to install key: {detail}")
                continue

            verified, detail = verify_windows_ssh(
                ssh=ssh,
                host=host,
                username=username,
                private_key=private_key,
                timeout_s=config.ssh.connect_timeout_s,
            )
            if verified:
                print(f"  passwordless Windows SSH verified: {detail or 'OK'}")
            else:
                failures += 1
                print(f"  FAILED verification: {detail}")

    # Drop the reference after the temporary askpass environment is gone.
    password = ""

    if failures:
        raise SystemExit(1)

    print("\nPasswordless Windows SSH is configured for all selected Pis.")
    if username != config.ssh.username:
        print(
            "Update ssh.username in testbed.json to match the username used "
            "above before using rpi_udp_controller.py or sync_tester.py run."
        )


if __name__ == "__main__":
    main()
