# Flock mode

Several simulated robots cooperating on one task. Ships since v0.3, **simulator only**,
and labelled experimental. Two demos:

```bash
uvx quackd run flock-kick --provider fake --seed 3               # ducks only: split, auction, kick
uvx quackd run reachy-spots-duck-kicks --provider fake --seed 3  # a Reachy Mini head spots, a duck kicks
```

In the first, ducks split the search for a ball, the one that bids the shortest camera
distance wins the kick, and everyone else keeps clear. In the second (0.4), two different
bodies share the job: a stationary head that can look but not walk finds the ball and
judges the kick from its own camera, a duck that can walk and kick does the kicking. One
GIF, one `flock.jsonl` you can read the cooperation out of, zero API keys.

## What a flock is

2 to 4 robots in one shared arena on one shared clock, each with its **own** safety
executor enforcing the same `.duck` contract: allowlist, budgets, machine enforced abort
rules, per robot transcript. Ducks come in the four colorways (Cream, Sky, Lavender,
Graphite); a Reachy Mini head sits at a fixed wall pose. A deterministic **coordinator**
referees. Add a `flock:` block to a `.duck` file or pass `--flock N` to any duck; name the
members' robots with `robots:` in the file or `--robots name=<adapter>:<backend>,...`.
Every member acts only through the verbs its own manifest provides
([ADR-0020](adr/0020-heterogeneous-flocks.md)).

## The bus

