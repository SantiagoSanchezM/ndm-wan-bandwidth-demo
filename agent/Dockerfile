FROM gcr.io/datadoghq/agent:7

# iperf3 client for the wan_throughput check, plus what we need to add the Ookla repo.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      iperf3 curl gnupg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# --- Option A: Ookla speedtest ------------------------------------------------
# The check needs the official Ookla CLI (Debian package `speedtest`), not the
# python speedtest-cli. Ookla ships one static binary, so the jammy repo is fine on noble.
RUN curl -fsSL https://packagecloud.io/ookla/speedtest-cli/gpgkey \
      | gpg --dearmor -o /usr/share/keyrings/ookla.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/ookla.gpg] https://packagecloud.io/ookla/speedtest-cli/ubuntu/ jammy main" \
      > /etc/apt/sources.list.d/ookla.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends speedtest \
 && rm -rf /var/lib/apt/lists/*

# The community integration is not bundled with the Agent.
RUN agent integration install -r -t datadog-speedtest==2.0.0

# The CLI refuses to run until its licence is accepted, and the check has no flag
# for it. Accepting only sticks after a real test completes (`--servers` exits
# before saving), so run one test at build time. In the container the Agent runs
# checks as root; dd-agent (the user on a host install) is accepted too, with a
# real home so the acceptance persists. A test that fails midway saves nothing,
# so retry, and check for the saved file rather than the exit code.
# Non-fatal: if this fails (e.g. no internet at build time), see README fallback.
RUN mkdir -p /home/dd-agent && chown dd-agent /home/dd-agent && usermod -d /home/dd-agent dd-agent \
 && for u in root dd-agent; do \
      for try in 1 2 3; do \
        su "$u" -s /bin/bash -c 'speedtest --accept-license --accept-gdpr -f json -p no >/dev/null 2>&1; \
                                 test -f "$HOME/.config/ookla/speedtest-cli.json"' && break; \
        [ "$try" = 3 ] && echo "WARNING: Ookla licence not accepted for $u - see README"; \
      done; \
    done

# --- Option B: iperf3 custom check, and SNMP ------------------------------------
COPY checks.d/ /etc/datadog-agent/checks.d/
COPY conf.d/   /etc/datadog-agent/conf.d/
