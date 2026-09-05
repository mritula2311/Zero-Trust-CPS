# External review artifact packet

Base: `738833846b9bc20ee90f03e7010d93fa4c46aee8`.
Source snapshot: 2026-09-05. Review contract: docs/MANUAL_EXTERNAL_REVIEW.md.
Original result numbers below predate the source repairs. No new training.

## Source diff

Whitespace normalized for display; obtain an applicable patch with `git diff 7388338 -- src scripts`.

```diff
diff --git a/scripts/benchmark_crossdevice_models.py b/scripts/benchmark_crossdevice_models.py
index f9bc75e..e3ffd08 100644
--- a/scripts/benchmark_crossdevice_models.py
+++ b/scripts/benchmark_crossdevice_models.py
@@ -59,8 +59,9 @@ number here was looked at:
                         and the GCN self-loop weight
     TEST split       -> read ONCE, report

-All four models receive the SAME per-node [rule, isolation_forest, lstm_ae]
-sub-scores for all ten nodes at one tick. Nothing else differs.
+Models receive the same per-node [rule, isolation_forest, lstm_ae] sub-scores.
+Architecture, optimisation and class weighting differ; in particular the concat
+MLP loss is unweighted. See docs/ASTRA_AUDIT.md for the comparison's limits.

 OPERATING POINT. Two are reported per model, because "which model" and "where
 to set the alarm" are different questions and answering them with one number
@@ -77,9 +78,10 @@ class weighting, shared verbatim with train_network_gnn so the comparison stays
 like-for-like. Swapping in focal loss would change two models and not the two
 sklearn ones, which is the sort of asymmetry this file exists to avoid.

-PENDING_REAL_HARDWARE_DATA rows (esp32-vib-002, no capture exists) carry no
-features. Excluded from every fit and every metric, counted in the output,
-never imputed.
+PENDING_REAL_HARDWARE_DATA rows (esp32-vib-002, no capture exists) are excluded
+from target loss and metrics, but a neutral 0.9 placeholder remains in model
+context. A masked input benchmark is still required; no physical observation
+exists for that column.

 Writes results/crossdevice_benchmark/.
 """
@@ -94,6 +96,7 @@ sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
 sys.path.insert(0, os.path.dirname(__file__))

 import numpy as np
+from scipy.stats import t as student_t
 import torch
 import torch.nn as nn
 from sklearn.ensemble import HistGradientBoostingClassifier
@@ -777,10 +780,13 @@ def _eval_slice(model, X, y, meta, thr, col_idx=None, scenario=None):
     if col_idx is not None:
         scores, y, valid = scores[:, col_idx], y[:, col_idx], valid[:, col_idx]
     s, lab = scores[valid], y[valid]
-    if len(set((lab == 0).astype(int))) < 2:
-        return {"n": int(len(lab)), "f1": float("nan"), "recall": float("nan"),
-                "false_positive_rate": float("nan")}
-    return {"n": int(len(lab)), **metrics(s, lab, thr)}
+    result = metrics(s, lab, thr)
+    if not np.any(lab == 0):
+        result.update(f1=None, recall=None, detection_rate=None,
+                      undefined_reason="no anomalous observations")
+    if not np.any(lab == 1):
+        result["false_positive_rate"] = None
+    return result


 def m9_ablation_investigation(n_seeds=10):
@@ -821,14 +827,16 @@ def m9_ablation_investigation(n_seeds=10):
             for slice_name, col_idx in slices.items():
                 r = _eval_slice(model, *real_te, thr, col_idx=col_idx)
                 per_seed[name][f"col:{slice_name}"].append(r["f1"])
+                per_seed[name][f"col:{slice_name}:false_positive_rate"].append(r["false_positive_rate"])
             for sc in scenarios:
                 r = _eval_slice(model, *real_te, thr, scenario=sc)
                 if r is not None:
                     per_seed[name][f"scenario:{sc}"].append(r["f1"])
+                    per_seed[name][f"scenario:{sc}:false_positive_rate"].append(r["false_positive_rate"])
         print(f"  seed {seed} done")

     print(f"\n{'=' * 90}")
-    print("M9 ABLATION INVESTIGATION -- per-slice F1, mean +/- 95% CI over seeds")
+    print("M9 ABLATION INVESTIGATION -- per-slice F1 and FPR, mean +/- 95% CI over seeds")
     print(f"{'=' * 90}")
     all_keys = sorted(per_seed["hybrid"])
     print(f"{'slice':28s} {'hybrid (real+virtual)':26s} {'ablation (virtual-only)':26s}")
@@ -836,19 +844,20 @@ def m9_ablation_investigation(n_seeds=10):
     for key in all_keys:
         row = {}
         for name in ("hybrid", "ablation"):
-            vals = [v for v in per_seed[name][key] if not np.isnan(v)]
-            row[name] = mean_ci(vals) if vals else {"mean": float("nan"), "ci95": None}
+            vals = [v for v in per_seed[name][key] if v is not None]
+            row[name] = mean_ci(vals) if vals else {"mean": None, "ci95": None,
+                                                   "undefined_reason": "no observations for this metric"}
             summary[name][key] = row[name]
         h, a = row["hybrid"], row["ablation"]
-        h_str = f"{h['mean']:.4f} +/-{h['ci95']:.4f}" if h.get("ci95") is not None else f"{h['mean']:.4f}"
-        a_str = f"{a['mean']:.4f} +/-{a['ci95']:.4f}" if a.get("ci95") is not None else f"{a['mean']:.4f}"
+        h_str = "n/a" if h["mean"] is None else f"{h['mean']:.4f}" + (f" +/-{h['ci95']:.4f}" if h.get("ci95") is not None else " (CI n/a)")
+        a_str = "n/a" if a["mean"] is None else f"{a['mean']:.4f}" + (f" +/-{a['ci95']:.4f}" if a.get("ci95") is not None else " (CI n/a)")
         print(f"{key:28s} {h_str:26s} {a_str:26s}")

     path = os.path.join(RESULTS_DIR, "m9_ablation_investigation.json")
     os.makedirs(RESULTS_DIR, exist_ok=True)
     with open(path, "w") as f:
         json.dump({"n_seeds": n_seeds, "summary": summary,
-                   "per_seed": {k: dict(v) for k, v in per_seed.items()}}, f, indent=2, default=float)
+                   "per_seed": {k: dict(v) for k, v in per_seed.items()}}, f, indent=2, default=float, allow_nan=False)
     print(f"\nwritten to {path}")
     return summary

@@ -1674,13 +1683,6 @@ def main():
 # --------------------------------------------------------------------------
 # multi-seed validation of the two dilution mechanisms
 # --------------------------------------------------------------------------
-# t multipliers for a two-sided 95% interval at n-1 degrees of freedom. Hardcoded
-# for the handful of seed counts this is run with rather than pulling in scipy
-# for three numbers; falls back to the normal approximation, which is stated in
-# the output so an interval is never silently mislabelled.
-_T95 = {3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 8: 2.365, 10: 2.262}
-
-
 def mean_ci(values):
     """Mean and half-width of a two-sided 95% interval over SEEDS.

@@ -1692,12 +1694,13 @@ def mean_ci(values):
     v = np.asarray(values, dtype=float)
     n = len(v)
     if n < 2:
-        return {"mean": round(float(v.mean()), 4), "ci95": None, "n_seeds": n}
-    t = _T95.get(n, 1.96)
+        return {"mean": round(float(v.mean()), 4) if n else None,
+                "ci95": None, "n_seeds": n}
+    t = float(student_t.ppf(0.975, n - 1))
     half = t * float(v.std(ddof=1)) / np.sqrt(n)
     return {"mean": round(float(v.mean()), 4), "ci95": round(float(half), 4),
             "sd": round(float(v.std(ddof=1)), 4), "n_seeds": n,
-            "multiplier": "t" if n in _T95 else "normal-approx",
+            "multiplier": "t",
             # Raw per-seed values kept, not just the summary. A +-0.36 interval
             # on a bounded [0,1] metric is a warning that the distribution may be
             # bimodal, and a mean +- CI reported over a bimodal outcome describes
@@ -1775,17 +1778,22 @@ def _paired_t(d, **extra):
     significance -- the set models return an identical value at every level of
     both probes, having no neighbourhood to aggregate over."""
     n = len(d)
+    if n < 2:
+        return {"mean": round(float(d.mean()), 4) if n else None,
+                "sd": None, "n_seeds": n, "significant": False,
+                "seeds_negative": int((d < 0).sum()),
+                "note": "fewer than two seeds; interval undefined", **extra}
     mean, sd = float(d.mean()), float(d.std(ddof=1))
     row = {"mean": round(mean, 4), "sd": round(sd, 4), "n_seeds": n,
            "seeds_negative": int((d < 0).sum()), **extra}
     if sd == 0.0:
         row.update({"significant": False, "note": "flat by construction"})
         return row
-    t = _T95.get(n, 1.96)
+    t = float(student_t.ppf(0.975, n - 1))
     half = t * sd / np.sqrt(n)
     row.update({"ci95": [round(mean - half, 4), round(mean + half, 4)],
                 "t": round(mean / (sd / np.sqrt(n)), 3), "t_crit": t,
-                "multiplier": "t" if n in _T95 else "normal-approx",
+                "multiplier": "t",
                 "significant": bool(abs(mean) > half),
                 "per_seed": [round(float(x), 4) for x in d]})
     return row
diff --git a/scripts/generate_training_data.py b/scripts/generate_training_data.py
index e5c10e9..34ede6d 100644
--- a/scripts/generate_training_data.py
+++ b/scripts/generate_training_data.py
@@ -112,6 +112,8 @@ OUTPUT_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")

 def generate(ticks: int = TICKS, seed: int = 42) -> list[dict]:
     random.seed(seed)
+    ds._rest_dc = ds.REST_DC_CENTRE
+    ds._rest_drift_hz = ds.REST_DRIFT_HZ_CENTRE
     records = []
     base_ts = 60_000  # start at 60s of simulated uptime, matches the "past the reboot grace window" realistic case
     for tick in range(ticks):
@@ -119,7 +121,8 @@ def generate(ticks: int = TICKS, seed: int = 42) -> list[dict]:
         high_rate_tick = tick % 18 == 11    # attack-matrix row 5: abnormal rate from an AUTHENTICATED device
         stealthy_tick = tick % 30 == 22     # attack-matrix row 11, see module docstring

-        for device_id, info in DEVICE_REGISTRY.items():
+        for device_id in ds.LEGACY_DEVICE_IDS:
+            info = DEVICE_REGISTRY[device_id]
             anomalous = device_id == "esp32-vib-001" and tick % 12 == 7
             stealthy = device_id == "esp32-vib-001" and stealthy_tick and not anomalous
             coordinated = coordinated_tick and not anomalous and not stealthy
diff --git a/scripts/merge_real_hardware_data.py b/scripts/merge_real_hardware_data.py
index 93edabc..91f15e6 100644
--- a/scripts/merge_real_hardware_data.py
+++ b/scripts/merge_real_hardware_data.py
@@ -129,6 +129,7 @@ def main():
     for r in real:
         merged_real.append({
             "tick": next_tick,
+            "source_tick": r["tick"],
             "device_id": "esp32-vib-001",
             "reading": r["reading"],
             "auth_ok": True,
diff --git a/scripts/train_lstm_ae.py b/scripts/train_lstm_ae.py
index 92cbd5b..5b6d2e2 100644
--- a/scripts/train_lstm_ae.py
+++ b/scripts/train_lstm_ae.py
@@ -45,11 +45,8 @@ def train_one(records, device_id) -> bool:
     normal readings, saving both to that device's per-device paths. Returns
     True if trained, False if too few examples (skipped, not fatal)."""
     torch.manual_seed(TRAINING_SEED)
-    normal = [
-        r for r in records
-        if r["device_id"] == device_id and r["label"] == 1 and r["auth_ok"]
-    ]
-    normal.sort(key=lambda r: r["tick"])
+    runs = datasets.normal_sequences(records, device_id)
+    normal = [r for run in runs for r in run]
     if len(normal) < LSTM_SEQ_LEN + 10:
         print(f"[skip] {device_id}: only {len(normal)} normal examples -- no model trained")
         return False
@@ -58,9 +55,16 @@ def train_one(records, device_id) -> bool:
     mean = raw.mean(axis=0)
     std = raw.std(axis=0)
     std[std < 1e-6] = 1.0
-    normalized = (raw - mean) / std
-
-    windows = np.stack([normalized[i:i + LSTM_SEQ_LEN] for i in range(len(normalized) - LSTM_SEQ_LEN + 1)])
+    windows = []
+    for run in runs:
+        normalized = (np.array([fe.feature_vector(r["reading"]) for r in run],
+                               dtype=np.float32) - mean) / std
+        windows.extend(normalized[i:i + LSTM_SEQ_LEN]
+                       for i in range(len(run) - LSTM_SEQ_LEN + 1))
+    if not windows:
+        print(f"[skip] {device_id}: no contiguous normal training windows")
+        return False
+    windows = np.stack(windows)
     x = torch.tensor(windows, dtype=torch.float32, device=_TORCH_DEVICE)

     # input_dim from THIS device's own feature set, not the module-level
diff --git a/scripts/train_transformer.py b/scripts/train_transformer.py
index 67fac59..098ffa3 100644
--- a/scripts/train_transformer.py
+++ b/scripts/train_transformer.py
@@ -42,6 +42,7 @@ from config import (
     FEATURE_NAMES, TRAINING_SEED,
 )
 import feature_engineering as fe
+import datasets
 from transformer_scorer import TransformerAutoencoder, _TORCH_DEVICE

 SESSION_PATH = os.path.join(DATA_COLLECTED_DIR, "training_session.json")
@@ -53,11 +54,8 @@ def train_one(records, device_id) -> bool:
     saved to that device's per-device paths. Returns True if trained, False
     if too few examples (skipped, not fatal)."""
     torch.manual_seed(TRAINING_SEED)
-    normal = [
-        r for r in records
-        if r["device_id"] == device_id and r["label"] == 1 and r["auth_ok"]
-    ]
-    normal.sort(key=lambda r: r["tick"])
+    runs = datasets.normal_sequences(records, device_id)
+    normal = [r for run in runs for r in run]
     if len(normal) < SEQ_LEN + 10:
         print(f"[skip] {device_id}: only {len(normal)} normal examples -- no model trained")
         return False
@@ -66,9 +64,16 @@ def train_one(records, device_id) -> bool:
     mean = raw.mean(axis=0)
     std = raw.std(axis=0)
     std[std < 1e-6] = 1.0
-    normalized = (raw - mean) / std
-
-    windows = np.stack([normalized[i:i + SEQ_LEN] for i in range(len(normalized) - SEQ_LEN + 1)])
+    windows = []
+    for run in runs:
+        normalized = (np.array([fe.feature_vector(r["reading"]) for r in run],
+                               dtype=np.float32) - mean) / std
+        windows.extend(normalized[i:i + SEQ_LEN]
+                       for i in range(len(run) - SEQ_LEN + 1))
+    if not windows:
+        print(f"[skip] {device_id}: no contiguous normal training windows")
+        return False
+    windows = np.stack(windows)
     clean = torch.tensor(windows, dtype=torch.float32, device=_TORCH_DEVICE)

     model = TransformerAutoencoder().to(_TORCH_DEVICE)
diff --git a/src/config.py b/src/config.py
index 909441c..8852301 100644
--- a/src/config.py
+++ b/src/config.py
@@ -19,7 +19,9 @@ _SRC_DIR = os.path.dirname(os.path.abspath(__file__))
 # --- Secrets (never committed -- see src/secrets_local.example.py) ---
 # Real values live in src/secrets_local.py, gitignored. Falls back to
 # obviously-fake placeholders if that file doesn't exist (fresh clone) so
-# the project still imports and runs for exploration -- auth against a
+# offline research still imports for exploration -- gateway startup refuses
+# unconfigured TLS/broker auth and placeholder device keys cannot authenticate.
+# Authentication against a
 # real broker/device won't work until you copy secrets_local.example.py
 # to secrets_local.py and fill in real values (or generate your own).
 try:
@@ -41,10 +43,9 @@ except ImportError:
     MQTT_GATEWAY_PASSWORD = "CHANGE-ME-generate-your-own-password"

 # --- MQTT broker (Module 6: Secure Communication) ---
-# NOTE: This starter uses plain MQTT on localhost for simplicity so you can see
-# the pipeline working immediately. Before you treat this as "done", follow
-# docs/03_add_tls.md to switch this to MQTT-over-TLS (port 8883) -- that step
-# is what actually satisfies Module 6 / references [23],[24] in the report.
+# Offline configuration may import without certificates. The gateway run()
+# guard requires TLS and broker authentication before starting live services;
+# follow docs/07_module6_secure_communication.md to provision them.
 MQTT_HOST = "localhost"
 MQTT_PORT = 1883
 MQTT_TLS_PORT = 8883
diff --git a/src/datasets.py b/src/datasets.py
index 1b8aca5..e5823f0 100644
--- a/src/datasets.py
+++ b/src/datasets.py
@@ -59,6 +59,33 @@ def network_records(scenario: str, split: str) -> list[dict]:
         return json.load(f)


+def normal_sequences(records: list[dict], device_id: str) -> list[list[dict]]:
+    """Authentic normal runs in acquisition order, never across a discontinuity.
+
+    Sorting concatenated scenarios by tick braids independent sessions; filtering
+    anomalies first joins the normal readings on either side of an event. Split
+    before filtering instead. source_tick preserves gaps hidden by merged ticks.
+    """
+    runs, run = [], []
+    previous_key = previous_tick = None
+    for row in records:
+        if row.get("device_id") != device_id:
+            continue
+        tick = row.get("source_tick", row.get("tick"))
+        key = tuple(row.get(k) for k in ("session_id", "scenario", "phase"))
+        eligible = (row.get("label") == 1 and row.get("auth_ok") is True
+                    and row.get("reading") is not None and type(tick) is int)
+        if run and (not eligible or key != previous_key or tick != previous_tick + 1):
+            runs.append(run)
+            run = []
+        if eligible:
+            run.append(row)
+            previous_key, previous_tick = key, tick
+    if run:
+        runs.append(run)
+    return runs
+
+
 def scenarios() -> list[str]:
     names = set()
     for path in glob.glob(os.path.join(NETWORK_DIR, "network_*_train.json")):
diff --git a/src/device_simulator.py b/src/device_simulator.py
index 9e414da..680bd05 100644
--- a/src/device_simulator.py
+++ b/src/device_simulator.py
@@ -68,6 +68,10 @@ from config import (
 )
 import feature_engineering as fe

+# The original runtime demo/training task. Network research profiles are built
+# separately by generate_network_data.py, with sensor-specific generators.
+LEGACY_DEVICE_IDS = ("esp32-vib-001", "sensor-002", "actuator-001")
+

 def sign(secret: str, payload: dict) -> str:
     canonical = json.dumps(payload, sort_keys=True).encode()
@@ -307,7 +311,8 @@ def run():
     # on boot_id/seq (trust_engine.check_boot_replay() can only track one
     # session per device_id) and produce spurious replay rejections on
     # whichever publisher's messages arrive second.
-    SIMULATED_DEVICES = {d: info for d, info in DEVICE_REGISTRY.items() if d not in REAL_HARDWARE_DEVICE_IDS}
+    SIMULATED_DEVICES = {d: DEVICE_REGISTRY[d] for d in LEGACY_DEVICE_IDS
+                         if d not in REAL_HARDWARE_DEVICE_IDS}
     if REAL_HARDWARE_DEVICE_IDS:
         print(f"[simulator] {sorted(REAL_HARDWARE_DEVICE_IDS)} excluded -- real hardware handles them")

diff --git a/src/gateway.py b/src/gateway.py
index 0ca5648..0f0d13d 100644
--- a/src/gateway.py
+++ b/src/gateway.py
@@ -49,6 +49,7 @@ Run this BEFORE device_simulator.py (or the real ESP32/firmware/main.py).
 import hashlib
 import hmac
 import json
+import math
 import os
 import threading
 import time
@@ -145,6 +146,8 @@ def verify_signature(device_id: str, payload: dict, signature: str) -> bool:
     canonical = json.dumps(payload, sort_keys=True).encode()

     def matches(secret: str) -> bool:
+        if not isinstance(secret, str) or not secret or secret.startswith("CHANGE-ME"):
+            return False
         expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
         return hmac.compare_digest(expected, signature)

@@ -214,6 +217,18 @@ def _process_telemetry(envelope: dict, transport: str, transport_secured: bool)
     except (KeyError, TypeError):
         print(f"[gateway/{transport}] malformed message, dropping")
         return
+    # Validate before HMAC/type-sensitive comparisons or any per-device state.
+    # bool is an int subclass, but is never a timestamp or replay counter.
+    if (not isinstance(payload, dict) or not isinstance(device_id, str)
+            or not isinstance(signature, str) or len(signature) != 64
+            or any(c not in "0123456789abcdef" for c in signature)
+            or type(ts) not in (int, float) or not 0 <= ts < 2**63
+            or type(boot_id) is not int or boot_id < 0
+            or type(seq) is not int or seq < 1
+            or (payload.get("step_up_nonce_echo") is not None
+                and not isinstance(payload["step_up_nonce_echo"], str))):
+        print(f"[gateway/{transport}] malformed message, dropping")
+        return
     step_up_echo = payload.get("step_up_nonce_echo")

     # Module 1: identity known at all? Checked before HMAC (and before
@@ -235,17 +250,25 @@ def _process_telemetry(envelope: dict, transport: str, transport_secured: bool)
         _reject(device_id, "device_revoked", transport)
         return

-    # Optional gateway-level protective response (Module 2 Section 5.1):
-    # once a claimed id has crossed the failure threshold, drop further
-    # attempts against it before even attempting verification.
-    if identity_targeting_risk.is_throttled(device_id):
-        return
-
     # Module 2 Check 3: HMAC, against the current key.
     if not verify_signature(device_id, payload, signature):
+        # A claimed identity is attacker-controlled. Its cooldown may suppress
+        # repeated rejection logging, never a genuinely authenticated device.
+        if identity_targeting_risk.is_throttled(device_id):
+            return
         _reject(device_id, "hmac_mismatch", transport)
         return

+    fields = feature_names_for(device_id) if is_feature_vector(device_id) else ["value"]
+    try:
+        valid_reading = all(type(payload.get(k)) in (int, float)
+                            and math.isfinite(payload[k]) for k in fields)
+    except OverflowError:
+        valid_reading = False
+    if not valid_reading:
+        _reject(device_id, "malformed_reading", transport)
+        return
+
     # Module 2 Check 4: boot-aware anti-replay.
     is_replay, replay_reason = trust_engine.check_boot_replay(device_id, boot_id, seq)
     if is_replay:
@@ -447,7 +470,7 @@ def on_connect(client, userdata, flags, reason_code, properties=None):
 def on_message(client, userdata, msg):
     try:
         envelope = json.loads(msg.payload.decode())
-    except json.JSONDecodeError:
+    except (UnicodeDecodeError, json.JSONDecodeError):
         print("[gateway/mqtt] malformed message, dropping")
         return
     process_telemetry(envelope, transport="mqtt", transport_secured=MQTT_USE_TLS)
@@ -978,6 +1001,11 @@ def start_silence_watchdog() -> threading.Thread:
 def run():
     """Runs MQTT and the HTTPS second-transport (coap_server.py) concurrently."""
     global _mqtt_publish_client, _gateway_boot_id
+    # Offline research can import placeholder configuration; serving cannot.
+    if (not MQTT_USE_TLS or not MQTT_USE_AUTH
+            or not MQTT_GATEWAY_PASSWORD or MQTT_GATEWAY_PASSWORD.startswith("CHANGE-ME")):
+        raise RuntimeError("Gateway requires configured MQTT TLS and broker credentials; "
+                           "see docs/07_module6_secure_communication.md")
     audit_log.init_db()
     _gateway_boot_id = _load_and_increment_gateway_boot_id()
     client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="zt-gateway")
diff --git a/src/isolation_forest_scorer.py b/src/isolation_forest_scorer.py
index f1cc5a1..33698da 100644
--- a/src/isolation_forest_scorer.py
+++ b/src/isolation_forest_scorer.py
@@ -23,6 +23,7 @@ import numpy as np

 from config import (
     isolation_forest_path, isolation_forest_meta_path, FEATURE_VECTOR_DEVICE_IDS, FEATURE_NAMES,
+    feature_names_for,
 )


@@ -114,4 +115,4 @@ class IsolationForestScorer:
         x = np.asarray([feature_vec], dtype=np.float64)
         shap_values = np.array(self._explainers[device_id].shap_values(x))[0]
         idx = int(np.argmax(np.abs(shap_values)))
-        return FEATURE_NAMES[idx], float(shap_values[idx])
+        return feature_names_for(device_id)[idx], float(shap_values[idx])
diff --git a/src/lstm_ae_scorer.py b/src/lstm_ae_scorer.py
index 7da57a3..03f4069 100644
--- a/src/lstm_ae_scorer.py
+++ b/src/lstm_ae_scorer.py
@@ -23,6 +23,7 @@ import os
 import numpy as np
 import torch
 import torch.nn as nn
+from config import feature_names_for

 from config import LSTM_SEQ_LEN, LSTM_HIDDEN_SIZE, LSTM_NUM_LAYERS, lstm_ae_path, lstm_ae_meta_path, FEATURE_VECTOR_DEVICE_IDS, FEATURE_NAMES, TRAINING_SEED

@@ -162,7 +163,7 @@ class LSTMAEScorer:
             base_error = float(((model(x) - x) ** 2).mean())

             best_name, best_drop, best_cf_error = None, -1.0, base_error
-            for c, name in enumerate(FEATURE_NAMES):
+            for c, name in enumerate(feature_names_for(device_id)):
                 perturbed = x.clone()
                 perturbed[:, :, c] = 0.0  # 0.0 in NORMALIZED space == this channel's own training mean
                 perturbed_error = float(((model(perturbed) - perturbed) ** 2).mean())
diff --git a/src/trust_engine.py b/src/trust_engine.py
index 42dba13..11a7cd5 100644
--- a/src/trust_engine.py
+++ b/src/trust_engine.py
@@ -213,10 +213,10 @@ class IdentityTargetingRisk:

     def is_throttled(self, claimed_device_id: str) -> bool:
         """Optional gateway-level protective response (Section 5.1): once a
-        claimed id has crossed the threshold, further attempts against it
-        are dropped before even reaching verification, for a cooldown
-        window -- a defence against the traffic itself, never a judgement
-        applied to a real device's own trust."""
+        claimed id has crossed the threshold, repeated failed-HMAC attempts
+        can be dropped without further rejection logging. Call only after
+        signature verification fails: a claimed identity must never suppress
+        authentic telemetry or change that device's own trust."""
         until = self._cooldown_until.get(claimed_device_id)
         return until is not None and time.time() < until

@@ -312,7 +312,9 @@ class RuleBasedTrustEngine:
         # message mutating device state, violating the "a rejected message never
         # touches the claimed device's state" invariant, and locking out the real
         # board (its now-lower boot_id read as a superseded-session replay).
-        st = self._get_auth_state(device_id)
+        st = self.auth_state.get(device_id)
+        if st is None:
+            return False, "first_message"
         if st.last_seen_boot_id is None:
             return False, "first_message"
         if boot_id > st.last_seen_boot_id:

```

