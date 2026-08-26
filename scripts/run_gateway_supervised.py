"""
IEC 62443 FR7 "Resource Availability" -- process supervision.

A single gateway.py process is a single point of failure: if it crashes
(unhandled exception, OOM, whatever), telemetry silently stops being
processed until a human notices and restarts it by hand. This is the
minimum viable fix for that -- not redundancy/failover in the
multi-instance/load-balanced sense (this is still ONE gateway; a genuinely
redundant deployment needs multiple gateway instances behind a broker
that can route around a dead one, real infrastructure this prototype
doesn't have), but automatic restart-on-crash, which is the honest,
achievable piece of FR7 for a single-machine software prototype.

Restart behaviour: on ANY exit (crash or clean Ctrl+C-from-inside-the-child
doesn't happen since gateway.py catches KeyboardInterrupt itself and
returns 0), restart after a short delay. A backoff kicks in if gateway.py
is crash-looping (exits within CRASH_LOOP_WINDOW_SECONDS repeatedly) so a
persistent bug doesn't spin the CPU in a tight restart loop -- after
MAX_RAPID_RESTARTS in a row, back off to a longer delay instead of giving
up entirely (still favours "keep trying" over "silently stop protecting
the system", the more defensible failure mode for a security gateway).

Run this INSTEAD of `python gateway.py` directly:
    python scripts/run_gateway_supervised.py
Ctrl+C here stops both the supervisor and the supervised gateway.
"""

import os
import subprocess
import sys
import time

GATEWAY_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "gateway.py")
RESTART_DELAY_SECONDS = 2
CRASH_LOOP_WINDOW_SECONDS = 10
MAX_RAPID_RESTARTS = 5
BACKOFF_DELAY_SECONDS = 30


def main():
    rapid_restarts = 0
    print(f"[supervisor] starting gateway.py, restart-on-crash enabled (Ctrl+C to stop everything)")
    while True:
        start = time.time()
        proc = subprocess.Popen([sys.executable, GATEWAY_PATH])
        try:
            exit_code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            print("\n[supervisor] stopped.")
            return

        uptime = time.time() - start
        if exit_code == 0:
            # gateway.py only returns 0 via its own KeyboardInterrupt
            # handler -- someone deliberately stopped it inside that
            # window; don't fight that.
            print("[supervisor] gateway.py exited cleanly (0) -- not restarting.")
            return

        print(f"[supervisor] gateway.py exited with code {exit_code} after {uptime:.1f}s -- restarting")

        if uptime < CRASH_LOOP_WINDOW_SECONDS:
            rapid_restarts += 1
        else:
            rapid_restarts = 0

        if rapid_restarts >= MAX_RAPID_RESTARTS:
            print(f"[supervisor] {rapid_restarts} rapid restarts in a row -- backing off {BACKOFF_DELAY_SECONDS}s "
                  f"(this usually means a real bug, not a transient failure -- check the crash output above)")
            time.sleep(BACKOFF_DELAY_SECONDS)
            rapid_restarts = 0
        else:
            time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    main()
