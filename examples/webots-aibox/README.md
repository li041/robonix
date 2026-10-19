# webots-aibox — full-stack split deployment

One `rbnx boot` on the AIBOX board brings up the whole stack for the TIAGo
Webots simulation:

- **AIBOX board**: Atlas, soma, executor, pilot, liaison, vitals, mapping
  (native), nav2 (native), scene (native, NPU), explore (docker).
- **Ubuntu sim host**: the four TIAGo primitives, started through SSH
  wrappers (`primitives/*` forward their `build`/`start`/`stop` over
  `remote.env:HOST_SSH`), each docker-exec'ing its driver into the sim
  container.

The Webots sim itself stays outside boot — it is a GUI container owned by
`examples/webots/sim/start-aibox-ubuntu.sh` / `sim/stop.sh`.

## One-time setup

1. Board → sim host SSH, BatchMode-capable (see
   `.agents/skills/deploy-aibox-ubuntu/SKILL.md` §0): generate a keypair on
   the board, authorize its public key on the sim host, add the
   `aibox-ubuntu` alias to the board's `~/.ssh/config`.
2. `remote.env` — check `HOST_WEBOTS_ROOT` and `BOARD_ATLAS` still match the
   two machines' Tailscale addresses.
3. The board's `run/webots-ubuntu.env` (Zenoh client wiring) and
   `run/vlm.env` (VLM credentials) exist — `boot.env` sources both.
4. The three service/skill packages are built under
   `examples/webots/rbnx-boot/cache/` on the board (the manifest references
   them by `path:`; `rbnx build -f robonix_manifest.yaml` keeps them built).

## Bring up

```bash
# Ubuntu sim host:
bash examples/webots/sim/start-aibox-ubuntu.sh --world office.wbt
# wait for "[sim/start] live odom, RGB, and lidar data received"

# AIBOX board:
cd /root/robonix/examples/webots-aibox
. ./boot.env
rbnx build -f robonix_manifest.yaml
rbnx boot -f robonix_manifest.yaml --no-update-check -v
```

Boot waits for each layer to register before the next: the four primitives
must be ACTIVE before mapping starts, mapping before nav2, explore last.

Verify with `rbnx caps -v` (expect the four TIAGo primitives, mapping, nav2,
explore) and a `rbnx ask "What can you see in front of the robot?"`.

## Tear down

```bash
rbnx shutdown        # on the board, in the deployment directory
```

Shutdown reaches each remote driver via Atlas, then the stop hooks sweep any
leftover remote wrapper or driver (wrapper first — a live wrapper would
respawn its driver), then the board-side processes. Stop the sim last on the
Ubuntu host with `bash examples/webots/sim/stop.sh`.

## Known trade-offs

- The remote wrapper dies with its SSH channel; the drivers it spawned are
  docker-exec'd and can outlive it. The stop hooks are the cleanup path, and
  Atlas GC (TERMINATED after 90 s, dropped ~10 min later) reclaims
  registrations when the sim host is unreachable.
- Boot cannot restart a remote driver; a crashed primitive needs a full
  `rbnx shutdown` + boot cycle.
- If a primitive start dies at registration, check the sim host first:
  the sim container must be running and reachable before boot starts.
- A cold first boot can time out on explore (its Docker container is built
  inside soma's registration wait). Both `rbnx` **and** `robonix-soma` on
  the board must be rebuilt with the 180 s `DRIVER_REGISTER_TIMEOUT`
  (`cargo build -p robonix-cli -p robonix-soma`) — a stale soma fails the
  skill after 60 s.
- The scene service needs the NPU prerequisites from
  `system/scene/AIBOX_MODEL_PORTING.md` (graphs under
  `/root/robonix/dualmap/model/npu`, patched DualMap at `/opt/dualmap`,
  torch weights) and the `SCENE_*` env that `boot.env` exports. Its build
  warns when the optional concept-graphs extra fails to pip-install; scene
  runs without it.
- Pilot can hang before registering if its VLM context-window probe
  (no request timeout in `system/pilot/src/vlm.rs`) hits a stalled tunnel
  connection. Restart the boot; check the tunnel if it reproduces.