## tests/test_gateway_input_validation.py

```python
"""Ingress regressions: malformed telemetry cannot alter device state.

Run: python -m unittest discover -s tests -p test_gateway_input_validation.py -v
All audit, publication, and model boundaries are isolated from live data.
"""

import copy
import os
import sys
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


class TestGatewayInputValidation(unittest.TestCase):
    def test_gateway_startup_refuses_plaintext_or_unconfigured_auth(self):
        for tls, auth, password in ((False, True, "test-password"),
                                    (True, False, "test-password"),
                                    (True, True, "CHANGE-ME-password")):
            with self.subTest(tls=tls, auth=auth), \
                    patch.object(self.gateway, "MQTT_USE_TLS", tls), \
                    patch.object(self.gateway, "MQTT_USE_AUTH", auth), \
                    patch.object(self.gateway, "MQTT_GATEWAY_PASSWORD", password), \
                    patch.object(self.gateway.audit_log, "init_db") as init_db:
                with self.assertRaises(RuntimeError):
                    self.gateway.run()
                init_db.assert_not_called()

    def test_placeholder_device_key_cannot_authenticate(self):
        import hashlib
        import hmac
        import json
        envelope = self.envelope()
        key = "CHANGE-ME-generate-your-own-secret"
        envelope["signature"] = hmac.new(key.encode(), json.dumps(
            envelope["payload"], sort_keys=True).encode(), hashlib.sha256).hexdigest()
        with patch.dict(self.gateway.DEVICE_REGISTRY["sensor-002"], secret=key):
            self.assertFalse(self.gateway.verify_signature(
                "sensor-002", envelope["payload"], envelope["signature"]))

    def test_first_replay_check_does_not_create_auth_state(self):
        before = copy.deepcopy(vars(self.engine))
        self.assertFalse(self.engine.check_boot_replay("sensor-002", 1, 1)[0])
        self.assertEqual(vars(self.engine), before)

    def setUp(self):
        import gateway

        self.gateway = gateway
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.engine = gateway.RuleBasedTrustEngine()
        self.stack.enter_context(patch.object(gateway, "trust_engine", self.engine))
        self.stack.enter_context(patch.object(
            gateway, "identity_targeting_risk", gateway.IdentityTargetingRisk()))
        # Synthetic keys only: these tests never sign with a deployed key.
        self.stack.enter_context(patch.object(gateway, "DEVICE_REGISTRY", {
            "sensor-002": {"secret": "test-only-key"},
            "esp32-vib-001": {"secret": "test-only-key"},
        }))
        self.stack.enter_context(patch.object(gateway, "is_revoked", return_value=False))
        for name in ("_reject", "_publish_decision", "_publish_challenge", "_apply_auto_quarantine"):
            self.stack.enter_context(patch.object(gateway, name))
        self.stack.enter_context(patch.object(gateway.audit_log, "log_decision"))
        self.stack.enter_context(patch("builtins.print"))
        self.stack.enter_context(patch.object(gateway, "USE_RL_POLICY", False))
        self.scorers = []
        for name in ("if_scorer", "lstm_scorer", "gnn_scorer"):
            scorer = Mock()
            scorer.score.return_value = 0.9
            self.scorers.append(scorer)
            self.stack.enter_context(patch.object(gateway, name, scorer))
        self.fusion = Mock(last_shap=None)
        self.fusion.combine.return_value = (0.9, 0.9, "test score")
        self.fusion.is_trained.return_value = False
        self.stack.enter_context(patch.object(gateway, "fusion_engine", self.fusion))

    def envelope(self, device_id="sensor-002"):
        payload = {"device_id": device_id, "ts": int(time.time() * 1000),
                   "boot_id": 2, "seq": 2}
        if self.gateway.is_feature_vector(device_id):
            payload.update({name: 1.0 for name in self.gateway.feature_names_for(device_id)})
        else:
            payload["value"] = 25.0
        return {"payload": payload, "signature": "0" * 64}

    def assert_dropped_without_state_change(self, envelope, authenticated=True, seeded=False):
        engine = self.gateway.RuleBasedTrustEngine()
        if seeded:
            engine.commit_boot_seq("sensor-002", 1, 1)
            engine.score_security_trust("sensor-002", False, None)
            engine.update_process_anomaly("sensor-002", 0.85)
            engine.commit_boot_seq("esp32-vib-001", 1, 1)
            engine.score_security_trust("esp32-vib-001", False, None)
            engine.update_process_anomaly("esp32-vib-001", 0.85)
        before = copy.deepcopy(vars(engine))
        for scorer in self.scorers:
            scorer.reset_mock()
        self.fusion.reset_mock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.gateway, "trust_engine", engine))
            if authenticated:
                # Model a correctly authenticated message with an invalid schema.
                stack.enter_context(patch.object(self.gateway, "verify_signature", return_value=True))
            self.gateway.process_telemetry(envelope, "mqtt", True)
        self.assertEqual(vars(engine), before, "malformed telemetry mutated claimed device state")
        for scorer in self.scorers:
            scorer.score.assert_not_called()
        self.fusion.combine.assert_not_called()

    def test_non_object_envelopes_and_payloads_are_dropped(self):
        for value in (None, [], "text", 42, True):
            with self.subTest(envelope=value):
                self.assert_dropped_without_state_change(value)
            with self.subTest(payload=value):
                self.assert_dropped_without_state_change({"payload": value, "signature": "0" * 64})

    def test_nonstring_device_ids_are_dropped(self):
        for value in ([], {}, None, 42, True):
            with self.subTest(device_id=value):
                envelope = self.envelope()
                envelope["payload"]["device_id"] = value
                self.assert_dropped_without_state_change(envelope)

    def test_malformed_signatures_are_dropped_without_hmac_type_errors(self):
        for value in (None, [], {}, 42, True, "\u00e9" * 64):
            with self.subTest(signature=value):
                envelope = self.envelope()
                envelope["signature"] = value
                self.assert_dropped_without_state_change(envelope, authenticated=False)

    def test_invalid_timestamps_cannot_create_or_modify_state(self):
        for seeded in (False, True):
            for value in (True, False, "123", None, [], {}, float("nan"), float("inf"), -float("inf")):
                with self.subTest(timestamp=value, seeded=seeded):
                    envelope = self.envelope()
                    envelope["payload"]["ts"] = value
                    self.assert_dropped_without_state_change(envelope, seeded=seeded)

    def test_invalid_boot_and_sequence_cannot_poison_replay_state(self):
        for seeded in (False, True):
            for field in ("boot_id", "seq"):
                for value in (True, False, "2", None, [], {}, 2.5, float("nan"), float("inf")):
                    with self.subTest(field=field, value=value, seeded=seeded):
                        envelope = self.envelope()
                        envelope["payload"][field] = value
                        self.assert_dropped_without_state_change(envelope, seeded=seeded)

    def test_missing_readings_are_dropped_before_state_or_models_change(self):
        for device_id in ("sensor-002", "esp32-vib-001"):
            envelope = self.envelope(device_id)
            fields = (self.gateway.feature_names_for(device_id)
                      if self.gateway.is_feature_vector(device_id) else ["value"])
            for field in fields:
                with self.subTest(device_id=device_id, missing=field):
                    missing = copy.deepcopy(envelope)
                    del missing["payload"][field]
                    self.assert_dropped_without_state_change(missing, seeded=True)

    def test_invalid_readings_are_dropped_before_state_or_models_change(self):
        for device_id in ("sensor-002", "esp32-vib-001"):
            fields = (self.gateway.feature_names_for(device_id)
                      if self.gateway.is_feature_vector(device_id) else ["value"])
            for field in fields:
                for value in (None, True, "1.0", [], {}, float("nan"), float("inf"), -float("inf")):
                    with self.subTest(device_id=device_id, field=field, value=value):
                        envelope = self.envelope(device_id)
                        envelope["payload"][field] = value
                        self.assert_dropped_without_state_change(envelope, seeded=True)

    def test_valid_numeric_readings_reach_scoring(self):
        for device_id in ("sensor-002", "esp32-vib-001"):
            with self.subTest(device_id=device_id):
                with patch.object(self.gateway, "verify_signature", return_value=True):
                    self.gateway.process_telemetry(self.envelope(device_id), "mqtt", True)
                self.assertEqual(self.engine.auth_state[device_id].last_seen_seq, 2)
                self.assertIn(device_id, self.engine.security_state)
                self.assertIn(device_id, self.engine.process_state)
                self.assertEqual(self.engine.process_state[device_id].score, 0.9)
        self.assertEqual(self.fusion.combine.call_count, 2)

    def test_forged_claim_cooldown_cannot_block_authentic_telemetry(self):
        import trust_engine

        risk = self.gateway.identity_targeting_risk
        with patch.object(trust_engine, "IDENTITY_TARGETING_RISK_THRESHOLD_60S", 1):
            with patch.object(trust_engine, "IDENTITY_TARGETING_COOLDOWN_SECONDS", 60):
                risk.record("sensor-002", "hmac_mismatch")
        self.assertTrue(risk.is_throttled("sensor-002"))

        with patch.object(self.gateway, "verify_signature", return_value=True):
            self.gateway.process_telemetry(self.envelope(), "mqtt", True)

        self.assertIn("sensor-002", self.engine.auth_state,
                      "forged identity claims blocked an authentic device")
        self.assertEqual(self.engine.auth_state["sensor-002"].last_seen_seq, 2)
        self.assertIn("sensor-002", self.engine.security_state)
        self.assertEqual(self.engine.process_state["sensor-002"].score, 0.9)
        self.fusion.combine.assert_called_once()

    def test_invalid_ascii_signature_cannot_reach_scoring_even_during_cooldown(self):
        import trust_engine

        for throttled in (False, True):
            with self.subTest(throttled=throttled):
                if throttled:
                    with patch.object(trust_engine, "IDENTITY_TARGETING_RISK_THRESHOLD_60S", 1):
                        with patch.object(trust_engine, "IDENTITY_TARGETING_COOLDOWN_SECONDS", 60):
                            self.gateway.identity_targeting_risk.record("sensor-002", "hmac_mismatch")
                    self.assertTrue(self.gateway.identity_targeting_risk.is_throttled("sensor-002"))
                self.assert_dropped_without_state_change(self.envelope(), authenticated=False)

    def test_invalid_utf8_does_not_escape_mqtt_callback(self):
        with patch.object(self.gateway, "process_telemetry") as process:
            self.gateway.on_message(None, None, SimpleNamespace(payload=b"\xff"))
        process.assert_not_called()

    def test_malformed_json_does_not_reach_processing(self):
        with patch.object(self.gateway, "process_telemetry") as process:
            self.gateway.on_message(None, None, SimpleNamespace(payload=b"{"))
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()

```

