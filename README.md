# LashariHost VPS Manager Bot (v4)

A Discord bot that deploys and manages Docker-based VPS containers with full
`systemd` support and **direct root SSH access** (real IP, port, username and
root password — works with Termius, PuTTY or plain `ssh`).

Includes a **redeem code** system, **port forwarding** (10 ports per VPS) and a
**multi-node** system so you can host VPS across several physical servers from
one bot.

---

## Features

- 1-click VPS deploy from Discord (`/deploy` or `/create`)
- Ubuntu 20.04 / 22.04 / 24.04 and Debian 11 / 12 containers with full `systemd`
- Direct root SSH — IP + unique port + root password sent to the user's DM
- Port forwarding — up to 10 extra ports per VPS
- Redeem codes — one-time codes members can claim for their own VPS
- Multi-node — connect extra servers as nodes and deploy on any of them
- Live status: `LashariHost | {n} VPS Running`
- Start / stop / restart / reinstall, auto-expiry, suspend / unsuspend
- Admin-only management commands
- Optional Pterodactyl integration

---

## Files in this repo

| File | Purpose |
|---|---|
| `lasharihost_bot.py` | The main Discord bot |
| `node_agent.py` | Script you run on extra servers to turn them into nodes |
| `requirements.txt` | Python dependencies |
| `.env.example` | Config template — copy to `.env` |
| `lasharihost.service` | systemd unit template (24/7 running) |
| `.gitignore`, `LICENSE` | Repo housekeeping |

---

## Requirements

- Linux server (Ubuntu 22.04 / 24.04 recommended) with a **public IPv4**
- **Docker** installed and running
- **Python 3.10+**
- A **Discord bot token**
- Root / sudo access (VPS containers run privileged)

---

## Installation — step by step

### 1. Clone the repository

```bash
git clone https://github.com/atifqmi-max/vpsbot-v4.git
cd vpsbot-v4
```

### 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
docker ps
```

### 3. Install Python and dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Create the Discord bot

1. Go to https://discord.com/developers/applications and click **New Application**
2. **Bot** → **Add Bot** → enable **Server Members Intent**
3. **Reset Token** and copy it
4. **OAuth2 → URL Generator** → scopes `bot` + `applications.commands`,
   permissions `Send Messages`, `Embed Links`
5. Open the generated URL and invite the bot to your server

### 5. Configure `.env`

```bash
cp .env.example .env
nano .env
```

Minimum required values:

```env
DISCORD_TOKEN=your_bot_token
ADMIN_ROLE_ID=your_admin_role_id
ADMIN_USER_IDS=your_discord_user_id
SERVER_IP=your_server_public_ip
```

Find your public IP with `curl -4 ifconfig.me`.

### 6. Open firewall ports

On the server:

```bash
sudo ufw allow 20000:29999/tcp   # VPS SSH ports
sudo ufw allow 8788/tcp          # node agent port (only if you use nodes)
sudo ufw reload
```

If you are on AWS / GCP / Azure / Hetzner etc., **also** add an inbound rule in
the provider's Security Group / Firewall: **Custom TCP, port range
`20000-29999`, source `0.0.0.0/0`** (and `8788` for nodes). Without this,
SSH will time out even though the bot works.

If you want to use port forwarding (`/port-add`) with host ports outside
`20000-29999`, open those ports in the provider firewall as well.

### 7. Run the bot

```bash
source venv/bin/activate
python3 lasharihost_bot.py
```

You should see `Database ready.` and `Online as ...`.

---

## Run 24/7 with systemd

Edit the paths in `lasharihost.service` if your folder is not `/root/vpsbot-v4`,
then:

```bash
sudo cp lasharihost.service /etc/systemd/system/lasharihost.service
sudo systemctl daemon-reload
sudo systemctl enable lasharihost
sudo systemctl start lasharihost
sudo systemctl status lasharihost
```

Live logs:

```bash
journalctl -u lasharihost -f
```

Restart after updating the bot file:

```bash
sudo systemctl restart lasharihost
```

> **Upgrading from the old StoneNodes version?** The database is now
> `lasharihost.db`. Keep your old data with:
> `mv stonenodes.db lasharihost.db` (while the bot is stopped).
> Old VPS keep working; new VPS are named `lasharihost-vps-XXXX`.

---

## Commands

### User commands

| Command | Description |
|---|---|
| `/my-vps` | List your VPS |
| `/start <id>` / `/stop <id>` / `/restart <id>` | Power controls |
| `/reinstall <id>` | Wipe and rebuild (new root password) |
| `/vps-performance <id>` | Live CPU / RAM / disk / network |
| `/port-add <id> <host_port> <container_port>` | Forward a public port to a port inside your VPS (max 10) |
| `/port-list <id>` | Show your port forwards |
| `/port-remove <id> <host_port>` | Remove a port forward |
| `/redeem <code>` | Claim a VPS with a redeem code |
| `/commands` | Show all commands |

Port forwarding example: `/port-add lasharihost-vps-0001 30080 80` makes
`SERVER_IP:30080` reach port `80` inside your VPS. Ports `20000-29999` are
reserved for SSH.

### Admin commands

| Command | Description |
|---|---|
| `/deploy <user>` | Wizard: OS → CPU → **Node** → specs |
| `/create` | Full-parameter create (with `node` option) |
| `/admin-add-user`, `/admin-remove-user` | Grant / revoke hosting access |
| `/extend-vps`, `/suspend-vps`, `/unsuspend-vps` | Expiry and suspension |
| `/remove-vps`, `/fix-vps` | Delete a VPS / clear a stuck container |
| `/list-vps` | All VPS on the host |
| `/node-stats` | Host CPU / RAM / disk |
| `/check-network` | Diagnose `SERVER_IP` and port setup |
| `/gen-redeem <ram> <cpu> <disk> <valid_days> <count>` | Generate redeem codes |
| `/redeem-stock` | View unredeemed codes |
| `/node-create`, `/node-config`, `/node-list`, `/node-delete` | Node management |
| `/ptero-status` | Pterodactyl status |

---

## Redeem codes

1. Admin: `/gen-redeem ram:2048 cpu:2 disk:20 valid_days:30 count:5`
2. Give codes to members.
3. Member: `/redeem SN-XXXX-XXXX-XXXX` — the code is claimed and deleted
   atomically (it can never be used twice) and the VPS is sent to their DM.
4. `/redeem-stock` shows what is still unclaimed.

---

## Multi-node system

Extra servers connect **outbound** to your main bot, so the node itself needs
no inbound ports for the agent — only your main bot server must allow
`AGENT_PORT` (default `8788`).

### Admin side (in Discord)

1. `/node-create name:Node2`
2. `/node-config name:Node2` — the bot replies with an **install command** and a
   **connect string** (`name|token|ip|port`).

### On the new server

```bash
curl -o node_agent.py https://raw.githubusercontent.com/atifqmi-max/vpsbot-v4/main/node_agent.py
sudo python3 node_agent.py
```

A menu appears:

```
1. Install VPS Bot
2. Uninstall VPS Bot
3. Connect NODE
4. Exit
```

| Option | What it does |
|---|---|
| **1. Install VPS Bot** | Installs Docker and the Python packages the agent needs. Run this first. |
| **2. Uninstall VPS Bot** | Removes Docker and every container it created (asks for confirmation). |
| **3. Connect NODE** | Paste the connect string from `/node-config`. The node goes 🟢 online and starts accepting VPS jobs. The process must keep running. |
| **4. Exit** | Quit the menu. |

First-time flow: choose **1**, wait, run the script again, choose **3**, paste
the connect string.

### Keep the agent running after you close the terminal

Quick way (tmux):

```bash
tmux new -s lasharihost-agent
sudo python3 node_agent.py      # choose 3, paste connect string
# detach: Ctrl+B then D      |   re-attach: tmux attach -t lasharihost-agent
```

Permanent way: run option 3 once (it saves `node_config.json`), press
`Ctrl+C`, then create `/etc/systemd/system/lasharihost-agent.service`:

```ini
[Unit]
Description=LashariHost Node Agent
After=docker.service network.target

