"""
wan_throughput: can this circuit carry the required bandwidth?

Runs one iperf3 test per instance and reports whether the circuit met the
requirement. By default it offers UDP at exactly the required rate and checks
what arrives. The question is "can it sustain 50 Mbps", not "how fast can it go".
"""
import json
import os
import subprocess

from datadog_checks.base import AgentCheck

__version__ = "1.0.0"


class WanThroughputCheck(AgentCheck):
    __NAMESPACE__ = "wan.throughput"

    def check(self, _):
        server = self.instance["server"]
        required = float(self.instance.get("required_mbps") or os.environ.get("TARGET_RATE_MBPS", 50))
        protocol = self.instance.get("protocol", "udp")
        reverse = self.instance.get("reverse", True)
        tags = list(self.instance.get("tags", [])) + [
            "server:{}".format(server),
            "protocol:{}".format(protocol),
            "direction:{}".format("download" if reverse else "upload"),
        ]

        result, error = self._run_iperf(server, required, protocol, reverse)

        # Service check 1: did the test execute? Tooling health, not circuit health.
        if error:
            self.log.warning("iperf3 test against %s failed: %s", server, error)
            self.service_check("can_connect", AgentCheck.CRITICAL, tags=tags, message=error)
            self.service_check("requirement", AgentCheck.UNKNOWN, tags=tags,
                               message="Test did not run: " + error)
            return
        self.service_check("can_connect", AgentCheck.OK, tags=tags)

        mbps, jitter, lost = result
        max_lost = float(self.instance.get("max_lost_percent", 1.0))
        tolerance = float(self.instance.get("tolerance_percent", 5.0))
        passed = mbps >= required * (1 - tolerance / 100) and (lost is None or lost <= max_lost)

        self.gauge("mbps", mbps, tags=tags)
        self.gauge("required_mbps", required, tags=tags)
        self.gauge("headroom_mbps", mbps - required, tags=tags)
        self.gauge("meets_requirement", 1 if passed else 0, tags=tags)
        if jitter is not None:
            self.gauge("jitter_ms", jitter, tags=tags)
        if lost is not None:
            self.gauge("lost_percent", lost, tags=tags)

        # Service check 2: did the circuit pass? This is the one to page on.
        if passed:
            self.service_check("requirement", AgentCheck.OK, tags=tags)
            return
        summary = "{:.1f} Mbps achieved vs {:.0f} required".format(mbps, required)
        if lost is not None:
            summary += ", {:.1f}% loss (max {:.1f}%)".format(lost, max_lost)
        self.service_check("requirement", AgentCheck.CRITICAL, tags=tags, message=summary)

    def _run_iperf(self, server, required, protocol, reverse):
        """Returns ((mbps, jitter_ms, lost_percent), None) or (None, error_message)."""
        duration = int(self.instance.get("duration", 10))
        cmd = ["iperf3", "-c", server, "-p", str(self.instance.get("port", 5201)),
               "-t", str(duration), "-J"]
        if protocol == "udp":
            target = float(self.instance.get("target_mbps", required))
            cmd += ["-u", "-b", "{}M".format(target)]
        if reverse:
            cmd.append("-R")
        if self.instance.get("bind_ip"):
            cmd += ["-B", self.instance["bind_ip"]]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 20)
        except subprocess.TimeoutExpired:
            return None, "iperf3 timed out after {}s".format(duration + 20)
        except OSError as e:
            return None, "could not run iperf3: {}".format(e)

        try:
            result = json.loads(proc.stdout)
        except ValueError:
            return None, "unparseable iperf3 output (exit {}): {}".format(
                proc.returncode, (proc.stderr or proc.stdout).strip()[:200])

        # iperf3 -J reports failures (busy server, refused...) in an "error" field.
        if result.get("error"):
            return None, "iperf3 error: {}".format(result["error"])
        if proc.returncode != 0:
            return None, "iperf3 exited {}".format(proc.returncode)
        try:
            return self._parse(result, protocol), None
        except (KeyError, TypeError) as e:
            return None, "unexpected iperf3 JSON, missing {}".format(e)

    @staticmethod
    def _parse(result, protocol):
        """Returns (mbps, jitter_ms, lost_percent) as seen by the receiver."""
        end = result["end"]
        if protocol == "udp":
            # sum_received is what actually crossed the circuit; older iperf3 only has sum.
            s = end.get("sum_received") or end["sum"]
            return s["bits_per_second"] / 1e6, s.get("jitter_ms"), s.get("lost_percent")
        return end["sum_received"]["bits_per_second"] / 1e6, None, None