## tests/test_training_sequences.py

```python
"""Regression tests for contiguous normal time-series training records.

Run from the repository root:
    python -m unittest discover -s tests -p test_training_sequences.py -v

Fixtures are in memory; no captured data or model artifacts are accessed.
"""

import copy
import os
import sys
import unittest
from unittest.mock import patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import datasets


DEVICE = "esp32-vib-003"


def record(tick, **overrides):
    row = {
        "device_id": DEVICE,
        "tick": tick,
        "label": 1,
        "auth_ok": True,
        "reading": {
            "rms": 1.0,
            "peak": 2.0,
            "crest_factor": 2.0,
            "kurtosis": 3.0,
            "dominant_freq": 10.0,
        },
    }
    row.update(overrides)
    return row


class TestNormalTrainingSequences(unittest.TestCase):
    def test_source_tick_retains_gaps_hidden_by_merge_renumbering(self):
        rows = [record(0, source_tick=10), record(1, source_tick=11),
                record(2, source_tick=25), record(3, source_tick=26)]
        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [rows[:2], rows[2:]])

    def test_both_trainers_pass_only_within_run_windows_to_model(self):
        import torch
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import train_lstm_ae
        import train_transformer

        class CaptureAE(torch.nn.Module):
            def __init__(self, **kwargs):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.tensor(1.0))

            def forward(self, x):
                self.windows = x.detach().cpu().numpy()
                return x * self.weight

        rows = [record(t, device_id="esp32-vib-001", session_id=s)
                for s in ("one", "two") for t in range(10)]
        for module, factory, epochs in (
                (train_lstm_ae, "LSTMAutoencoder", "LSTM_EPOCHS"),
                (train_transformer, "TransformerAutoencoder", "TRANSFORMER_EPOCHS")):
            with self.subTest(trainer=module.__name__):
                model = CaptureAE()
                with patch.object(module, factory, return_value=model), \
                        patch.object(module, epochs, 0), \
                        patch.object(module.torch, "save"), \
                        patch.object(module.os, "makedirs"), \
                        patch("builtins.open", mock_open()), patch("builtins.print"):
                    self.assertTrue(module.train_one(rows, "esp32-vib-001"))
                self.assertEqual(model.windows.shape, (6, 8, 5))

    def test_scenario_blocks_with_restarting_ticks_never_braid(self):
        # The corpus loader concatenates independent files. Their scenario
        # order says nothing about time, and their tick counters all restart.
        expected = [
            [record(t, session_id=f"NET_{name}", scenario=name) for t in range(5)]
            for name in ("propagation", "all_normal", "localized")
        ]
        rows = [row for run in expected for row in run]

        actual = datasets.normal_sequences(rows, DEVICE)

        self.assertEqual(actual, expected)

    def test_each_metadata_change_is_a_boundary_even_with_consecutive_ticks(self):
        for field in ("session_id", "scenario", "phase"):
            with self.subTest(field=field):
                before = [record(t, **{field: "first"}) for t in (0, 1)]
                after = [record(t, **{field: "second"}) for t in (2, 3)]

                self.assertEqual(
                    datasets.normal_sequences(before + after, DEVICE),
                    [before, after],
                )

    def test_returning_to_previous_metadata_does_not_rejoin_an_old_run(self):
        rows = [record(0, phase="rest"), record(1, phase="event"), record(2, phase="rest")]

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [[row] for row in rows])

    def test_anomalous_or_invalid_target_record_interrupts_normal_readings(self):
        invalid_rows = [
            record(1, label=0),
            record(1, auth_ok=False),
            record(1, reading=None),
            record(None),
            record("invalid"),
        ]
        for missing in ("label", "auth_ok", "reading", "tick"):
            incomplete = record(1)
            del incomplete[missing]
            invalid_rows.append(incomplete)

        for invalid in invalid_rows:
            with self.subTest(invalid=invalid):
                before = record(0)
                # Deliberately consecutive to the last VALID row: filtering
                # before segmentation would hide the intervening invalid row.
                after = record(1)
                self.assertEqual(
                    datasets.normal_sequences([before, invalid, after], DEVICE),
                    [[before], [after]],
                )

    def test_tick_gap_splits_legacy_records_without_metadata(self):
        before = [record(t) for t in (10, 11, 12)]
        after = [record(t) for t in (14, 15, 16)]

        self.assertEqual(datasets.normal_sequences(before + after, DEVICE), [before, after])

    def test_duplicate_tick_starts_a_new_run(self):
        before = [record(0), record(1)]
        after = [record(1), record(2)]

        self.assertEqual(datasets.normal_sequences(before + after, DEVICE), [before, after])

    def test_reversed_ticks_are_not_sorted_into_false_continuity(self):
        before = [record(3), record(4)]
        after = [record(1), record(2)]

        self.assertEqual(datasets.normal_sequences(before + after, DEVICE), [before, after])

    def test_other_device_interleaving_does_not_break_a_valid_run(self):
        expected = [record(t) for t in range(4)]
        rows = []
        for row in expected:
            rows.extend([
                row,
                record(row["tick"], device_id="another-device", label=0, reading=None),
            ])

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [expected])

    def test_legacy_contiguous_run_and_singleton_remain_available(self):
        rows = [record(t) for t in range(30)]

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [rows])
        self.assertEqual(datasets.normal_sequences(rows[:1], DEVICE), [rows[:1]])

    def test_absent_metadata_and_explicit_none_share_legacy_run(self):
        rows = [record(0), record(1, session_id=None, scenario=None, phase=None), record(2)]

        self.assertEqual(datasets.normal_sequences(rows, DEVICE), [rows])

    def test_empty_or_no_eligible_device_returns_no_runs(self):
        for rows in ([], [record(0, device_id="another-device")], [record(0, label=0)]):
            with self.subTest(rows=rows):
                self.assertEqual(datasets.normal_sequences(rows, DEVICE), [])

    def test_segmentation_does_not_change_input_records_or_order(self):
        rows = [record(4, scenario="z"), record(1, scenario="a"), record(2, scenario="a")]
        original = copy.deepcopy(rows)

        datasets.normal_sequences(rows, DEVICE)

        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()

```

