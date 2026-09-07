# ZT-Duo / Zero-Trust CPS

> **Current reference, 2026-09-07 (final corrected-M6 pass):** Use the [paper master guide](docs/paper/00_PAPER_MASTER_GUIDE.md), [architecture](docs/paper/02_SYSTEM_ARCHITECTURE.md), [numerical authority](docs/paper/13_RESULTS_MASTER_TABLES.md), [claim gate](docs/paper/17_CLAIM_EVIDENCE_MATRIX.md) and [limitations](docs/paper/18_LIMITATIONS_AND_THREATS_TO_VALIDITY.md). The configured gateway uses a corrected M6 Set Transformer checkpoint with its matched fusion and policy artifacts (promoted after a confirmed training defect was found and fixed in the originally-deployed checkpoint, preserved as historical evidence); the standalone M1–M9 benchmark and preserved GCN replay are separate evidence. M6 comparative gains (fusion and policy) are now measured under an explicitly-pinned, held-out-replay-qualified comparison — see 13 O4/O5. SW-420 has TRAIN capture only. Older sections below retain their historical scope.


A research gateway that authenticates CPS telemetry and keeps **Security Trust**
separate from **Process Anomaly Trust** until an access policy consumes both.
An authenticated physical disturbance should raise an operations alert while
retaining telemetry; forged or replayed traffic is rejected.

Begin paper writing at the [paper master guide](docs/paper/00_PAPER_MASTER_GUIDE.md).
The [results history](RESULTS.md), [requirements](PRD.md) and
[methodology history](METHODOLOGY.md) preserve earlier decisions and experiments.
This is a research testbed with unresolved deployment and evidence requirements.

## What runs

`src/gateway.py` hosts MQTT ingestion, an HTTPS telemetry endpoint, the dashboard
and a silence watchdog. Shared pipeline state is serialized by a lock. The second
transport's historical filename is `coap_server.py`; it implements HTTPS POST,
not CoAP or DTLS.

1. Validate the envelope and identity; verify HMAC, finite sensor readings,
   boot/sequence freshness and timestamp freshness before committing device state.
   Failed-signature cooldown cannot suppress authentic telemetry.
2. Compute Security Trust from cyber evidence: rate, step-up outcomes and silence.
3. Fuse Rule + per-device Isolation Forest + LSTM-AE + the configured M6 Set Transformer
   into Process Trust. Both trust scores are high-is-good.
4. Apply the frozen contextual bandit (the legacy `USE_RL_POLICY` toggle) or the
   static two-score table. `STEP_UP` issues a nonce challenge. Automatic
   quarantine is disabled by default. All training is offline.
5. Record decisions, explanations and governance mappings in SQLite with a
   hash chain and separately keyed checkpoints. This is an implementation mapping,
   not certification to NIST or IEC standards.

The registry has 22 identities: two configured physical devices, eighteen network
research simulations and two legacy scalar simulations. `esp32-vib-001`
(ESP32 + MPU6050) has TRAIN/VALIDATION/TEST physical captures. `esp32-vib-002`
(SW-420) has a TRAIN-only capture (`20260905_162002`); its held-out captures
remain pending. The live legacy simulator publishes only its original
three-device cohort, excluding configured physical IDs; network simulations use
the dedicated data-generation scripts. Configuration does not prove live presence.

## What the research supports

| Component | Current role |
|---|---|
| Rule, Isolation Forest, LSTM-AE | Local process baseline; training and evaluation must use matched, versioned artifacts. |
| Legacy GCN | Superseded as the deployed relational scorer by M6 (2026-09-07); corrected ablations and topology probes do not support a general GNN superiority claim. A fair, clean-provenance GCN policy baseline was retrained for the final policy comparison (`adaptive_pdp_qtable_gcn_corrected.json`). Prior fusion artifacts retained (`models/*_gcn_backup.*`) for reproducibility. |
| Set Transformer (M6/M8/M9) | A corrected M6 checkpoint (`set_transformer_corrected.pt`, promoted 2026-09-07 after a confirmed class-weight training defect was found and fixed in the originally-deployed checkpoint) supplies the current gateway relational score, matched fusion and matched policy. Standalone benchmark selection remains a separate protocol; comparative runtime gains over GCN are now measured (fusion +~1-1.2 Macro-F1 pts, policy +0.0029 macro-F1), held-out-replay-qualified — see 13 O4/O5. M8/M9 remain research candidates. |
| Concat MLP | Efficient fixed-size deployment baseline to compare under matched calibration. |
| Deep Sets | Strong set baseline. |
| Temporal Transformer | Ablation only; the fair undiluted comparison did not improve on LSTM-AE. |
| NP-ST | Rejected ablation; negative results retained. |
| Policy | Bandit is the runtime default; compare all families under identical validation constraints before choosing a replacement. |

