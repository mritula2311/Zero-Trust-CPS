"""
Module 7 extension, Phase 9: Live Dashboard.

Swaps the console print() in gateway.py for a live web view -- polls
audit_log.recent() on a timer and renders it as a table plus a line chart
of trust score over time per device.

Run alongside the gateway + a telemetry source (device_simulator.py or the
real ESP32/firmware/main.py), NOT instead of them -- this only reads the
SQLite audit log, it doesn't participate in the pipeline itself:

    streamlit run dashboard.py

Report Section 7.3 / synopsis Section 7.3 calls the audit_log table
"governance evidence" -- this is the view that makes that evidence legible
without reading raw SQL rows. The "NIST SP 800-207 completeness" section
below is specifically the "compliance mapping view" synopsis Section 7.3
names as Layer 3's third output (alongside the live table and the trust
chart) -- not a nice-to-have, a named deliverable.
"""

import time

import pandas as pd
import streamlit as st

import audit_log
import iec62443_mapping
import nist_mapping
from config import DEVICE_REGISTRY, THRESHOLD_ALLOW, THRESHOLD_STEP_UP, NIST_TENETS

REFRESH_SECONDS = 2
ROWS_TO_FETCH = 300

st.set_page_config(page_title="Zero-Trust CPS Dashboard", layout="wide")
st.title("Zero-Trust CPS -- Live Trust & Access Decisions")
st.caption(
    "Polls data/audit_log.db every "
    f"{REFRESH_SECONDS}s. Run the gateway + device_simulator.py (or the "
    "ESP32 firmware) alongside this for live data."
)

placeholder = st.empty()


def render(rows: list[dict]) -> None:
    with placeholder.container():
        if not rows:
            st.info("No audit log entries yet -- start the gateway and a telemetry source.")
            return

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

        latest = df.groupby("device_id").tail(1).set_index("device_id")
        cols = st.columns(max(len(DEVICE_REGISTRY), 1))
        for i, device_id in enumerate(DEVICE_REGISTRY):
            with cols[i % len(cols)]:
                if device_id in latest.index:
                    row = latest.loc[device_id]
                    st.metric(
                        device_id,
                        f"trust={row['trust_score']:.2f}",
                        delta=row["decision"],
                        delta_color="off",
                    )
                else:
                    st.metric(device_id, "no data yet")

        st.subheader("Trust score over time")
        chart_df = df.pivot_table(index="timestamp", columns="device_id", values="trust_score")
        st.line_chart(chart_df)
        st.caption(
            f"ALLOW >= {THRESHOLD_ALLOW}  |  {THRESHOLD_STEP_UP} <= STEP_UP < {THRESHOLD_ALLOW}  |  DENY < {THRESHOLD_STEP_UP}  "
            "(reference lines for the Phase 5 static policy -- the live decision column may "
            "differ if config.USE_RL_POLICY is on, since Phase 8's bandit can diverge from these thresholds)"
        )

        st.subheader("Recent decisions")
        display_cols = [
            "timestamp",
            "device_id",
            "auth_ok",
            "trust_score",
            "confidence",
            "decision",
            "policy_source",
            "transport",
            "anomaly_score",
            "lstm_score",
            "gnn_score",
            "fused_score",
            "nist_tenets",
            "reason",
        ]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[display_cols].sort_values("timestamp", ascending=False),
            use_container_width=True,
            height=400,
        )

        st.subheader("NIST SP 800-207 governance completeness")
        st.caption(
            "Synopsis Section 7.3's 'compliance mapping view' — what proportion of "
            f"the last {len(df)} decisions are traceable evidence for each tenet "
            "(Section 10.1's 'governance completeness' evaluation metric)."
        )
        report = nist_mapping.completeness_report(rows)
        tenet_df = pd.DataFrame(
            [
                {"Tenet": f"{n}. {NIST_TENETS[n]}", "Coverage": frac}
                for n, frac in sorted(report.items())
            ]
        ).set_index("Tenet")
        st.bar_chart(tenet_df["Coverage"])
        st.dataframe(
            tenet_df.style.format({"Coverage": "{:.0%}"}),
            use_container_width=True,
        )
        if report and min(report.values()) < 1.0:
            gap_tenets = [n for n, frac in report.items() if frac < 1.0]
            st.caption(
                f"Tenet(s) {', '.join(str(n) for n in sorted(gap_tenets))} aren't covered by every "
                "decision — for tenet 2 (secured communication) that's expected until every message "
                "arrives over MQTT/TLS or HTTPS; for tenet 7 (telemetry improves posture) that's "
                "expected before the fusion engine finishes training."
            )

        st.subheader("IEC 62443-3-3 Foundational Requirements coverage")
        st.caption(
            "CLAUDE.md Section 6/10's second governance standard, alongside NIST SP 800-207 above. "
            "FR5/FR7 are marked PARTIAL honestly — real sub-controls exist and their coverage is "
            "computed, but the full requirement (physical network segmentation / multi-instance "
            "redundancy) genuinely doesn't hold on a single machine — see iec62443_mapping.py."
        )
        fr_coverage = iec62443_mapping.fr_coverage_report(rows)
        status_label = {"implemented": "Implemented", "partial": "Partial", "not_implemented": "Not implemented"}
        fr_rows = []
        for fr, info in iec62443_mapping.FOUNDATIONAL_REQUIREMENTS.items():
            coverage = fr_coverage.get(fr) if info["status"] != "not_implemented" else None
            fr_rows.append({"FR": f"{fr}. {info['name']}", "Status": status_label[info["status"]], "Coverage": coverage})
        fr_df = pd.DataFrame(fr_rows).set_index("FR")
        st.dataframe(
            fr_df.style.format({"Coverage": lambda v: f"{v:.0%}" if v is not None else "—"}),
            use_container_width=True,
        )
        with st.expander("Security Level (SL) self-assessment"):
            st.text(iec62443_mapping.SECURITY_LEVEL_ASSESSMENT)


audit_log.init_db()

# Streamlit re-executes this whole script top-to-bottom on every rerun, so
# this isn't a real loop -- render once, sleep, then st.rerun() throws to
# restart the script from the top for the next cycle. (No external
# autorefresh package needed; this is the standard poll-and-rerun pattern.)
render(audit_log.recent(ROWS_TO_FETCH))
time.sleep(REFRESH_SECONDS)
st.rerun()