## tests/test_research_reporting.py

```python
"""Absent anomaly classes must not erase the normal-control false positives."""
import json
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import benchmark_crossdevice_models as benchmark


class TestSliceMetrics(unittest.TestCase):
    def evaluate(self, labels):
        x = np.zeros((1, 2, 3))
        meta = [{"scenario": "NETWORK_NORMAL", "valid": np.array([True, True])}]
        with patch.object(benchmark, "deep_sets_scores", return_value=np.array([[0.2, 0.9]])):
            return benchmark._eval_slice(None, x, np.array([labels]), meta, 0.6)

    def test_normal_control_keeps_fpr_with_undefined_detection(self):
        result = self.evaluate([1, 1])
        self.assertEqual(result["false_positive_rate"], 0.5)
        self.assertIsNone(result["f1"])
        self.assertIsNone(result["recall"])
        self.assertEqual((result["fp"], result["tn"]), (1, 1))
        json.dumps(result, allow_nan=False)

    def test_anomaly_only_slice_keeps_detection_with_undefined_fpr(self):
        result = self.evaluate([0, 0])
        self.assertEqual(result["recall"], 0.5)
        self.assertIsNone(result["false_positive_rate"])

    def test_mixed_slice_preserves_existing_metrics(self):
        result = self.evaluate([0, 1])
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["false_positive_rate"], 0.0)


class TestSeedIntervals(unittest.TestCase):
    def test_two_seed_interval_uses_student_t_not_normal_approximation(self):
        result = benchmark.mean_ci([0.0, 2.0])
        self.assertAlmostEqual(result["ci95"], 12.7062, places=4)
        self.assertEqual(result["multiplier"], "t")
        paired = benchmark._paired_t(np.array([0.0, 2.0]))
        self.assertEqual(paired["ci95"], [-11.7062, 13.7062])
        self.assertFalse(paired["significant"])

    def test_insufficient_seeds_produce_strict_json_and_no_significance(self):
        for values in ([], [1.0]):
            with self.subTest(values=values):
                result = benchmark.mean_ci(values)
                self.assertIsNone(result["ci95"])
                json.dumps(result, allow_nan=False)
                paired = benchmark._paired_t(np.array(values))
                self.assertFalse(paired["significant"])
                json.dumps(paired, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

```

## tests/test_sensor_explanations.py

