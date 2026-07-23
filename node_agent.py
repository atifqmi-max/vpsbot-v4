#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════╗
║           StoneNodes — Node Agent                     ║
║  Runs on a remote server and connects OUTBOUND to the  ║
║  main StoneNodes bot so it can host VPS containers on  ║
║  this machine too.                                     ║
╚═══════════════════════════════════════════════════════╝

Menu:
  1. Install VPS Bot     -> installs Docker + deps on this machine
  2. Uninstall VPS Bot   -> removes Docker + deps from this machine
  3. Connect NODE        -> paste the connect string from /node-config
                            and this machine starts hosting VPS for
                            the main bot
  4. Exit
"""

import os
import sys
import json
import time
import random
import string
import socket
import asyncio
import subprocess

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_config.json")


# ─────────────────────────────────────────────────────
# 1. INSTALL / UNINSTALL
# ─────────────────────────────────────────────────────
def run(cmd: str, check: bool = True):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True)
    if check and r.returncode != 0:
        print(f"  ⚠️  Command exited with code {r.returncode} (continuing anyway)")
    return r.returncode


def install_vps_bot():
    print("\n=== Installing Docker + agent dependencies ===\n")
    run("curl -fsSL https://get.docker.com | sh", check=False)
    run("systemctl enable docker", check=False)
    run("systemctl start docker", check=False)
    run("apt-get update -qq", check=False)
    run("apt-get install -y -qq python3 python3-pip python3-venv", check=False)
    run(f"{sys.executable} -m pip install --break-system-packages -q docker aiohttp", check=False)
    print("\n✅ Docker + dependencies installed. Verify with: docker ps")
    print("Next: run this script again and choose '3. Connect NODE'.\n")


def uninstall_vps_bot():
    print("\n=== Uninstalling ===\n")
    confirm = input("This removes Docker and ALL containers on this machine. Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Cancelled.")
        return
    run("docker ps -aq --filter label=managed-by=stonenodes | xargs -r docker rm -f", check=False)
    run("apt-get purge -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin "
        "docker-compose-plugin", check=False)
    run("rm -rf /var/lib/docker", check=False)
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    print("\n✅ Uninstalled.\n")


# ─────────────────────────────────────────────────────
# 2. VPS PROVISIONING (mirrors the main bot's provision())
# ─────────────────────────────────────────────────────
def gen_root_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def provision_vps(job: dict) -> dict:
    """Runs entirely on THIS machine's local Docker. Returns a job_result dict."""
    import docker

    vps_id     = job["vps_id"]
    image      = job["image"]
    ram_mb     = job["ram_mb"]
    cpu_cores  = job["cpu_cores"]
    cpu_name   = job.get("cpu_name", "Generic CPU")
    os_label   = job.get("os_label", image)
    host_port  = job["host_port"]
    root_pass  = job["root_pass"]

    # Make sure the requested port is actually free on THIS machine;
    # if not, pick another one in a small range around it.
    if not _port_free(host_port):
        for _ in range(20):
            candidate = random.randint(20000, 29999)
            if _port_free(candidate):
                host_port = candidate
                break
        else:
            return {"ok": False, "error": "No free port available on this node."}

    client = docker.from_env()
    client.images.pull(image)

    mem    = ram_mb * 1024 * 1024
    period = 100000
    quota  = int(cpu_cores * period)

    try:
        host_cfg = client.api.create_host_config(
            mem_limit=mem, memswap_limit=mem, cpu_period=period, cpu_quota=quota,
            privileged=True, cgroupns="host",
            binds={"/sys/fs/cgroup": {"bind": "/sys/fs/cgroup", "mode": "rw"}},
            tmpfs={"/run": "rw,nosuid,nodev", "/run/lock": "rw,nosuid,nodev", "/tmp": "rw,nosuid,nodev"},
            port_bindings={22: host_port},
        )
    except TypeError:
        host_cfg = client.api.create_host_config(
            mem_limit=mem, memswap_limit=mem, cpu_period=period, cpu_quota=quota,
            privileged=True,
            binds={"/sys/fs/cgroup": {"bind": "/sys/fs/cgroup", "mode": "rw"}},
            tmpfs={"/run": "rw,nosuid,nodev", "/run/lock": "rw,nosuid,nodev", "/tmp": "rw,nosuid,nodev"},
            port_bindings={22: host_port},
        )

    try:
        ct_data = client.api.create_container(
            image=image, name=vps_id, detach=True, tty=True, stdin_open=True,
            environment={"TERM": "xterm-256color", "container": "docker"},
            command="/sbin/init", host_config=host_cfg, ports=[22],
            labels={"managed-by": "stonenodes", "vps-id": vps_id},
        )
        client.api.start(ct_data["Id"])
        ct = client.containers.get(ct_data["Id"])
    except Exception as e:
        return {"ok": False, "error": f"Container create failed: {e}"}

    time.sleep(6)  # let systemd boot

    ct.exec_run("bash -c 'apt-get update -qq'", tty=False)
    ct.exec_run(
        "bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
        "openssh-server tmate neofetch curl wget sudo procps net-tools iproute2 htop'",
        tty=False,
    )

    # Fake specs so neofetch/free/lscpu show the "sold" resources
    ct.exec_run(f"bash -c \"echo -e 'MemTotal: {ram_mb*1024} kB' > /proc/meminfo\"", tty=False)

    # Root password + direct SSH
    ct.exec_run(f"bash -c \"echo 'root:{root_pass}' | chpasswd\"", tty=False)
    ct.exec_run("mkdir -p /run/sshd", tty=False)
    ct.exec_run(
        "bash -c \""
        "sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config; "
        "sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config; "
        "grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config; "
        "grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config"
        "\"",
        tty=False,
    )
    ct.exec_run(
        "bash -c 'systemctl enable ssh 2>/dev/null; systemctl restart ssh "
        "|| systemctl restart sshd || service ssh restart'",
        tty=False,
    )

    # tmate backup SSH
    sock = "/tmp/tmate.sock"
    ct.exec_run(f"bash -c 'rm -f {sock}; tmate -S {sock} new-session -d'", tty=False)
    time.sleep(5)
    ct.exec_run(f"bash -c 'tmate -S {sock} wait tmate-ready'", tty=False)
    r   = ct.exec_run(f"bash -c \"tmate -S {sock} display -p '#{{tmate_ssh}}'\"", tty=False)
    ssh = r.output.decode(errors="ignore").strip() if r.output else ""

    return {"ok": True, "container_id": ct.id, "ssh": ssh, "host_port": host_port}