Ten-seed topology results support different GCN/GATv2 sensitivity patterns and
an interaction between model and intervention, not a strict double dissociation.
Seed refits on one dataset do not establish variation across physical populations.
Re-run on the current 20-node network (RESULTS.md §0.13.22): pattern unchanged
and sharper, not a new finding.

M9's saved F1 is **0.9675** on the existing **hybrid** test (20-node network,
was 0.9671 at 10 nodes) and 0.6812 / 0.4636 / 0.2952 on LOW / MEDIUM / HIGH
virtual tests (⚠ was 0.7563 / 0.5436 / 0.3060 at 10 nodes — not directly
comparable, the real-side network size changed). The virtual-only ablation
scores **0.9640** on the existing test (was 0.9769 at 10 nodes) — the two are
now within overlapping confidence intervals and **no longer show hybrid vs.
virtual-only superiority in either direction** (RESULTS.md §0.13.21,
`docs/CLAIM_EVIDENCE_MATRIX.md` C20, withdrawn). These are standalone archived
results, not evidence of improved fused decisions. M9 trains with up to 15 slots;
saved tests use 20 existing-network or 5 virtual slots. There is **no n=15 test**.
A pending slot's placeholder is excluded from pooling/attention as of
RESULTS.md §0.13.19 (previously it entered model context even when masked
from loss — that was the bug §0.13.19 fixed).

LOW virtual-generator checks use the source TRAIN resting residuals; they are
not held-out realism validation. MEDIUM/HIGH are stress presets with documented
marginal failures. Physical replay currently resamples rows, and calibration
halves reuse source observations. A physical-column score still depends on the
whole hybrid model input. These limitations prevent claims of independent physical
validation, manufacturing variation or demonstrated benefit from real-data pooling.

The saved leakage-corrected hardware test detects 30/30 bench disturbances but
flags 5/12 resting windows (41.7%; descriptive Wilson CI 19.3–68.0%). Overlapping
windows are not independent sessions. Earlier leaky 0/49 and 1/29 results remain
historical and withdrawn as validation. Industrial fault validation is pending.

## Setup and local verification

Use the repository root and a Python environment with `requirements.txt` installed:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/benchmark_crossdevice_models.py --selfcheck
python scripts/validate_virtual_device_generator.py
```

The native test runner is `unittest`. See the audit for the baseline and final
counts. The generator validator reports an aggregate failure when MEDIUM/HIGH
marginals diverge; inspect its per-regime output.

Before starting live services, provision local secrets from
`src/secrets_local.example.py`, CA/server certificates, broker credentials and
topic ACLs following [secure communication](docs/07_module6_secure_communication.md).
Secrets and private keys stay outside Git. Gateway startup refuses plaintext
MQTT, unconfigured broker authentication and a placeholder gateway password;
placeholder device HMAC keys cannot authenticate. File autodetection alone does
not verify the broker's running configuration.

```powershell
python src/gateway.py
# A second terminal, with the same environment:
python src/device_simulator.py
```

The dashboard is served by the gateway on port 8600. A static, non-live
implementation/demonstration interface — the same architecture and evidence
without a running gateway — is in [design/](design/README.md); open
[design/Main.dc.html](design/Main.dc.html) or run
`node design/start-demo.mjs`. Real-device provisioning is
covered by the [MPU6050 guide](firmware/HARDWARE_SETUP.md) and
[SW-420 guide](firmware/HARDWARE_SETUP_SW420.md). Firmware peer-certificate
verification remains unresolved: the MPU6050 firmware explicitly uses
`CERT_NONE`. Provision and validate a verifying TLS configuration on the actual
MicroPython build before deployment.

Do not run generators or trainers over the archived evidence just to reproduce
documentation. Most scripts use fixed output paths. First allocate a separate
artifact directory/checkout, preserve hashes and source-session provenance, then
follow the dependency order in [METHODOLOGY](METHODOLOGY.md) and the
[experimental protocol](docs/EXPERIMENTAL_PROTOCOL.md). Source repairs do not
retroactively correct saved model weights or measurements.

## Repository guide

- `src/`: runtime gateway, trust/policy, inference, audit and sensor contracts.
- `scripts/`: capture, split/merge, generation, offline training and evaluation.
- `tests/`: invariants, firmware/host equivalence and audit regressions.
- `firmware/`: MicroPython clients, acquisition helpers and hardware records.
- `data/`, `models/`, `results/`: source/generated evidence, trained artifacts and
  saved measurements; preserve their history and provenance.
- `docs/00_overview.md` through `docs/13_system_architecture_and_workflow.md`:
  module documentation, with current audit qualifications.
- `ZERO_TRUST_CPS_KB.md`, `SESSION_LOG.md`: historical engineering decisions
  and chronological handoff; current architecture is in the paper package.
- `docs/MANUAL_EXTERNAL_REVIEW.md`: the requested independent review prompt.

The older paper title and binary synopsis describe the project's historical
framing. Publication text and exported figures still need review against the
current claim matrix; neither a GNN novelty claim nor deployment readiness follows
from the existence of this implementation.
