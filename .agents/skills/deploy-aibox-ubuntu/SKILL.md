---
name: deploy-aibox-ubuntu
description: Run Robonix on AIBOX with the TIAGo Webots simulator and primitive providers on Ubuntu.
---

# AIBOX Webots on Ubuntu

The stack is one `rbnx boot` on the board, driven by the
`examples/webots-aibox/` deploy directory: AIBOX runs Atlas, soma,
executor, pilot, liaison, vitals, mapping, nav2, scene (NPU), and explore;
the four TIAGo primitives start on Ubuntu through SSH-wrapped packages that
`rbnx start` on the sim host (docker-exec'ing each driver into the sim
container) while the board supervises them. Only Webots itself starts by
hand on Ubuntu. VLM credentials stay on AIBOX. Do not run the example's
local rbnx boot manifest on Ubuntu.

Tear-down is one `rbnx shutdown` on the board plus `sim/stop.sh` on Ubuntu.
The manual per-component `rbnx start` flow is gone; when boot misbehaves,
Troubleshooting covers the recovery paths.

## 0. Connect to AIBOX

Every AIBOX command runs through the configured SSH alias; the alias supplies
the host, user, and identity key.

~~~bash
ssh aibox 'hostname && echo aibox-ok'
~~~

Code blocks with `/root/robonix` paths run on AIBOX, either as
`ssh aibox '<command>'` or inside an interactive `ssh aibox` terminal.
Interactive shells find `rbnx` and the debug binaries through the PATH line
that step 1 appends to `/root/.bashrc`. A non-interactive
`ssh aibox '<command>'` does not — the default `.bashrc` returns early for
non-interactive shells — so remote one-liners must carry the export
themselves:

~~~bash
ssh aibox 'export PATH=/root/robonix/target/debug:$PATH; which rbnx'
~~~

The deploy directory additionally needs a BatchMode-capable board → Ubuntu
SSH alias; it already exists on this board (`HOST_SSH=aibox-ubuntu`, see
`examples/webots-aibox/remote.env`).

## 1. One-time initialization (AIBOX)

Run once per board, in an interactive `ssh aibox` terminal. Add the debug
binaries to the login PATH, copy the rmw_zenoh default config, and write the
shared environment file. Refresh the IPv4 values whenever the tailnet
addresses change: `100.123.129.114` is Ubuntu's `tailscale ip -4` and
`100.74.193.22` is AIBOX's.

~~~bash
cd /root/robonix
grep -qF "export PATH=/root/robonix/target/debug:\$PATH" /root/.bashrc \
  || echo "export PATH=/root/robonix/target/debug:\$PATH" >> /root/.bashrc
mkdir -p run
cp /opt/ros/humble/share/rmw_zenoh_cpp/config/DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5 run/zenoh-aibox.json5
~~~

In `run/zenoh-aibox.json5` set mode `client` and connect endpoint
`tcp/100.123.129.114:7447`. Then write the environment file:

~~~bash
cat > run/webots-ubuntu.env <<'EOF'
export ROBONIX_ATLAS=127.0.0.1:50051
export ROBONIX_SIM_ATLAS=172.17.0.1:50051
export ROBONIX_ADVERTISE_HOST=172.17.0.1
export ROBONIX_SIM_HOST_TAILSCALE=100.123.129.114
export ROBONIX_ZENOH_ROUTER=tcp/${ROBONIX_SIM_HOST_TAILSCALE}:7447
export ROBONIX_ZENOH_MODE=client
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ZENOH_SESSION_CONFIG_URI=/root/robonix/run/zenoh-aibox.json5
export ZENOH_ROUTER_CHECK_ATTEMPTS=20
export HTTPS_PROXY=http://127.0.0.1:18080
export HTTP_PROXY=http://127.0.0.1:18080
export NO_PROXY=localhost,127.0.0.1,172.17.0.1,100.74.193.22,${ROBONIX_SIM_HOST_TAILSCALE}
export no_proxy=${NO_PROXY}
EOF
~~~