All coordination crosses a tiny in process pub/sub bus, one message at a time, and every
message lands in `flock.jsonl`. Eight message kinds: `TASK` (the plan), `BID` (a sighting
with the bidder's own camera distance estimate and, with roles, the role it bids for and
the verbs it provides), `CLAIM` (the one kick permit, with the role assignments), `ROLE`
(SEARCH a heading sector, KICK, YIELD, STOP, and with roles SPOT and JUDGE), `HB`
(heartbeat for the watchdog), `RESULT` (kicked, miss, search empty, budget, aborted, and
with roles `kick_done`), `HINT` (an arena frame target estimate, sim only) and `VERDICT`
(the spotter's judgement). The bus is a small protocol so a LAN bus (MQTT) can slot in for
real robots. Only the in process implementation is used by default, and nobody ever awaits
the bus, which keeps the shared clock deadlock free.

## The auction, in one paragraph

Contract Net, the same shape RoboCup teams use. The first `BID` opens a window of 0.4 s
of sim time. When it closes, the lowest camera distance wins, ties break on the member
name, and a previous kicker keeps its claim unless a challenger undercuts it by the
hysteresis margin (20 % by default), which stops role oscillation. The claim carries a
lease (6 s), a fixed fuse from the moment it is granted. A miss or an expired lease
releases the claim and the failed duck sits out a cooldown, during which it may keep
searching but cannot bid. A lost heartbeat also releases the claim, but that duck is
presumed dead and excluded for good. Either way everyone re-scans the full circle (the
ball has moved) and the auction runs again. Ducks cannot fall in the 2D simulator, so
fall handling waits for hardware.

## Roles

- **SEARCH**: orient to your heading sector (if `walk` is allowed), `search_scan` inside
  it, quack on a sighting (the theatrical part), publish a `BID`.
- **KICK**: `walk_to` the target, `kick`, report the result. The contract's criterion is
  total ball displacement, so a rally of short kicks counts.
- **YIELD**: stop, and back away when the coordinator's ground truth check says you are
  inside the minimum separation ring, or as blind courtesy when your own last ball
  estimate was.
- **STOP**: the run is over.

Each role step is one verb through that duck's own executor. A role change mid verb
preempts it cleanly and does not count as a failure.

## Heterogeneous roles (0.4)

A `duck: 1` file may declare `flock.roles`, and quackd knows exactly two:

```yaml
flock:
  members: [reachy-01, duck-01]
  roles:
    spotter: {requires: [observe, gaze]}
    kicker: {requires: [go_to, kick]}
robots:
  reachy-01: reachy_mini:sim2d
  duck-01: microduck:sim2d
```

- **Capability aware bids.** A robot bids only for a role whose `requires` its manifest
  satisfies (aliases count: `get_frame` satisfies `observe`). The coordinator checks every
  bid again before counting it, so a bid from a robot we do not run cannot claim a role it
  cannot do. The cost stays the robot's own camera distance, so no shared map is needed.
- **One auction, several roles.** Roles are filled most constrained first (fewest eligible
  bidders, then role name), lowest own distance wins, ties break on the member name, and a
  previous kicker keeps its claim under the same hysteresis rule. The **spotter is held
  for the run** (its reference frame must not change between kicks); the kicker is
  re auctioned every cycle. A duck can spot too, so two ducks make a valid spotter and
  kicker pair; a head cannot kick.
- **SPOT**: gaze at the sighting, take a fresh frame, keep the target in view. The
  spotter's first sighting is its reference point.
- **KICK, with roles**: `go_to`, `kick`, step aside, and report `kick_done`. The actor
  never evaluates success.
- **JUDGE**: the spotter sweeps its gaze around the last sighting with a fresh frame at
  each look and publishes a `VERDICT`: `moved` when the target is more than the contract's
  0.3 m plus a judge margin from the reference, `not_moved`, or `lost`. The judge margin
  (0.15 m by default) exists because the size based distance estimate quantises in about
  0.2 m steps beyond 1.5 m: a strict spotter costs a re kick, a lenient one would let the
  world's veto fail the run. Only `moved` is a success; anything else sends the kicker
  back to search and kick again against the same reference, so a rally adds up.

The spotter judges, the world vetoes: `summary.json` only says `success` when the
spotter's verdict and the simulator's `ball_displacement_m` agree.

## Frame of reference

There is no computable relative frame between two robots on hardware: the Microduck has
no absolute localisation and quackd does not know where a Reachy Mini is mounted. Two
consequences shape the design. The spotter judges displacement in its **own camera
frame**, against its own first sighting, which needs no shared frame at all; that is why
a stationary spotter is the honest judge on hardware too. And **frame hints** (`HINT`
messages) are the spotter's arena frame estimate of the target, which only exist in the
simulator where every robot knows its pose: a receiver uses one solely to choose which
way to turn before its own `search_scan`, every approach and every kick uses the kicker's
own camera. `flock.frame_hints: auto` turns them on only when every member runs in
`sim2d`; on hardware they are off. A fixed camera can be occluded by static scenery; the
shipped head pose sees the ball at spawn on most seeds and on every seed once it turns,
and an occluded spotter simply reports `lost` and the flock re searches. That limit is
documented, not worked around with ground truth.

## What the LLM does, and does not do

At most **one** model call per run: the planner may tune task parameters (target label,
approach distance, scan step, timeout) through a single forced tool call. Numeric
parameters are clamped into the schema's ranges, an invalid field is dropped on its own
(the valid ones survive), and a missing or broken call falls back to deterministic
defaults, logged. With `--provider fake` even that call is skipped and the plan is a pure
function. The auction, the roles and the steering are deterministic code. Per duck LLM
pilots and LLM negotiated bids are still deliberately out of scope: they would cost N
times the tokens and latency, and the demo does not need them to be honest.
`summary.json` records `planner.llm_calls` (0 or 1) as proof.

## Ground truth

The outcome is judged by the coordinator from sim telemetry (`ball_displacement_m`), not
from any model's claim. A member reporting a kick the world did not record turns the run
into a failure. Duck to duck safety separation is watched from world ground truth: while
a claim is live the coordinator measures every other duck's true distance to the kicker
and orders an intruder to retreat, with the motion still running through that duck's own
executor. The kicker's ball approach uses perception only, exactly like a solo run.

## Reading a flock run

```
runs/<timestamp>-flock-kick/
  flock.jsonl          # the coordinator's log: every bus message, auction, verb
  summary.json         # outcome, kicker, auctions, bids, planner proof, per duck rollup;
                       # with roles also robots, roles, assignments, spotter and verdicts
  run.gif              # world view | the claimant's own camera, with phase captions
  ducks/duck-0/        # per robot transcript.jsonl and frames/ (no summary.json on purpose)
```

Three annotated lines from a real `flock.jsonl`, and three more from a heterogeneous run:

```jsonc
{"sim_t": 2.4, "kind": "bus", "msg": {"kind": "BID", "src": "duck-1", "ball_dist_m": 0.62}}
{"sim_t": 2.8, "kind": "auction_decision", "kicker": "duck-1", "bids": {"duck-1": 0.62}, "tie": false}
{"sim_t": 8.6, "kind": "bus", "msg": {"kind": "RESULT", "src": "duck-1", "status": "kicked", "ball_moved_m": 0.59}}

{"sim_t": 0.3, "kind": "bus", "msg": {"kind": "BID", "src": "reachy-01", "role": "spotter", "ball_dist_m": 1.1, "provides": ["gaze", "observe", "..."]}}
{"sim_t": 9.3, "kind": "bus", "msg": {"kind": "RESULT", "src": "duck-01", "status": "kick_done", "ball_moved_m": 0.16}}
{"sim_t": 9.4, "kind": "bus", "msg": {"kind": "VERDICT", "src": "reachy-01", "kicker": "duck-01", "verdict": "moved", "moved_m": 0.38}}
```

## The shared clock

Sim time is a shared resource: the world advances one tick only while every participant
(each duck and the coordinator) is asleep, and it freezes while anyone thinks. A slow LLM
therefore costs zero sim time, and with `--provider fake` and a fixed seed a flock run is
reproducible. Wall clock heartbeat scheduling is the one nondeterministic input, and it
only influences failure path timing, as in solo runs.

## Which robots can join

Flock mode knows the **Microduck** and the **Reachy Mini**. Any other adapter is refused
when the run starts, with the names it does know. An Open Duck Mini cannot join a flock
yet, and that is a limit of `quackd/flock/runner.py`, not of the robot: extending it is
future work rather than a hardware problem.

## Status and future work

Sim only. Nothing multi robot has run on hardware, and the acoustic channel stays
theatrical (a quack, or a Reachy's expressive sound, marks the sighting; Wi Fi would carry
the real data). Two choreographies ship: `flock-kick` (ducks) and
`reachy-spots-duck-kicks` (a head and a duck), both 10 of 10 seeds with scripted pilots
and ground truth checks. An MQTT bus implementing the same `Bus` protocol exists
([lan.md](lan.md)), library only and tested on a fake broker; a flock across machines
also needs a clock across machines, which is future work, as are hardware flocks once
Microducks ship. See [adapter-status.md](adapter-status.md) for the wider honesty
table.