[Service]
Type=simple
WorkingDirectory=/root
ExecStart=/usr/bin/python3 /root/node_agent.py
Restart=always
RestartSec=5
StandardInput=null

[Install]
WantedBy=multi-user.target
```

Open the SSH range (`20000-29999`) on the node's firewall / security group too.

> **Current limitation:** node support covers VPS **creation**. `/start`,
> `/stop`, `/restart`, `/reinstall`, `/remove-vps` and `/port-*` act on the
> main server's Docker. For VPS hosted on a node, manage them with `docker`
> directly on that node.

---

## What the user receives (DM)

```
Your VPS is Ready
Instance ID       lasharihost-vps-0001
OS                Ubuntu 24.04
RAM / CPU         8g / 4 vCPU
Shared IPv4       <SERVER_IP>
SSH Port (NAT)    <unique port>
Username          root
Root Password     <16 random characters>
SSH Command       ssh root@<SERVER_IP> -p <port>
```

---

## Troubleshooting

**SSH: connection timed out** — the port range is blocked. Check
`sudo ufw status` **and** the cloud Security Group (`20000-29999` TCP inbound).

**SSH: connection closed / reset during key exchange** — sshd did not start in
the container. Check `journalctl -u lasharihost -f` for lines about
`openssh-server` / `sshd -t`. The bot retries the install automatically and
fails loudly if `openssh-server` cannot be installed.

**Node agent: "port already in use" on startup** — an old bot copy is still
running: `sudo lsof -i :8788` then `sudo kill -9 <PID>`, or change `AGENT_PORT`.

**systemd `status=203/EXEC`** — a path in the service file is wrong. Use real
paths (e.g. `/root/vpsbot-v4/venv/bin/python3`).

**Slash commands not showing** — global sync can take a while the first time;
re-invite the bot with the `applications.commands` scope.

**Container name already in use** — `/fix-vps <id>` removes the stuck container.

---

## License

MIT — see [LICENSE](LICENSE).
