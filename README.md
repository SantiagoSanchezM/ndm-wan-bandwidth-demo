# WAN circuit capacity: can it run the site?

A local OrbStack demo that answers one question: **can a WAN circuit sustain 50 Mbps,
enough to run a site?** It also shows the answer in the SNMP interface
counters the network team already trusts.

Datadog Network Path measures latency, loss and jitter, but not capacity. To prove
capacity, something has to put load on the link and something has to measure it:

- **SNMP interface counters are the measurement.** NDM keeps doing what it does today.
- **The throughput test is only the load generator.** It gives NDM something to measure
  on a link that is otherwise idle, such as a cellular backup.

We are not replacing network device monitoring. We are giving it something to measure.

## What's in the box

One simulated site with three WAN circuits. Each circuit has a far-end endpoint that
runs an iperf3 server and a real net-snmp agent, and shapes its own traffic with `tc netem`:

| Circuit   | Capacity  | Latency | Expected result |
|-----------|-----------|---------|-----------------|
| primary   | 200 Mbps  | 8 ms    | PASS            |
| secondary | 80 Mbps   | 25 ms   | PASS            |
| cellular  | 30 Mbps   | 70 ms   | **FAIL**, on purpose |

The cellular circuit is deliberately below the 50 Mbps bar. The point of the demo is
that the criterion **correctly fails a circuit that can't carry the site**, not just
that the tooling runs.

> **About the three networks.** Locally the Agent sits on three Docker networks, one per
> circuit endpoint. Treat them as **three destinations**, not as a topology. At a real
> site the Agent host has one NIC on the site LAN, and the **edge appliance
> steers each destination onto a circuit** with a path policy rule. Nothing here needs a
> multi-homed host in production.

```
docker-compose.yml
agent/
  Dockerfile                        Agent 7 + iperf3 + Ookla CLI + speedtest integration
  checks.d/wan_throughput.py        Option B: iperf3 custom check
  conf.d/wan_throughput.d/conf.yaml one instance per circuit
  conf.d/speedtest.d/conf.yaml      Option A: Ookla speedtest
  conf.d/snmp.d/conf.yaml           SNMP polling of the three endpoints (shows up in NDM)
endpoint/
  Dockerfile                        iperf3 + net-snmp + iproute2
  entrypoint.sh, set-rate           apply shaping, start snmpd and iperf3
dashboard.json                      Option B dashboard: iperf3 + SNMP (import into Datadog)
dashboard-speedtest.json            Option A dashboard: Ookla speedtest
```

## Run it

The API key comes from 1Password at launch, so it never sits on disk. Copy
`.env.1password.tpl` to a location **outside the repo** (for example
`~/.config/ndm-wan-bandwidth-demo/env.1password.tpl`) and point `DD_API_KEY` at your own item.
Then:

```sh
op run --env-file="$HOME/.config/ndm-wan-bandwidth-demo/env.1password.tpl" -- docker compose up --build -d
```

Without 1Password: `cp .env.example .env`, fill in the key, then `docker compose up --build -d`.

> Always start the stack through `op run`. A plain `docker compose up` recreates the Agent
> with an empty API key. `exec`, `logs` and `restart` don't need it.

Import both dashboards under **Dashboards → New Dashboard → Import dashboard JSON**:

- `dashboard-speedtest.json` shows **Option A** (Ookla speedtest).
- `dashboard.json` shows **Option B** (iperf3 + SNMP correlation).

Check it's healthy:

```sh
docker compose exec agent agent status          # wan_throughput, speedtest, snmp: no errors
docker compose exec agent agent check wan_throughput
docker compose exec agent agent check snmp
docker compose exec agent agent check speedtest
docker compose logs primary secondary cellular | grep shaped
```

## Test it: raise the cellular cap

Cellular is shaped to 30 Mbps, so it fails the 50 Mbps bar. To prove the verdict is a
live measurement rather than a staged result, raise its capacity on the running container:

```sh
docker compose exec cellular set-rate 80mbit 70ms
```

`set-rate` changes the `tc netem` shaping and the capacity SNMP reports, with no restart.
Within two minutes the next scheduled test runs. Then:

- the cellular tile on the iperf3 dashboard **flips green** (`meets_requirement` goes 0 → 1),
- achieved Mbps rises from ~29 to ~50, and loss drops from ~40% to 0,
- SNMP `ifHighSpeed` for the cellular endpoint reports 80 instead of 30, and the SNMP octet
  rate follows the iperf3 line up.

To see the result on screen straight away, run the check by hand. That command only prints
results; the dashboard changes on the next scheduled run:

```sh
docker compose exec agent agent check wan_throughput
```

To put it back to 30 Mbps, run `docker compose restart cellular`, which reapplies the
settings in `docker-compose.yml`.

## Option A: Ookla speedtest (community integration)

This option is already built into the Agent image. The image installs
`datadog-speedtest==2.0.0` and the official Ookla CLI (Debian package `speedtest` from the
packagecloud repo, not the python `speedtest-cli`). It measures the Agent's real internet
path to an Ookla server, not the simulated circuits, every 15 minutes.

Two config options are worth showing (`conf.d/speedtest.d/conf.yaml`):

