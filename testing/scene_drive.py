#!/usr/bin/env python3
# SPDX-License-Identifier: MulanPSL-2.0
"""Walk the robot along a coverage sweep for Scene perception testing.

Scene testing needs camera coverage, not navigation decisions: the driver
reads the live costmap, plans a boustrophedon sweep over the free space of
whatever world is loaded, and sends the waypoints through the same navigate
skill the executor uses. No explore, no frontier or random-goal selection.
The judge stays the simulator's collision report, and the Robonix/ROS
plumbing is inherited from nav_stress.

Runs where a Robonix provider runs (the nav2 container in the Webots
example); see the deploy-aibox-scene skill for the environment.
"""

from __future__ import annotations

import argparse
import json
import math
import time

import nav_stress
from nav_stress import Tools, World, candidates, endpoint, goal_pose, log, wait_terminal

CONSUMER = "scene-drive"


def sweep_waypoints(grid, clearance_m: float, spacing_m: float, margin_m: float,
                    max_goals: int) -> list[tuple[float, float, float]]:
    """Boustrophedon coverage over free costmap cells: per y-band, walk the
    band's free x-span, alternating direction between bands. Yaw faces the
    travel direction so the camera leads the motion."""
    pts = candidates(grid, clearance_m)
    if not pts:
        return []
    ys = sorted(p[1] for p in pts)
    y0, y1 = ys[0], ys[-1]
    wps: list[tuple[float, float, float]] = []
    bands = max(1, int(math.ceil((y1 - y0) / spacing_m)))
    for b in range(bands):
        lo, hi = y0 + b * spacing_m, y0 + (b + 1) * spacing_m
        band = sorted(p for p in pts if lo <= p[1] < hi)
        if not band:
            continue
        y = band[len(band) // 2][1]  # a cell-centre y, guaranteed free nearby
        xs = sorted(p[0] for p in band)
        left, right = xs[0] + margin_m, xs[-1] - margin_m
        if right - left < 0.5:
            continue
        if b % 2 == 0:
            wps += [(left, y, 0.0), (right, y, 0.0)]
        else:
            wps += [(right, y, math.pi), (left, y, math.pi)]
        if len(wps) >= max_goals:
            break
    return wps[:max_goals]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spacing", type=float, default=1.2,
                    help="sweep line spacing in metres (camera coverage)")
    ap.add_argument("--clearance", type=float, default=0.2,
                    help="metres beyond the costmap's own inflation")
    ap.add_argument("--margin", type=float, default=0.3,
                    help="metres trimmed from each sweep end")
    ap.add_argument("--max-goals", type=int, default=24)
    ap.add_argument("--goal-timeout", type=float, default=150.0)
    ap.add_argument("--waypoints-file", default="",
                    help="JSON {\"waypoints\": [[x, y, yaw], ...]} for a "
                         "hand-tuned per-world path; skips the costmap sweep")
    ap.add_argument("--out", default="", help="write the summary JSON here too")
    a = ap.parse_args()

    nav_stress.CONSUMER = CONSUMER
    world = nav_stress.World()  # the collision judge; also feeds the sweep
    try:
        _, nav_url = endpoint("robonix/service/navigation/navigate", "mcp")
        nav = Tools(nav_url)
    except Exception as e:  # noqa: BLE001
        log(f"cannot resolve the navigate tool: {e}")
        return 2

    if a.waypoints_file:
        with open(a.waypoints_file, encoding="utf-8") as f:
            wps = [tuple(p) for p in json.load(f)["waypoints"]]
        log(f"waypoints file: {len(wps)} waypoints")
    else:
        world = nav_stress.World()
        # The map at boot covers only the spawn view; the boustrophedon
        # needs some mapped free space, so wait for a non-empty sweep plan
        # instead of acting on the first (mostly unknown) grid.
        wps = []
        for _ in range(12):
            for _ in range(60):
                if world.costmap is not None or world.map is not None:
                    break
                time.sleep(1.0)
            grid = world.costmap or world.map
            if grid is None:
                log("no /map or /global_costmap/costmap")
                return 2
            wps = sweep_waypoints(grid, a.clearance, a.spacing, a.margin, a.max_goals)
            if wps:
                break
            log("sweep plan empty on the current map; retrying in 10 s")
            time.sleep(10.0)
    log(f"sweep: {len(wps)} waypoints")
    if not wps:
        return 2

    results = []
    for n, (x, y, yaw) in enumerate(wps):
        before = len(world.collisions)
        t0 = time.time()
        r = nav("navigate", goal=goal_pose(x, y, yaw))
        if not r.get("accepted"):
            end = {"state": "REJECTED", "detail": r.get("detail", "")}
        else:
            end = wait_terminal(lambda **k: nav("status", **k), r.get("run_id", ""), a.goal_timeout)
            if end.get("state") == "TIMEOUT_LOCAL":
                nav("cancel", run_id=r.get("run_id", ""))
        hits = world.collisions[before:]
        row = {
            "goal": [round(x, 2), round(y, 2), round(yaw, 2)],
            "state": end.get("state"),
            "seconds": round(time.time() - t0, 1),
            "collisions": hits,
        }
        results.append(row)
        log(f"waypoint {n + 1}/{len(wps)} ({x:.2f}, {y:.2f}): {row['state']} "
            f"in {row['seconds']} s, collisions {len(hits)}")
        if row["state"] in {"REJECTED"} and n == 0:
            log("first waypoint rejected - check nav2 health before continuing")
            break

    summary = {
        "waypoints": len(results),
        "succeeded": sum(r["state"] == "SUCCEEDED" for r in results),
        "collisions": len(world.collisions),
        "collision_count_topic": world.count,
        "results": results,
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    return 1 if summary["collisions"] else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