```python
"""Explanations must name the features the scored sensor actually supplies."""
import os
import sys
import unittest
from types import SimpleNamespace

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from isolation_forest_scorer import IsolationForestScorer
from lstm_ae_scorer import LSTMAEScorer


class TestSwitchExplanations(unittest.TestCase):
    def test_if_names_switch_feature(self):
        scorer = IsolationForestScorer.__new__(IsolationForestScorer)
        scorer.models = {"esp32-vib-002": object()}
        scorer._explainers = {"esp32-vib-002": SimpleNamespace(
            shap_values=lambda x: np.array([[0.1, 0.2, 0.8, 0.3]]))}
        name, _ = scorer.level2_explain("esp32-vib-002", [1, 0.2, 10, 0.4])
        self.assertEqual(name, "burst_max_ms")

    def test_lstm_perturbs_only_switch_channels(self):
        scorer = LSTMAEScorer.__new__(LSTMAEScorer)
        scorer.models = {"esp32-vib-002": lambda x: torch.zeros_like(x)}
        scorer._history = {"esp32-vib-002": [[1, 2, 5, 3]] * 8}
        scorer.stats = {"esp32-vib-002": dict(mean=np.zeros(4), std=np.ones(4),
                                             baseline_error_mean=0, baseline_error_std=1)}
        name, _, _ = scorer.level2_explain("esp32-vib-002")
        self.assertEqual(name, "burst_max_ms")


if __name__ == "__main__":
    unittest.main()

```

## tests/test_legacy_generation.py

```python
"""The original three-device experiment must not change as registry grows."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from generate_training_data import generate


class TestLegacyGeneration(unittest.TestCase):
    def test_registry_expansion_does_not_inject_research_or_pending_nodes(self):
        rows = generate(ticks=2, seed=42)
        self.assertEqual({r["device_id"] for r in rows},
                         {"esp32-vib-001", "sensor-002", "actuator-001"})
        self.assertEqual(len(rows), 6)

    def test_repeated_seed_resets_persistent_simulator_walk(self):
        first = generate(ticks=10, seed=42)
        generate(ticks=7, seed=999)
        self.assertEqual(generate(ticks=10, seed=42), first)


if __name__ == "__main__":
    unittest.main()

```

## scripts/generate_network_data.py:167 — _load_real_pool

```python
def _load_real_pool(split: str):
    """Real rows for the two physical nodes, keyed by (device_id, anomalous).

    Drawn only from sessions allocated to `split`. A real node with no capture
    in this split yields an empty pool and its rows are emitted as
    PENDING_REAL_HARDWARE_DATA."""
    pool = {(d, False): [] for d in REAL_NODES}
    pool.update({(d, True): [] for d in REAL_NODES})
    for path in splits.labelled_session_paths(split):
        with open(path) as f:
            session = json.load(f)
        sid = splits.session_id_of(path)
        for r in session:
            did = r.get("device_id")
            if did not in REAL_NODES:
                continue
            phase = r.get("phase") or ""
            if phase == "(pending mark)":
                continue
            anomalous = phase not in ("at_rest", "C1_both_normal")
            r["_session_id"] = sid
            pool[(did, anomalous)].append(r)
    return pool
```

## scripts/generate_network_data.py:227 — build

```python
def build(scenario: str, split: str):
    anomalous_nodes = SCENARIOS[scenario]
    real_pool = _load_real_pool(split)
    rngs = {d: random.Random(_seed_for(scenario, split, d)) for d in NETWORK_NODES}
    n_ticks = TICKS[split]
    records, pending = [], {d: 0 for d in REAL_NODES}

    # Every simulated node's full series first, then assemble by tick.
    sim_series = {d: _simulated_series(d, SIMULATED_NODE_PROFILES[d], scenario, split,
                                       anomalous_nodes, n_ticks)
                  for d in NETWORK_NODES if d in SIMULATED_NODE_PROFILES}

    for tick in range(n_ticks):
        in_event = _in_event(tick, anomalous_nodes)
        event_id = f"{scenario}_{split}_evt{tick // (2 * BLOCK_TICKS):03d}" if in_event else None

        for device_id in NETWORK_NODES:
            is_anom = in_event and device_id in anomalous_nodes
            rng = rngs[device_id]
            base = {
                "tick": tick,
                "device_id": device_id,
                "session_id": f"NET_{scenario}_{split.upper()}_001",
                "network_experiment_id": GRAPH_TOPOLOGY["network_experiment_id"],
                "scenario": scenario,
                "split": split,
                "event_id": event_id,
                "condition": "PHYSICAL_ANOMALY" if is_anom else "NORMAL",
                "label": 0 if is_anom else 1,
                "auth_ok": True,
                "event_type": "coordinated" if is_anom else "normal",
                "simulated_flood": False,
            }

            if device_id in REAL_NODES:
                candidates = real_pool[(device_id, is_anom)]
                if not candidates:
                    pending[device_id] += 1
                    records.append({**base,
                                    "source_type": "PENDING_REAL_HARDWARE_DATA",
                                    "sensor_type": DEVICE_REGISTRY[device_id].get("sensor_type"),
                                    "reading": None})
                    continue
                src = candidates[rng.randrange(len(candidates))]
                records.append({**base,
                                "source_type": "REAL",
                                "sensor_type": DEVICE_REGISTRY[device_id].get("sensor_type", "MPU6050"),
                                "real_session_id": src.get("_session_id"),
                                "real_phase": src.get("phase"),
                                "label_source": src.get("label_source"),
                                "reading": src["reading"]})
            else:
                profile = SIMULATED_NODE_PROFILES[device_id]
                reading = sim_series[device_id][tick]
                records.append({**base,
                                "source_type": "SIMULATED",
                                "sensor_type": DEVICE_REGISTRY[device_id]["sensor_type"],
                                "simulation_profile": profile["variation"],
                                "seed": profile["seed"],
                                "reading": reading})
    return records, pending
```

## scripts/generate_virtual_network_data.py:83 — build

```python
def build(scenario: str, split: str, preset_name: str = PRESET_NAME) -> list[dict]:
    anomalous_nodes = VIRTUAL_SCENARIOS[scenario]
    n_ticks = TICKS[split]
    preset = vgen.load_config()["heterogeneity_presets"][preset_name]
    pool = vgen.load_real_pool(split)
    stats = vgen.empirical_stats(pool)

    windows = [(t, min(t + BLOCK_TICKS, n_ticks))
               for t in range(0, n_ticks, BLOCK_TICKS) if (t // BLOCK_TICKS) % 2 == 1]

    series, masks = {}, {}
    for node_id in VIRTUAL_NODES:
        # Pure normal series first -- device identity (scale/bias/drift), base
        # trajectory and noise only, no anomaly. Ungated by node_id: a
        # non-anomalous node's series is exactly this.
        readings, _mask, _prov = vgen.generate_series(
            node_id, n_ticks, pool, stats, preset, scenario, split,
            global_seed=_seed_for(scenario, split, node_id), anomaly=None)
        mask = np.zeros(n_ticks, dtype=bool)

        if node_id in anomalous_nodes:
            # A FRESH fault_displacement() draw PER WINDOW, not one shared
            # delta per (scenario, split) -- a split-safe library of many real
            # fault trajectories (each fault_displacement() call independently
            # samples a random real disturbance run from `pool["fault"]`,
            # which load_real_pool(split) already restricts to this split's
            # own sessions, so this cannot leak across splits) rather than one
            # template stamped at every event. This was measured to matter:
            # sharing one delta across all of a split's event blocks produced
            # near-zero anomalous-score variance within a coordinated
            # scenario (std=0.0054 across 300 rows) -- an easily-learned
            # repeated signature, not a realistic anomaly distribution
            # (scripts/benchmark_crossdevice_models.py's m9_sanity_check
            # demonstrated this directly before this fix).
            node_rng = np.random.default_rng(_seed_for(scenario, split, node_id))
            lo, hi = preset["anomaly_severity_range"]
            lag = int(node_rng.integers(0, preset["coordinated_lag_ticks_max"] + 1))
            x = np.array([[r[k] for k in vgen.FREE_FEATURES] for r in readings])
            for t0, t1 in windows:
                a0, a1 = min(t0 + lag, n_ticks), min(t1 + lag, n_ticks)
                if a0 >= a1:
                    continue
                w_rng = np.random.default_rng(_seed_for(scenario, split, f"{node_id}_{t0}"))
                alpha = float(w_rng.uniform(lo, hi))
                _sid, _phase, delta = vgen.fault_displacement(pool, stats, a1 - a0, w_rng)
                x[a0:a1] += alpha * delta
                mask[a0:a1] = True
            readings = [vgen._finalise(row) for row in x]

        series[node_id], masks[node_id] = readings, mask

    records = []
    for tick in range(n_ticks):
        in_event = _in_event(tick, anomalous_nodes)
        event_id = f"{scenario}_{split}_evt{tick // (2 * BLOCK_TICKS):03d}" if in_event else None
        for node_id in VIRTUAL_NODES:
            is_anom = bool(masks[node_id][tick])
            records.append({
                "tick": tick,
                "device_id": node_id,
                "session_id": f"VNET_{scenario}_{split.upper()}_001",
                "scenario": scenario,
                "split": split,
                "event_id": event_id,
                "condition": "PHYSICAL_ANOMALY" if is_anom else "NORMAL",
                "label": 0 if is_anom else 1,
                "event_type": "coordinated" if is_anom else "normal",
                "source_type": vgen.SOURCE_TYPE,
                "heterogeneity_preset": preset_name,
                "reading": series[node_id][tick],
            })
    return records
```

## scripts/validate_virtual_device_generator.py:160 — discriminator

```python
def discriminator(real_resid, gen_resid, rng):
    """Balanced 1:1 real-vs-generated, so chance is exactly 0.5 -- there are
    6x more generated rows than the 103 real rows total, and unbalanced
    classes make "always predict the majority class" look like a finding
    (618/(618+103) = 0.857, which is exactly what an earlier, unbalanced
    version of this check reported for all three presets identically)."""
    n = min(len(real_resid), len(gen_resid))
    real_sub = real_resid[rng.choice(len(real_resid), n, replace=False)]
    gen_sub = gen_resid[rng.choice(len(gen_resid), n, replace=False)]
    X = np.vstack([real_sub, gen_sub])
    y = np.concatenate([np.zeros(n), np.ones(n)])
    acc = float(cross_val_score(LogisticRegression(max_iter=1000), X, y, cv=5).mean())
    flag = "OK (near-chance)" if acc < 0.65 else "FAILS (detectable footprint)"
    print(f"  [4] real-vs-generated residual discriminator (balanced, n={n} each): "
          f"accuracy={acc:.3f}  {flag}")
    return acc < 0.65
```

## scripts/validate_virtual_device_generator.py:178 — main

```python
def main():
    pool = vgen.load_real_pool(SPLIT)
    stats = vgen.empirical_stats(pool)
    real_blocks = _real_residual_blocks(pool)
    real_lengths = [len(a) for a in real_blocks]
    real_resid, _real_lag1 = _residual_array_and_lag1(real_blocks)
    config = vgen.load_config()

    print(f"Real resting rows: {sum(len(a) for a in real_blocks)} "
          f"({len(real_blocks)} runs, lengths {real_lengths}), split={SPLIT!r}\n")

    rng = np.random.default_rng(42)
    all_ok = True
    preset_medians = {}
    for i, preset_name in enumerate(PRESETS):
        preset = config["heterogeneity_presets"][preset_name]
        gen_blocks, clipped = _generated_residual_blocks(
            pool, stats, preset, seed0=1000 + i * 100, real_lengths=real_lengths)
        gen_resid, gen_lag1 = _residual_array_and_lag1(gen_blocks)
        preset_medians[preset_name] = _node_rms_medians(pool, stats, preset, seed0=2000 + i)

        n_rows = sum(len(a) for a in gen_blocks)
        print(f"--- {preset_name} preset ({n_rows} generated rows over {len(gen_blocks)} blocks) ---")
        print("  [1] marginals (detrended residuals):")
        all_ok = marginals(real_resid, gen_resid) and all_ok
        all_ok = covariance(stats, gen_resid) and all_ok
        all_ok = temporal(stats, gen_lag1) and all_ok
        all_ok = discriminator(real_resid, gen_resid, rng) and all_ok
        print(f"  [clip] rms clip engaged on {clipped.mean():.1%} of generated rows")
        print()

    print("--- [5] heterogeneity ordering (cross-node rms spread) ---")
    spreads = {p: float(np.std(preset_medians[p], ddof=1)) for p in PRESETS}
    for p in PRESETS:
        print(f"        {p:6s} spread={spreads[p]:.5f}")
    ordered = spreads["LOW"] < spreads["MEDIUM"] < spreads["HIGH"]
    print(f"        LOW < MEDIUM < HIGH: {'OK' if ordered else 'FAILS'}")
    all_ok = ordered and all_ok

    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    sys.exit(0 if all_ok else 1)
```

