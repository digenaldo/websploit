#!/usr/bin/env python3
"""Golden-stack guard for docker-compose.yml.

Fails if the default stack (no Compose profile) drifts from the checked-in
fingerprint in golden-stack.txt: services, container names, static IPs,
host ports, restart policy, platform, image/build source, resource limits,
and the networks a default `up` creates. It also pins which services the
opt-in `ai` profile adds on top of the default stack.

Usage (from anywhere):
    python3 .github/golden-stack/check.py            # compare, exit 1 on drift
    python3 .github/golden-stack/check.py --update   # rewrite the fixture

Set COMPOSE to test a specific Compose binary, e.g.
    COMPOSE=/usr/bin/docker-compose python3 .github/golden-stack/check.py

Only `docker compose config` is used: no daemon, no containers.
"""

import argparse
import difflib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURE = HERE / "golden-stack.txt"
OPT_IN_PROFILES = ["ai"]

HEADER = """\
# Golden fingerprint of the default WebSploit stack (no Compose profile).
# Checked by .github/golden-stack/check.py in CI. A diff here means the
# default `docker compose up -d` changed. Only regenerate it (--update) for an
# intentional, reviewed change to the default stack.
"""


def compose(compose_file, *args, profiles=()):
    env = dict(os.environ)
    # A stray COMPOSE_PROFILES would silently turn the default stack into a profiled one.
    env.pop("COMPOSE_PROFILES", None)
    cmd = shlex.split(os.environ.get("COMPOSE", "docker compose"))
    cmd += ["-f", str(compose_file)]
    for profile in profiles:
        cmd += ["--profile", profile]
    cmd += list(args)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("error: %s failed:\n%s" % (" ".join(cmd), result.stderr))
    return result.stdout


def fmt(value):
    return "-" if value in (None, "", [], {}) else str(value)


def service_line(name, svc, base_dir):
    if svc.get("build"):
        context = Path(svc["build"]["context"])
        try:
            context = context.relative_to(base_dir)
        except ValueError:
            pass
        source = "build:%s" % context.as_posix()
    else:
        source = "image:%s" % svc.get("image")

    networks = svc.get("networks") or {}
    ips = ",".join(
        "%s=%s" % (net, fmt((cfg or {}).get("ipv4_address")))
        for net, cfg in sorted(networks.items())
    )

    ports = ",".join(
        "%s%s:%s/%s" % (
            p["host_ip"] + ":" if p.get("host_ip") else "",
            fmt(p.get("published")),
            p.get("target"),
            p.get("protocol", "tcp"),
        )
        for p in svc.get("ports", [])
    )

    resources = (svc.get("deploy") or {}).get("resources")
    return " ".join([
        "service", name,
        "container=%s" % fmt(svc.get("container_name")),
        "ip=%s" % fmt(ips),
        "ports=%s" % fmt(ports),
        "restart=%s" % fmt(svc.get("restart")),
        "platform=%s" % fmt(svc.get("platform")),
        "source=%s" % source,
        "mem_limit=%s" % fmt(svc.get("mem_limit")),
        "cpus=%s" % fmt(svc.get("cpus")),
        "deploy_resources=%s" % fmt(json.dumps(resources, sort_keys=True) if resources else None),
    ])


def network_line(name, net):
    ipam = [
        "subnet:%s,gateway:%s" % (fmt(c.get("subnet")), fmt(c.get("gateway")))
        for c in (net.get("ipam") or {}).get("config") or []
    ]
    return " ".join([
        "network", name,
        "driver=%s" % fmt(net.get("driver")),
        "internal=%s" % str(bool(net.get("internal"))).lower(),
        "ipam=%s" % fmt(";".join(ipam)),
    ])


def fingerprint(compose_file):
    base_dir = compose_file.resolve().parent
    default = json.loads(compose(compose_file, "config", "--format", "json"))

    lines = [HEADER]
    # Compose only keeps networks that an enabled service uses, so this is the
    # set of networks a default `up` actually creates.
    for name, net in sorted((default.get("networks") or {}).items()):
        lines.append(network_line(name, net))
    for name, svc in sorted(default["services"].items()):
        lines.append(service_line(name, svc, base_dir))

    default_services = set(default["services"])
    for profile in OPT_IN_PROFILES:
        services = compose(compose_file, "config", "--services", profiles=[profile]).split()
        added = sorted(set(services) - default_services)
        lines.append("profile %s adds: %s" % (profile, " ".join(added) or "-"))

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=REPO / "docker-compose.yml",
                        help="compose file to check (default: repo docker-compose.yml)")
    parser.add_argument("--update", action="store_true",
                        help="rewrite golden-stack.txt from the compose file")
    args = parser.parse_args()

    actual = fingerprint(args.file)
    if args.update:
        FIXTURE.write_text(actual)
        print("updated %s" % FIXTURE.relative_to(REPO))
        return 0

    expected = FIXTURE.read_text()
    if actual == expected:
        print("golden-stack: default stack unchanged (%d services)" % actual.count("\nservice "))
        return 0

    sys.stdout.writelines(difflib.unified_diff(
        expected.splitlines(keepends=True), actual.splitlines(keepends=True),
        fromfile="golden-stack.txt (expected)", tofile="%s (actual)" % args.file,
    ))
    print("\ngolden-stack: DRIFT in the default stack. If this change is intentional, "
          "run `python3 .github/golden-stack/check.py --update` and justify it in the PR.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
