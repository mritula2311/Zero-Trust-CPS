# ZT-Duo / Zero-Trust CPS

A research gateway that authenticates CPS (cyber-physical system) telemetry and
keeps **Security Trust** separate from **Process Anomaly Trust** until an
access-policy decision consumes both. An authenticated physical disturbance
should raise an operations alert while retaining telemetry; forged or
replayed traffic is rejected.

This is a **research testbed** with unresolved deployment and evidence
requirements — see [Known limitations](#known-limitations) before citing any
number here as production-ready.

For the method and its mathematics, see [METHODOLOGY.md](METHODOLOGY.md). For
requirements, scope and decision records, see [PRD.md](PRD.md). For
agent/contributor working rules (invariants that have already cost real
debugging time), see [CLAUDE.md](CLAUDE.md).

---

## Architecture

The two scores are the whole design:

| | Security Trust | Process Anomaly Trust |
|---|---|---|
| Evidence | identity, HMAC, freshness, rate | the physical reading only |
| Answers | "is this message authentic?" | "is the machine behaving?" |
| Signals | rule-based trust engine | Rule + Isolation Forest + LSTM-AE + relational scorer → fusion |

They meet **only** at the final policy decision (`policy_engine.decide`) — a
2×2 lookup of (Security Trust, Process Anomaly Trust) plus staleness, nothing
else. Blending them earlier makes "forged credentials, normal cargo" and
"valid credentials, machine shaking" indistinguishable, and those two cases
need opposite responses (block vs. alert-and-keep-telemetry).

`src/gateway.py` hosts MQTT ingestion, an HTTPS telemetry endpoint, the live
dashboard (port 8600) and a silence watchdog. The second transport's
historical filename is `coap_server.py`; it implements HTTPS POST, not CoAP
or DTLS (see PRD.md §9 for why).

Pipeline, in order:

1. Validate the envelope and identity; verify HMAC, finite sensor readings,
   boot/sequence freshness and timestamp freshness before committing device
   state. Failed-signature cooldown cannot suppress authentic telemetry.
2. Compute Security Trust from cyber evidence: rate, step-up outcomes and
   silence.
3. Fuse Rule + per-device Isolation Forest + LSTM-AE + the configured
   relational scorer (M6 Set Transformer) into Process Anomaly Trust.
4. Apply the frozen contextual bandit (legacy `USE_RL_POLICY` toggle) or the
   static two-score table. `STEP_UP` issues a nonce challenge. Automatic
   quarantine is disabled by default. All model training is offline.
5. Record decisions, explanations and NIST SP 800-207 / IEC 62443
   governance mappings in SQLite with a hash chain and separately keyed
   checkpoints. This is an implementation mapping, not certification.

### Device registry

22 identities: two configured physical devices, eighteen network-research
simulations, two legacy scalar simulations.

- `esp32-vib-001` (ESP32 + MPU6050): TRAIN/VALIDATION/TEST physical captures.
- `esp32-vib-002` (SW-420 vibration switch): TRAIN/VALIDATION/TEST physical
  captures as of 2026-09-07 (0/108 resting false positives, 115/115
  detection on TEST — see [Headline results](#headline-results)). Its slot in
  the separate constructed 20-node network benchmark remains
  `PENDING_REAL_HARDWARE_DATA` in VALIDATION/TEST — a different pipeline.

Configuration does not prove live presence; the live legacy simulator
publishes only its original three-device cohort.

### Model comparison summary

| Component | Current role |
|---|---|
| Rule, Isolation Forest, LSTM-AE | Local process baseline; training/eval must use matched, versioned artifacts. |
| Legacy GCN | Superseded as the deployed relational scorer by M6 (2026-09-07). A clean-provenance GCN policy baseline was retrained for the final policy comparison; prior fusion artifacts retained for reproducibility. |
| **Set Transformer (M6, deployed)** | Corrected checkpoint (`set_transformer_corrected.pt`), promoted 2026-09-07 after a confirmed class-weight training defect was found and fixed. Supplies the current relational score, matched fusion and matched policy. |
| Concat MLP | Efficient fixed-size deployment baseline. |
| Deep Sets | Strong set baseline. |
| Temporal Transformer | Ablation only; did not improve on LSTM-AE under a fair comparison. |
| NP-ST | Rejected ablation; negative result retained. |
| Policy (contextual bandit) | Runtime-available; a validation-tuned static table currently outperforms it — compare all families under identical validation constraints before choosing a replacement. |

---

## Headline results

(Reconstructed from `results/`, `models/`, and `scripts/build_paper_results.py`
— rerun that script to regenerate a machine-checked version of these numbers.)

| Metric | Value | Source |
|---|---|---|
| Real-hardware disturbance detection | **30/30 (100%)**, Wilson 95% CI 88.6–100% | `results/final_verification/hardware_evaluation.log` |
| Real-hardware resting false-positive rate | **5/12 (41.7%)**, Wilson 95% CI 19.3–68.0% | Session-level split, leakage-free. Earlier 0/49 and 1/29 figures are withdrawn as leaky. |
| Deployed relational scorer | M6 Set Transformer (`set_transformer_corrected.pt`), promoted 2026-09-07 | `src/relational_pin.py`, `config.py` |
| Corrected-M6 fused Macro-F1 | **0.5798** vs. GCN **0.5679** | `results/gcn_m6_corrected_comparison/fusion_comparison.json` |
| Corrected-M6 policy Macro-F1 | **0.5332** vs. fair GCN baseline **0.5303** | `results/m6_corrected_policy/policy_metrics.json` |
| Static policy vs. adaptive bandit | **Static wins** (Macro-F1 0.588 vs. 0.533) | `results/policy_comparison/metrics.json` |
| BLOCK-class recall (any policy arm) | **0/33 (0%)** — architectural, not a bug (`stealthy_forged_values`/`combined` excluded from training as unlearnable from this state space) | — |
| Level-2 explainability recovery rate | **36% (79/219)** vs. 70% target | `results/final_verification/explainability_evaluation_corrected.log` |
| SW-420 held-out real-hardware (TEST) | 0/108 resting FP, 115/115 detection | `results/sw420_real_hardware/` |
| Test suite | 193/193 passing | `python -m unittest discover -s tests` |

Two findings worth flagging explicitly:

1. **The relational scorer does not beat simpler models purely on identical
   information** in the original ablation framing (concat-MLP ≈0.985-region
   vs. GCN ≈0.838-region on Task-1). The M6 Set Transformer, added under a
   from-scratch correctly-masked protocol, does beat both (Task-1 test F1
   0.9736 vs. GNN 0.5865).
2. **A validation-tuned static policy beats the adaptive bandit** on this
   state space. The bandit only beats the deployed, unconstrained static
   table. BLOCK stays unreachable (0/33 recall) for every adaptive-policy arm
   tried, because `combined`/`stealthy_forged_values` is architecturally
   excluded from training as unlearnable from a
   `(security_trust, process_trust)` state space.

To regenerate a fully sourced, machine-checked results document:

```bash
python scripts/build_paper_results.py
```

This reads every JSON/log directly (never re-derives numbers by hand) and
writes a SHA-256 manifest of every source file it touched — diff that
manifest before trusting a regenerated number against a codebase that has
moved on.

---

## Known limitations

- **No production-deployment readiness claim.** Firmware TLS peer-certificate
  verification is unresolved: the MPU6050 firmware explicitly uses
  `CERT_NONE`. Provision and validate a verifying TLS configuration before
  any real deployment.
- **No physical network segmentation** (IEC 62443 FR5 partial) — broker ACLs
  restrict topics, not network zones.
- **No multi-instance gateway redundancy** (FR7 partial) — one crash-resilient
  process, not load-balanced.
- **No certification claim** — the NIST/IEC mappings are an implementation
  mapping with a falsifiable self-check, not third-party certification.
- **No detection claim for `stealthy_forged_values`/`combined`-class attacks**
  from single-node telemetry — BLOCK recall measures 0/33 for every policy
  arm tried.
- **Explainability recovery is 36%** against a 70% target on the single-channel
  TEST protocol — reported as measured, not concealed.
- **Real-hardware resting false-positive rate is 41.7% (5/12)**, a small,
  dependent (overlapping-window) sample — not independent sessions.

---

## Setup and local verification

Use the repository root and a Python environment with `requirements.txt`
installed:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/benchmark_crossdevice_models.py --selfcheck
python scripts/validate_virtual_device_generator.py
```

The native test runner is `unittest`, not `pytest`. The generator validator
reports an aggregate failure when MEDIUM/HIGH marginals diverge; inspect its
per-regime output.

Before starting live services, provision local secrets from
`src/secrets_local.example.py`, CA/server certificates, broker credentials and
topic ACLs. Secrets and private keys stay outside Git. Gateway startup
refuses plaintext MQTT, unconfigured broker authentication and a placeholder
gateway password; placeholder device HMAC keys cannot authenticate. File
autodetection alone does not verify the broker's running configuration.

```powershell
python src/gateway.py
# In a second terminal, same environment:
python src/device_simulator.py
```

The dashboard is served by the gateway on port 8600. A static, non-live
demonstration build of the same UI is in `design/` — open
`design/Main.dc.html` or run `node design/start-demo.mjs`. Real-device
provisioning: pinout `VCC→3.3V` (not 5V), `GND→GND`, `SDA→GPIO21`,
`SCL→GPIO22`, `AD0→GND` (I2C address `0x68`); sampling at 500 Hz, 32-sample
windows, DLPF config 1 (184 Hz anti-alias). Swapped SDA/SCL is the most
common first-time fault.

Do not run generators or trainers over the archived evidence just to
reproduce documentation. Most scripts use fixed output paths. First allocate
a separate artifact directory/checkout, preserve hashes and source-session
provenance, then follow the dependency order in
[METHODOLOGY.md](METHODOLOGY.md). Source repairs do not retroactively correct
saved model weights or measurements.

**Training order is not optional — six steps:** IF → LSTM-AE → Transformer →
GNN → fusion → RL. Each replays through the previous models. Retrain all six,
in order, after any change to features, the simulator, or the merged
dataset.

---

## Repository guide

```
src/          runtime gateway, trust/policy, inference, audit, sensor contracts
firmware/     MicroPython clients, acquisition helpers
scripts/      capture, split/merge, generation, offline training and evaluation
tests/        invariants, firmware/host equivalence, audit regressions (unittest)
data/         source/generated evidence — preserve history and provenance
models/       trained artifacts + calibration/lineage metadata
results/      saved measurements — preserve history and provenance
design/       static demo build of the dashboard UI
config/       runtime configuration
certs/        TLS certificates (gitignored contents; provisioned locally)
```

---

## Documentation set

This project intentionally keeps only three living Markdown documents plus
this README, so there is one place to look instead of dozens of
overlapping, easily-stale files:

- **README.md** (this file) — architecture, headline results, setup, repo map.
- **[METHODOLOGY.md](METHODOLOGY.md)** — the method, its mathematics and
  novelty claims.
- **[PRD.md](PRD.md)** — problem statement, scope, functional/non-functional
  requirements, success criteria, decision record.
- **[CLAUDE.md](CLAUDE.md)** — working rules and invariants for anyone (human
  or agent) editing this codebase; every entry there documents a defect that
  already happened once.

Older per-topic documents (module walkthroughs, paper-drafting scaffolding,
audit/verification logs, review trackers) have been retired from the working
tree to keep the repository navigable. Their content is preserved in git
history — recover any of them with `git log --all -- <path>` and
`git show <commit>:<path>` if needed for paper writing or a deeper audit
trail.