## scripts/evaluate_gnn_baselines.py:94 — build_snapshots

```python
def build_snapshots(split: str):
    """(X, y, meta) where X is (n_ticks, 10, 3) of per-node sub-scores.

    The LSTM-AE is stateful, so each (scenario, node) stream is replayed IN
    TICK ORDER with its own scorer instance -- interleaving scenarios through
    one scorer would build windows that never existed, the same error
    evaluate_real_hardware.py's per-block reset exists to prevent."""
    X, y, meta = [], [], []
    excluded_pending = 0

    for scenario in datasets.scenarios():
        rows = datasets.network_records(scenario, split)
        by_tick = collections.defaultdict(dict)
        for r in rows:
            by_tick[r["tick"]][r["device_id"]] = r

        if_s, lstm_s = IsolationForestScorer(), LSTMAEScorer()   # fresh state per scenario
        for tick in sorted(by_tick):
            node_rows = by_tick[tick]
            feats = np.full((N_NODES, GNN_NODE_FEATURE_DIM), 0.9, dtype=np.float32)
            labels = np.ones(N_NODES, dtype=np.int64)
            valid = np.ones(N_NODES, dtype=bool)

            for device_id, r in node_rows.items():
                i = _NODE_INDEX[device_id]
                labels[i] = r["label"]
                if r.get("reading") is None:          # PENDING_REAL_HARDWARE_DATA
                    valid[i] = False
                    excluded_pending += 1
                    continue
                rule, _ = rule_range_score(device_id, r["reading"])
                if is_feature_vector(device_id):
                    fv = fe.feature_vector(r["reading"])
                    iso = if_s.score(device_id, fv)
                    lstm = lstm_s.score(device_id, fv)
                else:
                    iso = lstm = rule
                feats[i] = [rule, iso, lstm]

            X.append(feats)
            y.append(labels)
            meta.append({"scenario": scenario, "tick": tick, "valid": valid,
                         "event_id": next((r.get("event_id") for r in node_rows.values()), None)})
    return np.array(X), np.array(y), meta, excluded_pending
```

## scripts/benchmark_crossdevice_models.py:339 — train_mixed_cardinality

```python
def train_mixed_cardinality(X, y, meta, factory=SetTransformer,
                            sizes=(2, 3, 5, 10)):
    """Train one set model across MIXED device counts instead of only at n=10.

    Every other model in this file is fitted at n=10 and evaluated elsewhere by
    extrapolation, which is the largest stated limitation of the dilution
    results. Here each epoch draws a cardinality and a random subset of node
    slots, so the same weights see 2-, 3-, 5- and 10-device networks during
    training. Only set models can be trained this way at all; the graph models
    need an adjacency per size and the concat models have a fixed input width.

    THE SUBSETS ARE REAL. A size-k network is k of the ten real scored nodes at
    a real tick, never a synthesised or duplicated device, so nothing here is
    generated data. The ceiling is therefore n=10: this project has ten node
    streams and going above that needs the virtual-device generator, not a
    resampling trick that would quietly reuse one device as several.

    Same optimiser, learning rate, epoch count and class weighting as
    train_deep_sets -- only the cardinality schedule differs."""
    torch.manual_seed(TRAINING_SEED)
    rng = np.random.default_rng(TRAINING_SEED)
    model = factory().to(_TORCH_DEVICE)
    x_all = torch.tensor(X, dtype=torch.float32, device=_TORCH_DEVICE)
    t_all = torch.tensor(y, dtype=torch.float32, device=_TORCH_DEVICE)
    m_all = torch.tensor(np.array([m["valid"] for m in meta]), dtype=torch.bool,
                         device=_TORCH_DEVICE)

    n_pos = float(t_all[m_all].sum().item())
    n_neg = float(m_all.sum().item() - n_pos)
    w_pos = (n_pos + n_neg) / (2 * max(n_pos, 1.0))
    w_neg = (n_pos + n_neg) / (2 * max(n_neg, 1.0))

    opt = torch.optim.Adam(model.parameters(), lr=DEEPSETS_LR)
    model.train()
    t0 = time.perf_counter_ns()
    for ep in range(DEEPSETS_EPOCHS):
        k = sizes[ep % len(sizes)]
        cols = torch.tensor(np.sort(rng.choice(N_NODES, size=k, replace=False)),
                            device=_TORCH_DEVICE)
        x, t, mask = x_all[:, cols], t_all[:, cols], m_all[:, cols]
        opt.zero_grad()
        out = model(x)
        w = torch.where(t > 0.5, w_pos, w_neg)
        loss = (nn.functional.binary_cross_entropy(out, t, reduction="none") * w)[mask].mean()
        loss.backward()
        opt.step()
    elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
    model.eval()
    return model, elapsed_ms, DEEPSETS_EPOCHS
```

## scripts/benchmark_crossdevice_models.py:507 — train_mixed_provenance

```python
def train_mixed_provenance(real, virtual, factory=SetTransformer,
                           sizes=(2, 3, 5, 10, 15), seed=None):
    """M9: same architecture/optimiser/lr/epochs/class-weighting as M8's
    train_mixed_cardinality, but the per-epoch column pool is the FULL 15
    columns (10 existing hybrid + 5 LOW-heterogeneity virtual), not just the
    10 real ones -- every cardinality, not only n=15, can draw a virtual
    column. Confounding "virtual provenance" with "large n" would let the
    model shortcut on which population a column came from instead of learning
    genuine cardinality robustness; sampling uniformly across the full pool at
    every size is what avoids that.

    `real` and `virtual` are (X, y, meta) triples from build_snapshots("train")
    and build_virtual_snapshots("train") respectively. Their row counts must
    match (both are scenario-count x ticks-per-split, deliberately mirrored --
    see generate_virtual_network_data.py's docstring)."""
    return _train_pooled_sets([real, virtual], sizes, factory, seed)
```

## scripts/benchmark_crossdevice_models.py:525 — train_virtual_only

```python
def train_virtual_only(virtual, factory=SetTransformer, sizes=(2, 3, 5), seed=None):
    """Methodology ablation, not a training-regime candidate: the SAME
    architecture trained on ONLY the 5 virtual columns (no real hybrid
    columns at all), to measure whether the real+virtual pooling in
    train_mixed_provenance is earning its keep -- if real+virtual beats
    virtual-only on the REAL test set, that is direct evidence real telemetry
    still matters even after adding virtual scale, not an assumption."""
    return _train_pooled_sets([virtual], sizes, factory, seed)
```

## scripts/benchmark_crossdevice_models.py:680 — m9_seed_study

```python
def m9_seed_study(n_seeds=10):
    """The full M9 study: 10-seed training with per-seed threshold reporting
    across four regimes, plus a real+virtual vs. virtual-only ablation.

    - Real Test A / LOW virtual: threshold fit fresh each seed on that
      regime's OWN validation split (choose_threshold), then frozen for test
      -- the same protocol evaluate_gnn_baselines.py's docstring locks in.
    - MEDIUM/HIGH stress: NOT re-fit. These have no validation split by
      design (generate_virtual_network_data.py only builds their TEST split)
      -- they reuse the SAME seed's LOW-fitted threshold, frozen, because the
      question is "how does the already-calibrated model degrade under
      distribution shift", not "what threshold would look best here". Fitting
      a threshold on stress-test data would answer a different, less useful
      question and make MEDIUM/HIGH look better than they should.
    - Ablation: the SAME per-seed architecture trained on virtual columns
      ONLY (no real hybrid columns), evaluated on REAL test with its own
      real-validation-fit threshold -- tests whether real+virtual pooling
      (train_mixed_provenance) is actually earning its keep over virtual data
      alone.

    Snapshots don't depend on the training seed and are built ONCE.
    """
    print("Building snapshots (once; reused across all seeds)...")
    real_tr, real_va, real_te = build_snapshots("train")[:3], build_snapshots("validation")[:3], build_snapshots("test")[:3]
    virt_tr = build_virtual_snapshots("train", "LOW")
    virt_va = build_virtual_snapshots("validation", "LOW")
    virt_te = build_virtual_snapshots("test", "LOW")
    medium_te = build_virtual_snapshots("test", "MEDIUM")
    high_te = build_virtual_snapshots("test", "HIGH")
    print(f"  real train={len(real_tr[0])} virtual train={len(virt_tr[0])}")

    rows = {k: [] for k in ("real", "low", "medium", "high", "ablation_real")}

    for seed in range(n_seeds):
        t0 = time.perf_counter_ns()
        model, _elapsed_ms, _epochs = train_mixed_provenance(real_tr, virt_tr, seed=seed)
        abl_model, _, _ = train_virtual_only(virt_tr, seed=seed)

        thr_real, m_real = _fit_and_eval(model, real_va, real_te, N_NODES)
        thr_low, m_low = _fit_and_eval(model, virt_va, virt_te, N_VIRTUAL_NODES)
        m_medium = _eval_at_threshold(model, *medium_te, N_VIRTUAL_NODES, thr_low)
        m_high = _eval_at_threshold(model, *high_te, N_VIRTUAL_NODES, thr_low)
        thr_abl, m_abl = _fit_and_eval(abl_model, real_va, real_te, N_NODES)

        rows["real"].append({"threshold": thr_real, **m_real})
        rows["low"].append({"threshold": thr_low, **m_low})
        rows["medium"].append({"threshold": thr_low, **m_medium})   # frozen, not re-fit
        rows["high"].append({"threshold": thr_low, **m_high})       # frozen, not re-fit
        rows["ablation_real"].append({"threshold": thr_abl, **m_abl})

        dt_s = (time.perf_counter_ns() - t0) / 1e9
        print(f"  seed {seed}: real f1={m_real['f1']:.3f}  low f1={m_low['f1']:.3f}  "
              f"medium f1={m_medium['f1']:.3f}  high f1={m_high['f1']:.3f}  "
              f"ablation(virtual-only on real) f1={m_abl['f1']:.3f}  ({dt_s:.1f}s)")

    metric_keys = ["threshold", "f1", "precision", "recall",
                   "false_positive_rate", "detection_rate", "roc_auc", "pr_auc"]
    summary = {}
    for regime, recs in rows.items():
        summary[regime] = {mk: mean_ci([r[mk] for r in recs]) for mk in metric_keys}

    print(f"\n{'=' * 100}")
    print(f"M9 -- {n_seeds}-SEED STUDY SUMMARY (mean +/- 95% CI over training seeds)")
    print(f"{'=' * 100}")
    labels = {"real": "Real Test A (n=10)", "low": "LOW virtual (n=5)",
              "medium": "MEDIUM stress (frozen thr)", "high": "HIGH stress (frozen thr)",
              "ablation_real": "Ablation: virtual-only-trained, on real test"}
    for regime, label in labels.items():
        print(f"\n{label}:")
        for mk in metric_keys:
            s = summary[regime][mk]
            ci = f"+/-{s['ci95']:.4f}" if s.get("ci95") is not None else "(n<2)"
            print(f"    {mk:22s} {s['mean']:.4f} {ci}")

    path = os.path.join(RESULTS_DIR, "m9_seed_study.json")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"n_seeds": n_seeds, "summary": summary, "per_seed": rows}, f, indent=2, default=float)
    print(f"\nwritten to {path}")
    return summary
```