def exec_action(job: dict) -> dict:
    """Handle start / stop / restart / remove for a VPS already on this node."""
    import docker
    client = docker.from_env()
    action = job.get("action")
    vps_id = job.get("vps_id")
    try:
        ct = client.containers.get(vps_id)
        if action == "start":
            ct.start()
        elif action == "stop":
            ct.stop()
        elif action == "restart":
            ct.restart()
        elif action == "remove":
            ct.remove(force=True, v=True)
        else:
            return {"ok": False, "error": f"Unknown action '{action}'"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────
# 3. CONNECT NODE — persistent WebSocket client
# ─────────────────────────────────────────────────────
def save_config(node_id, token, server_ip, port):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"node_id": node_id, "token": token, "server_ip": server_ip, "port": port}, f)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE) as f:
        return json.load(f)


def parse_connect_string(s: str):
    """Format from /node-config: node_id|token|server_ip|port"""
    parts = s.strip().split("|")
    if len(parts) != 4:
        raise ValueError("That doesn't look like a valid connect string (expected 4 parts separated by '|').")
    node_id, token, server_ip, port = parts
    return node_id, token, server_ip, int(port)


async def agent_loop(node_id, token, server_ip, port):
    import aiohttp

    url = f"ws://{server_ip}:{port}/agent/ws"
    backoff = 5
    while True:
        try:
            print(f"[agent] Connecting to {url} as '{node_id}'...")
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=30) as ws:
                    await ws.send_json({"type": "hello", "node_id": node_id, "token": token})
                    ack = await ws.receive_json()
                    if not ack.get("ok"):
                        print(f"[agent] ❌ Rejected: {ack.get('error')}")
                        print("[agent] Check your connect string is correct and try again.")
                        return
                    print("[agent] ✅ Connected. Waiting for jobs...")
                    backoff = 5

                    async for msg in ws:
                        if msg.type.name != "TEXT":
                            continue
                        job = json.loads(msg.data)
                        jtype = job.get("type")
                        print(f"[agent] Job received: {jtype} ({job.get('vps_id')})")

                        if jtype == "create_vps":
                            loop = asyncio.get_event_loop()
                            result = await loop.run_in_executor(None, provision_vps, job)
                        elif jtype == "exec_action":
                            loop = asyncio.get_event_loop()
                            result = await loop.run_in_executor(None, exec_action, job)
                        else:
                            result = {"ok": False, "error": f"Unknown job type '{jtype}'"}

                        result["type"] = "job_result"
                        result["job_id"] = job["job_id"]
                        await ws.send_json(result)
        except Exception as e:
            print(f"[agent] Connection lost/failed: {e}")
        print(f"[agent] Reconnecting in {backoff}s...")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def connect_node():
    existing = load_config()
    if existing:
        print(f"\nAlready configured as node '{existing['node_id']}' -> {existing['server_ip']}:{existing['port']}")
        again = input("Paste a NEW connect string to reconfigure, or press Enter to reuse this one: ").strip()
        if again:
            node_id, token, server_ip, port = parse_connect_string(again)
            save_config(node_id, token, server_ip, port)
        else:
            node_id, token, server_ip, port = (
                existing["node_id"], existing["token"], existing["server_ip"], existing["port"]
            )
    else:
        raw = input("\nPaste the connect string from /node-config: ").strip()
        try:
            node_id, token, server_ip, port = parse_connect_string(raw)
        except ValueError as e:
            print(f"❌ {e}")
            return
        save_config(node_id, token, server_ip, port)

    print(
        "\n⚠️  This process must stay running for the node to stay online.\n"
        "   To keep it running after you close this terminal, use tmux/screen,\n"
        "   or set it up as a systemd service (see the README).\n"
    )
    try:
        asyncio.run(agent_loop(node_id, token, server_ip, port))
    except KeyboardInterrupt:
        print("\n[agent] Stopped.")


# ─────────────────────────────────────────────────────
# 4. MENU
# ─────────────────────────────────────────────────────
def menu():
    while True:
        print("\n" + "=" * 45)
        print("        StoneNodes — Node Agent")
        print("=" * 45)
        cfg = load_config()
        if cfg:
            print(f"  Configured as: {cfg['node_id']} -> {cfg['server_ip']}:{cfg['port']}")
        print("""
  1. Install VPS Bot
  2. Uninstall VPS Bot
  3. Connect NODE
  4. Exit
""")
        choice = input("Select an option [1-4]: ").strip()
        if choice == "1":
            install_vps_bot()
        elif choice == "2":
            uninstall_vps_bot()
        elif choice == "3":
            connect_node()
        elif choice == "4":
            print("Bye!")
            break
        else:
            print("Invalid option, try again.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠️  Please run this script as root (sudo python3 node_agent.py).")
    menu()
