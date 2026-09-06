"use strict";
(() => {
  const sensors = {
    mpu: {
      title: "MPU6050 · capture and replay", kind: "Five-channel schema",
      features: ["rms", "peak", "crest_factor", "kurtosis", "dominant_freq"],
      evidence: "Two TRAIN sessions (114 and 152 rows), VALIDATION (47 rows), TEST (116 rows). Offline TEST replay after warm-up: 30/30 disturbances detected and 5/12 resting windows flagged.",
      limit: "Small, dependent hardware sample. This is not low-false-alarm reliability or complete sensor-to-enforcement validation. The implemented ‘peak’ feature is peak-to-peak."
    },
    sw: {
      title: "SW-420 · TRAIN capture only", kind: "Four-channel schema",
      features: ["trigger_rate", "duty_cycle", "burst_max_ms", "inter_event_cv"],
      evidence: "First physical capture: 20260905_162002, 321 TRAIN rows, including 140 all-zero resting readings. Per-device four-channel checkpoints exist.",
      limit: "SW-420 VALIDATION/TEST are pending. A saved checkpoint does not establish held-out detection performance. SW-420 is a digital vibration module, not a second MPU6050."
    }
  };
  document.querySelectorAll("[data-device]").forEach(button => {
    button.addEventListener("click", () => {
      const sensor = sensors[button.dataset.device];
      document.querySelectorAll("[data-device]").forEach(other => {
        other.classList.toggle("selected", other === button);
        other.setAttribute("aria-pressed", String(other === button));
      });
      document.getElementById("sensor-title").textContent = sensor.title;
      document.getElementById("sensor-kind").textContent = sensor.kind;
      document.getElementById("sensor-evidence").textContent = sensor.evidence;
      document.getElementById("sensor-limit").textContent = sensor.limit;
      document.getElementById("sensor-schema").replaceChildren(...sensor.features.map(name => {
        const item = document.createElement("li"); item.textContent = name; return item;
      }));
    });
  });
  document.querySelectorAll("[data-policy]").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-policy]").forEach(other => {
        const selected = other === button;
        other.setAttribute("aria-pressed", String(selected));
        other.classList.toggle("active-static", selected && other.dataset.policy === "static");
        other.classList.toggle("active-rl", selected && other.dataset.policy === "bandit");
        document.getElementById(other.dataset.policy + "-policy").hidden = !selected;
      });
    });
  });
  const security = document.getElementById("security"), process = document.getElementById("process");
  function illustratePolicy() {
    const sec = Number(security.value), proc = Number(process.value);
    const action = sec >= 0.6 ? (proc >= 0.6 ? "ALLOW" : "ALERT") : (proc >= 0.6 ? "STEP_UP" : "BLOCK");
    document.getElementById("security-value").value = sec.toFixed(2);
    document.getElementById("process-value").value = proc.toFixed(2);
    const result = document.getElementById("policy-result");
    result.textContent = action; result.dataset.action = action;
    document.getElementById("policy-reason").textContent = {
      ALLOW: "Both scores meet the static thresholds.",
      ALERT: "Trusted cyber behaviour with an abnormal process: flag operations.",
      STEP_UP: "Cyber trust is below threshold while the process appears normal: request additional verification.",
      BLOCK: "Both scores are below their static thresholds."
    }[action];
  }
  security.addEventListener("input", illustratePolicy);
  process.addEventListener("input", illustratePolicy);
  illustratePolicy();
})();