## scripts/benchmark_crossdevice_models.py:766 — _eval_slice

```python
def _eval_slice(model, X, y, meta, thr, col_idx=None, scenario=None):
    """Metrics at a FROZEN threshold (the model's own full-network,
    validation-fit threshold -- never re-fit per slice, since the question is
    'how does the already-deployed decision behave on this slice', not 'what
    threshold would look best here'), restricted to a column subset and/or a
    single scenario."""
    k = X.shape[1]
    scores = deep_sets_scores(model, X[:, np.arange(k)])
    valid = np.array([m["valid"] for m in meta])
    if scenario is not None:
        row_idx = np.array([i for i, m in enumerate(meta) if m["scenario"] == scenario])
        if len(row_idx) == 0:
            return None
        scores, y, valid = scores[row_idx], y[row_idx], valid[row_idx]
    if col_idx is not None:
        scores, y, valid = scores[:, col_idx], y[:, col_idx], valid[:, col_idx]
    s, lab = scores[valid], y[valid]
    result = metrics(s, lab, thr)
    if not np.any(lab == 0):
        result.update(f1=None, recall=None, detection_rate=None,
                      undefined_reason="no anomalous observations")
    if not np.any(lab == 1):
        result["false_positive_rate"] = None
    return result
```

## scripts/benchmark_crossdevice_models.py:892 — validation_halves

```python
def validation_halves(meta, keep):
    """Split validation rows into a CALIBRATION half and a SELECTION half.

    A calibrator is a fit, not a selection. Fitting it on the same rows the
    threshold is then read from would make the reported FPR the calibrator's
    training error -- the exact shape of leak this project has already had to
    withdraw a published number over. The two halves are disjoint.

    The cut is CONTIGUOUS within each scenario, not random: neighbouring ticks
    share LSTM-AE windows and belong to the same event, so a random row split
    would put two views of one disturbance on both sides of the wall."""
    ticks = {}
    for t, _i in keep:
        ticks.setdefault(meta[t]["scenario"], []).append(meta[t]["tick"])
    cut = {sc: sorted(v)[len(v) // 2] for sc, v in ticks.items()}
    calib = np.array([meta[t]["tick"] < cut[meta[t]["scenario"]] for t, _i in keep])
    return calib, ~calib
```

## src/coap_server.py:57 — TelemetryHTTPSHandler

```python
class TelemetryHTTPSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # quiet -- gateway.process_telemetry() already prints one line per message

    def do_POST(self):
        import gateway  # deferred import -- avoids a circular import at module load time

        if self.path.strip("/") != COAP_TELEMETRY_PATH:
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            envelope = json.loads(body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"malformed JSON")
            return

        gateway.process_telemetry(envelope, transport="https", transport_secured=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
```

## src/coap_server.py:91 — start_https_server

```python
def start_https_server() -> HTTPServer:
    """Starts the HTTPS telemetry server in a background thread (same
    non-blocking pattern gateway.py already uses for MQTT's loop_start())
    and returns the server object so the caller can .shutdown() it if
    needed. Runs forever otherwise."""
    server = HTTPServer(("0.0.0.0", COAP_TLS_PORT), TelemetryHTTPSHandler)
    server.socket = _build_ssl_context().wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[https] listening on https://0.0.0.0:{COAP_TLS_PORT}/{COAP_TELEMETRY_PATH} "
          f"(Module 6's second secured transport -- see this file's docstring for why this substitutes for CoAP/DTLS)")
    return server
```

## Saved results/crossdevice_benchmark/m9_seed_study.json (selected top-level keys)

```json
{
  "n_seeds": 10,
  "summary": {
    "real": {
      "threshold": {
        "mean": 0.935,
        "ci95": 0.0379,
        "sd": 0.053,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.95,
          0.975,
          0.925,
          0.825,
          0.975,
          0.975,
          0.975,
          0.9,
          0.975,
          0.875
        ]
      },
      "f1": {
        "mean": 0.9671,
        "ci95": 0.0038,
        "sd": 0.0053,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9692,
          0.9615,
          0.9746,
          0.9677,
          0.9664,
          0.9591,
          0.9717,
          0.9724,
          0.96,
          0.968
        ]
      },
      "precision": {
        "mean": 0.9379,
        "ci95": 0.0076,
        "sd": 0.0106,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9427,
          0.9265,
          0.9517,
          0.9397,
          0.9368,
          0.9219,
          0.9474,
          0.9486,
          0.9236,
          0.9403
        ]
      },
      "recall": {
        "mean": 0.9981,
        "ci95": 0.0007,
        "sd": 0.0009,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9973,
          0.9993,
          0.9987,
          0.9973,
          0.998,
          0.9993,
          0.9973,
          0.9973,
          0.9993,
          0.9973
        ]
      },
      "false_positive_rate": {
        "mean": 0.0107,
        "ci95": 0.0014,
        "sd": 0.002,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.0098,
          0.0128,
          0.0082,
          0.0103,
          0.0109,
          0.0137,
          0.0089,
          0.0087,
          0.0133,
          0.0102
        ]
      },
      "detection_rate": {
        "mean": 0.9981,
        "ci95": 0.0007,
        "sd": 0.0009,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9973,
          0.9993,
          0.9987,
          0.9973,
          0.998,
          0.9993,
          0.9973,
          0.9973,
          0.9993,
          0.9973
        ]
      },
      "roc_auc": {
        "mean": 0.9996,
        "ci95": 0.0,
        "sd": 0.0001,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9996,
          0.9996,
          0.9996,
          0.9995,
          0.9996,
          0.9995,
          0.9995,
          0.9996,
          0.9997,
          0.9996
        ]
      },
      "pr_auc": {
        "mean": 0.9972,
        "ci95": 0.0003,
        "sd": 0.0005,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9975,
          0.9975,
          0.9974,
          0.9964,
          0.9972,
          0.9966,
          0.9969,
          0.9975,
          0.9978,
          0.997
        ]
      }
    },
    "low": {
      "threshold": {
        "mean": 0.97,
        "ci95": 0.0075,
        "sd": 0.0105,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.95,
          0.975,
          0.95
        ]
      },
      "f1": {
        "mean": 0.7563,
        "ci95": 0.0174,
        "sd": 0.0243,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.7866,
          0.76,
          0.7514,
          0.7477,
          0.7782,
          0.7503,
          0.7823,
          0.7537,
          0.7519,
          0.7008
        ]
      },
      "precision": {
        "mean": 0.6104,
        "ci95": 0.0225,
        "sd": 0.0314,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.6502,
          0.615,
          0.6038,
          0.5983,
          0.6392,
          0.602,
          0.6448,
          0.606,
          0.6041,
          0.5401
        ]
      },
      "recall": {
        "mean": 0.9955,
        "ci95": 0.0009,
        "sd": 0.0012,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9955,
          0.9944,
          0.9944,
          0.9967,
          0.9944,
          0.9955,
          0.9944,
          0.9967,
          0.9955,
          0.9978
        ]
      },
      "false_positive_rate": {
        "mean": 0.1126,
        "ci95": 0.0112,
        "sd": 0.0157,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.0943,
          0.1096,
          0.1149,
          0.1178,
          0.0988,
          0.1158,
          0.0964,
          0.1141,
          0.1149,
          0.1495
        ]
      },
      "detection_rate": {
        "mean": 0.9955,
        "ci95": 0.0009,
        "sd": 0.0012,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9955,
          0.9944,
          0.9944,
          0.9967,
          0.9944,
          0.9955,
          0.9944,
          0.9967,
          0.9955,
          0.9978
        ]
      },
      "roc_auc": {
        "mean": 0.987,
        "ci95": 0.0004,
        "sd": 0.0006,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9871,
          0.9875,
          0.9875,
          0.9859,
          0.9862,
          0.9872,
          0.9869,
          0.9872,
          0.9875,
          0.9866
        ]
      },
      "pr_auc": {
        "mean": 0.8832,
        "ci95": 0.0049,
        "sd": 0.0068,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.8792,
          0.8831,
          0.8834,
          0.873,
          0.8761,
          0.8823,
          0.8859,
          0.8869,
          0.8842,
          0.898
        ]
      }
    },
    "medium": {
      "threshold": {
        "mean": 0.97,
        "ci95": 0.0075,
        "sd": 0.0105,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.95,
          0.975,
          0.95
        ]
      },
      "f1": {
        "mean": 0.5436,
        "ci95": 0.0274,
        "sd": 0.0383,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.5911,
          0.5244,
          0.5194,
          0.5398,
          0.5812,
          0.511,
          0.5854,
          0.5857,
          0.5011,
          0.4971
        ]
      },
      "precision": {
        "mean": 0.3746,
        "ci95": 0.0261,
        "sd": 0.0364,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.4202,
          0.356,
          0.3513,
          0.3701,
          0.4104,
          0.3435,
          0.4146,
          0.4147,
          0.3347,
          0.331
        ]
      },
      "recall": {
        "mean": 0.9964,
        "ci95": 0.0006,
        "sd": 0.0009,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9966,
          0.9955,
          0.9955,
          0.9966,
          0.9955,
          0.9978,
          0.9955,
          0.9966,
          0.9966,
          0.9978
        ]
      },
      "false_positive_rate": {
        "mean": 0.2956,
        "ci95": 0.0324,
        "sd": 0.0453,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.2411,
          0.3158,
          0.3222,
          0.2974,
          0.2507,
          0.3344,
          0.2464,
          0.2466,
          0.3473,
          0.3536
        ]
      },
      "detection_rate": {
        "mean": 0.9964,
        "ci95": 0.0006,
        "sd": 0.0009,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9966,
          0.9955,
          0.9955,
          0.9966,
          0.9955,
          0.9978,
          0.9955,
          0.9966,
          0.9966,
          0.9978
        ]
      },
      "roc_auc": {
        "mean": 0.9578,
        "ci95": 0.0015,
        "sd": 0.0022,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9555,
          0.9606,
          0.9573,
          0.9545,
          0.956,
          0.9561,
          0.9588,
          0.9597,
          0.9603,
          0.9589
        ]
      },
      "pr_auc": {
        "mean": 0.7324,
        "ci95": 0.0066,
        "sd": 0.0093,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.7226,
          0.7445,
          0.7304,
          0.7212,
          0.7223,
          0.7263,
          0.7328,
          0.7373,
          0.7437,
          0.7427
        ]
      }
    },
    "high": {
      "threshold": {
        "mean": 0.97,
        "ci95": 0.0075,
        "sd": 0.0105,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.975,
          0.95,
          0.975,
          0.95
        ]
      },
      "f1": {
        "mean": 0.306,
        "ci95": 0.0069,
        "sd": 0.0096,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.3106,
          0.3009,
          0.2993,
          0.3008,
          0.312,
          0.2985,
          0.3147,
          0.3242,
          0.2916,
          0.3071
        ]
      },
      "precision": {
        "mean": 0.1807,
        "ci95": 0.0048,
        "sd": 0.0067,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.1839,
          0.1771,
          0.176,
          0.177,
          0.1849,
          0.1754,
          0.1867,
          0.1935,
          0.1707,
          0.1814
        ]
      },
      "recall": {
        "mean": 0.9999,
        "ci95": 0.0002,
        "sd": 0.0003,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          1.0,
          1.0,
          1.0,
          1.0,
          1.0,
          1.0,
          1.0,
          0.9989,
          1.0,
          1.0
        ]
      },
      "false_positive_rate": {
        "mean": 0.7921,
        "ci95": 0.0254,
        "sd": 0.0356,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.7741,
          0.8105,
          0.8166,
          0.8109,
          0.769,
          0.8197,
          0.7596,
          0.7262,
          0.8473,
          0.7868
        ]
      },
      "detection_rate": {
        "mean": 0.9999,
        "ci95": 0.0002,
        "sd": 0.0003,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          1.0,
          1.0,
          1.0,
          1.0,
          1.0,
          1.0,
          1.0,
          0.9989,
          1.0,
          1.0
        ]
      },
      "roc_auc": {
        "mean": 0.6583,
        "ci95": 0.0218,
        "sd": 0.0304,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.6568,
          0.6849,
          0.6633,
          0.6576,
          0.656,
          0.6678,
          0.6623,
          0.6769,
          0.6807,
          0.5768
        ]
      },
      "pr_auc": {
        "mean": 0.2045,
        "ci95": 0.0127,
        "sd": 0.0177,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.2019,
          0.2255,
          0.2052,
          0.2077,
          0.2034,
          0.2096,
          0.2072,
          0.211,
          0.2156,
          0.158
        ]
      }
    },
    "ablation_real": {
      "threshold": {
        "mean": 0.83,
        "ci95": 0.0887,
        "sd": 0.1241,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.925,
          0.825,
          0.95,
          0.75,
          0.75,
          0.75,
          0.575,
          0.875,
          0.95,
          0.95
        ]
      },
      "f1": {
        "mean": 0.9769,
        "ci95": 0.0007,
        "sd": 0.001,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9762,
          0.9765,
          0.9777,
          0.9774,
          0.9787,
          0.9765,
          0.9758,
          0.9781,
          0.9762,
          0.9762
        ]
      },
      "precision": {
        "mean": 0.958,
        "ci95": 0.0016,
        "sd": 0.0022,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9559,
          0.9571,
          0.9607,
          0.9589,
          0.9614,
          0.9571,
          0.9565,
          0.9608,
          0.9553,
          0.9565
        ]
      },
      "recall": {
        "mean": 0.9966,
        "ci95": 0.0005,
        "sd": 0.0007,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9973,
          0.9967,
          0.9953,
          0.9967,
          0.9967,
          0.9967,
          0.996,
          0.996,
          0.998,
          0.9967
        ]
      },
      "false_positive_rate": {
        "mean": 0.0071,
        "ci95": 0.0003,
        "sd": 0.0004,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.0074,
          0.0072,
          0.0066,
          0.0069,
          0.0065,
          0.0072,
          0.0073,
          0.0066,
          0.0075,
          0.0073
        ]
      },
      "detection_rate": {
        "mean": 0.9966,
        "ci95": 0.0005,
        "sd": 0.0007,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9973,
          0.9967,
          0.9953,
          0.9967,
          0.9967,
          0.9967,
          0.996,
          0.996,
          0.998,
          0.9967
        ]
      },
      "roc_auc": {
        "mean": 0.9987,
        "ci95": 0.0004,
        "sd": 0.0006,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9977,
          0.9993,
          0.9989,
          0.999,
          0.9978,
          0.9988,
          0.9992,
          0.9988,
          0.9983,
          0.9994
        ]
      },
      "pr_auc": {
        "mean": 0.9914,
        "ci95": 0.0028,
        "sd": 0.0039,
        "n_seeds": 10,
        "multiplier": "t",
        "per_seed": [
          0.9854,
          0.9935,
          0.9948,
          0.9947,
          0.9871,
          0.9902,
          0.9939,
          0.9906,
          0.9872,
          0.9966
        ]
      }
    }
  }
}
```