- **`server_id`** pins one Ookla server. Without it, Ookla picks from a rotating pool, so
  an SD-WAN path policy has no stable IP to match. With it, one rule can force
  the test onto the circuit under test.
- **`interface` / `ip`** bind the **source** of the test. Network Path can't do this.

`dashboard-speedtest.json` follows the same flow as the iperf3 dashboard. It shows a PASS/FAIL
verdict for **download and upload separately** (each at 95% of 50 Mbps or better), achieved vs
required, and a pass/fail history. In place of the SNMP overlay, it
shows which Ookla server each run used. The rotating servers are the visual argument for
pinning `server_id`. The integration has no pass/fail metric, so the dashboard derives one with
a `clamp_min`/`clamp_max` formula on `speedtest.*.bandwidth.bit_per_sec`.

**Licence.** The Ookla CLI won't run until its licence is accepted, and the check has no
flag for it. The build accepts it by running one real test with `--accept-license
--accept-gdpr` as root (which runs checks in the container Agent) and as `dd-agent` (the
user on a host install). Running `--servers` with those flags exits before the acceptance
is saved, so it isn't enough. If the build had no internet access, the step warns instead
of failing. In that case, accept at runtime:

```sh
docker compose exec agent speedtest --accept-license --accept-gdpr -f json -p no
```

## Option B: the iperf3 check (`wan_throughput`)

Each instance offers **UDP at the required rate** (`iperf3 -u -b 50M`) for 30 s every
two minutes and measures what arrives. The question is "can it sustain 50 Mbps", not "how fast can we
push it". A circuit passes when it delivers at least 95% of the required rate with under
1% loss. Both thresholds are configurable (`tolerance_percent`, `max_lost_percent`).

By default the test runs in reverse (`-R`): the far end sends to the site, which is the
download direction. Set `reverse: false` for upload. `bind_ip` sets the source address
(`-B`). `protocol: tcp` switches to push-as-fast-as-possible if you want to show raw
capacity: primary reaches ~190 Mbps.

| Metric (`wan.throughput.*`) | Meaning |
|---|---|
| `mbps` | throughput received |
| `required_mbps` | the bar (`TARGET_RATE_MBPS`, default 50) |
| `headroom_mbps` | `mbps - required_mbps` (see note) |
| `jitter_ms`, `lost_percent` | UDP receiver stats |
| `meets_requirement` | **1 = pass, 0 = fail**: the success criterion, graphable |

The check has two service checks for two different conditions:

- `wan.throughput.can_connect`: did the test execute? This covers tooling health:
  unreachable or busy server, timeout, bad output.
- `wan.throughput.requirement`: did the circuit pass? **Only this one should page.**
  It reports UNKNOWN when the test didn't run.

> If a manual `agent check wan_throughput` reports `the server is busy running a test`,
> the scheduled test for that circuit is running (iperf3 serves one test at a time). Rerun
> in 30 s. It's also a live example of the split above: `can_connect` goes CRITICAL,
> `requirement` goes UNKNOWN, and nothing claims the circuit failed.

Tags: `circuit:primary|secondary|cellular`, `site:demo`, `direction`, `protocol`, `server`.

> **Headroom note.** In UDP mode the check offers exactly the required rate, so a passing
> circuit shows headroom ≈ 0. That's by design: it proves the rate is sustainable, not how
> much more fits. For real headroom, set `target_mbps` above `required_mbps` or use `protocol: tcp`.

## SNMP correlation

The endpoints run real `snmpd` (`rocommunity public`, `agentAddress udp:161`). Their eth0
counters are real, so `ifHCInOctets` / `ifHCOutOctets` rise during each test and stay flat
between tests. Each endpoint also reports its shaped rate as `ifHighSpeed`, so utilisation
is measured against the circuit's real capacity. We deliberately don't use snmpsim: its
counters are recorded and static, so they would never move with the test traffic.

How the numbers line up:

- The Datadog SNMP profile marks `ifHCInOctets` / `ifHCOutOctets` as
  `monotonic_count_and_rate`, so each is submitted twice: `snmp.ifHCOutOctets` (a monotonic
  count, octets per collection interval) and **`snmp.ifHCOutOctets.rate` (octets per
  second)**. The dashboard uses the rate.
- Octets → Mbps: **`rate × 8 / 1,000,000`**. Skip the ×8 and the SNMP line sits 8× below
  the iperf3 line.
- The test traffic leaves the endpoint, so it shows up as the endpoint's **Out** octets.
  On a real edge device the same traffic is the WAN interface's **In** octets.
- The SNMP line uses `.rollup(max)`. SNMP only shows load while a test runs, and an
  average over a long window would dilute the plateau.
- SNMP is polled every 10 s, and each test lasts 30 s, so every test gets clean samples.

**SNMP replies bypass the shaping.** Without that, polls on a saturated circuit queue
behind the test traffic and stall for 10–20 s. In production NDM polls the edge device from
the LAN side, not across the circuit under test, so this matches reality.

## Shaping

`set-rate <rate> <delay>` applies `tc netem` on the endpoint's eth0 and updates the SNMP
capacity to match. It's safe to run on a live container. The compose file grants
`NET_ADMIN`. If that capability is missing, the endpoint logs a warning and serves iperf3
unshaped instead of failing.