Keep the two *_PROXY lines when AIBOX needs the VLM reverse tunnel (step 3);
delete them when AIBOX reaches the VLM endpoint directly. `run/vlm.env`
(`VLM_BASE_URL`, `VLM_API_KEY`, `VLM_MODEL` — the names the deploy
manifest's `${VLM_*}` references expand) already exists on the board and
never leaves it.

## 2. Start Webots on Ubuntu

~~~bash
cd /home/lxh/robonix
bash examples/webots/sim/start-aibox-ubuntu.sh --world office.wbt
~~~

Startup is complete when the script prints `[sim/start] live odom, RGB, and
lidar data received`. What follows is log tailing, not pending startup: the
script ends with a permanent `docker compose logs -f`, so the terminal never
returns to the prompt. Ctrl-C ends only the log tail; the simulator keeps
running in its container. Re-running the script is safe (compose reuses the
running container) — never start a second simulator.

## 3. VLM reverse proxy and pre-check (Ubuntu)

Skip this whole section when AIBOX reaches the VLM endpoint directly. Change
7897 if Ubuntu's proxy listens elsewhere. Keep the tunnel in its own
terminal:

~~~bash
ssh -N -o ServerAliveInterval=30 -R 127.0.0.1:18080:127.0.0.1:7897 aibox
~~~

Check the chain now; without this a broken proxy only surfaces when the first
chat task fails at the end of the deployment. From Ubuntu, the local proxy
has egress — any HTTP status is fine, a timeout is not:

~~~bash
curl -sx http://127.0.0.1:7897 -o /dev/null -w '%{http_code}\n' https://www.baidu.com
~~~

From AIBOX, the full chain tunnel → Ubuntu proxy → VLM upstream: any HTTP
status means the path works, connection refused means the tunnel is down,
and a timeout means the Ubuntu proxy or its egress is:

~~~bash
ssh aibox 'set -a; source /root/robonix/run/vlm.env; set +a; \
  curl -sx http://127.0.0.1:18080 -o /dev/null -w "%{http_code}\n" "$VLM_BASE_URL"'
~~~

## 4. Boot the full stack (AIBOX)

One-time: the board's `rbnx` **and** `robonix-soma` must carry the 180 s
`DRIVER_REGISTER_TIMEOUT` (scene's NPU load and explore's first container
exceed the old 60 s; a stale soma fails skills at 60 s even when rbnx waits
180 s):

~~~bash
ssh aibox 'cd /root/robonix && export PATH=/root/robonix/target/debug:$PATH && cargo build -p robonix-cli -p robonix-soma'
~~~

Then check `examples/webots-aibox/remote.env` (ssh alias, sim-host checkout
path, AIBOX Atlas endpoint) matches both machines — after a tailnet address
change this is the file to fix. Build once, boot, verify:

~~~bash
ssh aibox
cd /root/robonix/examples/webots-aibox
. ./boot.env
rbnx build -f robonix_manifest.yaml
rbnx boot -f robonix_manifest.yaml --no-update-check -v
~~~

Boot waits for each layer to register before starting the next; watch the
`[ OK ]` lines: the four TIAGo primitives (seconds, warm), mapping ~30 s,
nav2 ~40 s, scene ~105 s (NPU load), explore last (`[ OK ] explore
INACTIVE` — INACTIVE is its designed post-INIT state). The prim variants'
`--set` values live in the manifest's `config:` blocks; scene's in
`config/scene-aibox-npu.yaml` + the `SCENE_*` exports in `boot.env`.

## 5. Verify the run

~~~bash
rbnx caps
~~~

Expect thirteen providers: the four TIAGo primitives, mapping, nav2, scene,
explore (INACTIVE), pilot, soma, executor, liaison, vitals — all ACTIVE
except explore and executor (executor activates on the first task).

`rbnx chat` is an interactive TUI and needs a TTY — run it in an interactive
`ssh aibox` terminal. `rbnx ask` is its non-interactive sibling: same gRPC
path, one prompt, event stream to stdout, then exit (`--json` for
line-delimited JSON). Either way, send in order:

1. "What can you see in front of the robot?" — camera snapshot succeeds and
   matches the image.
2. "Explore the current room and report what you find." — poll the returned
   run_id until the Explore task reaches a successful terminal state; a
   successful tool call alone is not success. When the VLM upstream is
   degraded, the scripted `nav_stress.py` drive in the deploy-aibox-scene
   skill covers the same path without the VLM.
3. "What tasks are currently running?" — Pilot returns the current Executor
   task snapshot.

Scene-specific end-to-end checks are in the deploy-aibox-scene skill.

## 6. Stop the run

~~~bash
rbnx shutdown        # in the deploy directory, on the board
~~~

Shutdown reaches every driver through Atlas, runs the wrappers' stop hooks
(the primitive hooks sweep leftover remote wrappers/drivers on the sim host
— wrapper first, driver second), then stops the board-side components in
reverse order and removes `rbnx-boot/state.json`. Then stop the SSH reverse
forward and, last and only if the sim should go too, on Ubuntu:

~~~bash
bash /home/lxh/robonix/examples/webots/sim/stop.sh
~~~

Before starting a provider whose name is still taken, check for a surviving
wrapper (`pgrep -fa "rbnx start"` on either machine) and SIGINT it — do not
wait out the 10 min Atlas GC for a zombie you can kill in seconds.

## Troubleshooting

- **nav2 goals fail with action-server acknowledgement timeouts** — check
  the Navigation log for Zenoh missed-sample warnings and costmap messages
  about sensor timestamps earlier than the TF cache; do not retry Explore in
  that state. Restart Navigation (a full `rbnx shutdown` + boot cycle), then
  deactivate and reactivate Explore.
- **Explore times out at 60 s / stuck in Created after a cold first boot** —
  the protobuf stubs regenerate in Docker first and the container start can
  outlive soma's skill wait. First check that `robonix-soma` was rebuilt
  with the 180 s timeout (step 4); then `rbnx shutdown` and boot again —
  the warm run is green.
- **Pilot up but missing from `rbnx caps` / `rbnx ask` can't find it** —
  pilot stalls before registering while resolving the VLM context window
  (`system/pilot/src/vlm.rs` builds its reqwest client without a timeout,
  so one stalled connection through the tunnel hangs startup forever).
  Restart the boot; if it reproduces, check the tunnel first.
- **"already registered" when restarting a provider** — the previous
  instance stays in Atlas until GC (TERMINATED after 90 s, dropped ~10 min
  later; `rbnx caps` shows it). Kill any surviving wrapper first
  (`pgrep -fa "rbnx start"` on both machines), and restart the boot for a
  clean Atlas registry when rebuilding the whole deployment. The
  deploy-aibox-scene skill documents the GC details.
- **Topics or /map missing after a redeploy** — a Tailscale address
  changed: refresh `run/webots-ubuntu.env` and `run/zenoh-aibox.json5`
  (step 1) and `BOARD_ATLAS` in `examples/webots-aibox/remote.env`.