## Saved results/crossdevice_benchmark/seed_study.json (selected top-level keys)

```json
{
  "seeds": [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9
  ],
  "paired_effects": {
    "degree": {
      "M4_gcn": {
        "sd": 0.0479,
        "n_seeds": 10,
        "seeds_negative": 10,
        "levels": "1->9",
        "ci95": [
          -0.8502,
          -0.7818
        ],
        "t": -53.9,
        "t_crit": 2.262,
        "multiplier": "t",
        "significant": true,
        "per_seed": [
          -0.8925,
          -0.785,
          -0.8075,
          -0.89,
          -0.78,
          -0.8675,
          -0.7875,
          -0.7975,
          -0.775,
          -0.7775
        ],
        "mean_delta": -0.816
      },
      "M5_gatv2": {
        "sd": 0.2783,
        "n_seeds": 10,
        "seeds_negative": 4,
        "levels": "1->9",
        "ci95": [
          -0.2646,
          0.1336
        ],
        "t": -0.744,
        "t_crit": 2.262,
        "multiplier": "t",
        "significant": false,
        "per_seed": [
          0.035,
          -0.1375,
          0.07,
          0.07,
          0.08,
          0.2,
          -0.755,
          -0.1925,
          0.155,
          -0.18
        ],
        "mean_delta": -0.0655
      },
      "M6_set_transformer": {
        "sd": 0.0,
        "n_seeds": 10,
        "seeds_negative": 0,
        "levels": "1->9",
        "significant": false,
        "note": "flat by construction",
        "mean_delta": 0.0
      },
      "M3_deep_sets": {
        "sd": 0.0,
        "n_seeds": 10,
        "seeds_negative": 0,
        "levels": "1->9",
        "significant": false,
        "note": "flat by construction",
        "mean_delta": 0.0
      }
    },
    "peer_density": {
      "M4_gcn": {
        "sd": 0.0686,
        "n_seeds": 10,
        "seeds_negative": 0,
        "levels": "0->36",
        "ci95": [
          0.1404,
          0.2386
        ],
        "t": 8.736,
        "t_crit": 2.262,
        "multiplier": "t",
        "significant": true,
        "per_seed": [
          0.21,
          0.025,
          0.2375,
          0.2475,
          0.1575,
          0.1775,
          0.165,
          0.23,
          0.18,
          0.265
        ],
        "mean_delta": 0.1895
      },
      "M5_gatv2": {
        "sd": 0.285,
        "n_seeds": 10,
        "seeds_negative": 10,
        "levels": "0->36",
        "ci95": [
          -0.4771,
          -0.0694
        ],
        "t": -3.032,
        "t_crit": 2.262,
        "multiplier": "t",
        "significant": true,
        "per_seed": [
          -0.78,
          -0.305,
          -0.105,
          -0.285,
          -0.055,
          -0.7775,
          -0.0025,
          -0.245,
          -0.07,
          -0.1075
        ],
        "mean_delta": -0.2732
      },
      "M6_set_transformer": {
        "sd": 0.0,
        "n_seeds": 10,
        "seeds_negative": 0,
        "levels": "0->36",
        "significant": false,
        "note": "flat by construction",
        "mean_delta": 0.0
      },
      "M3_deep_sets": {
        "sd": 0.0,
        "n_seeds": 10,
        "seeds_negative": 0,
        "levels": "0->36",
        "significant": false,
        "note": "flat by construction",
        "mean_delta": 0.0
      }
    }
  },
  "interaction": {
    "within_model": {
      "M4_gcn": {
        "mean": -1.0055,
        "sd": 0.0943,
        "n_seeds": 10,
        "seeds_negative": 10,
        "contrast": "degree minus peer_density",
        "ci95": [
          -1.0729,
          -0.9381
        ],
        "t": -33.723,
        "t_crit": 2.262,
        "multiplier": "t",
        "significant": true,
        "per_seed": [
          -1.1025,
          -0.81,
          -1.045,
          -1.1375,
          -0.9375,
          -1.045,
          -0.9525,
          -1.0275,
          -0.955,
          -1.0425
        ]
      },
      "M5_gatv2": {
        "mean": 0.2078,
        "sd": 0.4733,
        "n_seeds": 10,
        "seeds_negative": 2,
        "contrast": "degree minus peer_density",
        "ci95": [
          -0.1308,
          0.5463
        ],
        "t": 1.388,
        "t_crit": 2.262,
        "multiplier": "t",
        "significant": false,
        "per_seed": [
          0.815,
          0.1675,
          0.175,
          0.355,
          0.135,
          0.9775,
          -0.7525,
          0.0525,
          0.225,
          -0.0725
        ]
      }
    },
    "across_models": {
      "mean": -1.2132,
      "sd": 0.5174,
      "n_seeds": 10,
      "seeds_negative": 10,
      "contrast": "(M4_gcn - M5_gatv2) of (degree minus peer_density)",
      "ci95": [
        -1.5833,
        -0.8432
      ],
      "t": -7.416,
      "t_crit": 2.262,
      "multiplier": "t",
      "significant": true,
      "per_seed": [
        -1.9175,
        -0.9775,
        -1.22,
        -1.4925,
        -1.0725,
        -2.0225,
        -0.2,
        -1.08,
        -1.18,
        -0.97
      ]
    }
  }
}
```

## Generator validator transcript

```text
Real resting rows: 103 (7 runs, lengths [11, 10, 14, 9, 17, 18, 24]), split='train'

--- LOW preset (618 generated rows over 42 blocks) ---
  [1] marginals (detrended residuals):
        rms            KS=0.076 p=0.6670  OK
        peak           KS=0.084 p=0.5400  OK
        kurtosis       KS=0.040 p=0.9980  OK
        dominant_freq  KS=0.081 p=0.5902  OK
  [2] cross-feature correlation: max abs diff = 0.086, mean = 0.039
  [3] lag-1 autocorrelation: real=[ 0.284  0.083  0.092 -0.005] generated=[0.264 0.053 0.093 0.091] max diff=0.097
  [4] real-vs-generated residual discriminator (balanced, n=103 each): accuracy=0.466  OK (near-chance)
  [clip] rms clip engaged on 0.0% of generated rows

--- MEDIUM preset (618 generated rows over 42 blocks) ---
  [1] marginals (detrended residuals):
        rms            KS=0.175 p=0.0082  DIVERGES
        peak           KS=0.108 p=0.2382  OK
        kurtosis       KS=0.070 p=0.7677  OK
        dominant_freq  KS=0.078 p=0.6413  OK
  [2] cross-feature correlation: max abs diff = 0.085, mean = 0.043
  [3] lag-1 autocorrelation: real=[ 0.284  0.083  0.092 -0.005] generated=[0.269 0.14  0.084 0.107] max diff=0.113
  [4] real-vs-generated residual discriminator (balanced, n=103 each): accuracy=0.461  OK (near-chance)
  [clip] rms clip engaged on 0.0% of generated rows

--- HIGH preset (618 generated rows over 42 blocks) ---
  [1] marginals (detrended residuals):
        rms            KS=0.243 p=0.0000  DIVERGES
        peak           KS=0.188 p=0.0035  DIVERGES
        kurtosis       KS=0.113 p=0.1966  OK
        dominant_freq  KS=0.139 p=0.0610  OK
  [2] cross-feature correlation: max abs diff = 0.109, mean = 0.064
  [3] lag-1 autocorrelation: real=[ 0.284  0.083  0.092 -0.005] generated=[0.226 0.131 0.046 0.021] max diff=0.058
  [4] real-vs-generated residual discriminator (balanced, n=103 each): accuracy=0.515  OK (near-chance)
  [clip] rms clip engaged on 0.0% of generated rows

--- [5] heterogeneity ordering (cross-node rms spread) ---
        LOW    spread=0.00794
        MEDIUM spread=0.01509
        HIGH   spread=0.03842
        LOW < MEDIUM < HIGH: OK

SOME CHECKS FAILED

```
