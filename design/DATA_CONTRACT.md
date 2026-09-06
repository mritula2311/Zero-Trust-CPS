# Gateway view data contract

This is a view of existing gateway responses, with no model inference, trust updates or policy selection in the live frontend. Implementation authority: `src/gateway.py` DashboardHandler, `_build_devices_view`, `_process_telemetry`, `_reject`, `_silence_watchdog_loop`, and `src/audit_log.py`. The research presentation is separate and never fetches these endpoints.

| Endpoint | Actual fields consumed | Interpretation / gap |
|---|---|---|
| `/api/status` | `use_rl_policy`, `security_threshold`, `process_threshold` | Configured policy mode and thresholds; no model-loaded or gateway-health inventory |
| `/api/devices` | `devices[].device_id`, `kind` | Registered identities, not connected devices. No `last_seen`, revocation, hardware attestation or connection state |
| `/api/decisions` | `rows[]` newest first; `timestamp`, `device_id`, `decision`, `auth_ok`, `reason`, `reason_category`, `transport` | Recent audit window; event time is not last accepted telemetry time. Malformed envelopes may be dropped before logging |
| same | `security_trust_score`, `process_trust_score`, `process_status` | Separate scores, high means trusted/normal; missing or malformed numbers display an em dash (UNKNOWN), never measured zero |
| same | `rule_score`, `anomaly_score`, `lstm_score`, `gnn_score`, `fused_score`, `confidence` | `anomaly_score` is IF normality; GCN is the runtime relational model. Numeric fallback scores cannot be distinguished from trained inference without backend model status |
| same | `shap_rule`, `shap_isolation_forest`, `shap_lstm_ae`, `shap_gnn`, `level2_dominant_feature`, `level2_summary` | Actual fusion SHAP log-odds and backend Level-2 explanation; unavailable attribution remains missing |
| `/api/chain` | `chain_ok`, `checkpoint_ok`, `full_scan_ok`, `tail_ok`, scan ages and row counts | Missing checks are UNKNOWN; no assumed PASS |
| `/api/governance` | `coverage`, `tenets`, validation records and summary | Audit-window evidence, not certification |
| `/api/iec62443` | `frs`, status and notes | Implemented/partial evidence, not certification |
| `/api/qtable` | `trained`, `actions`, `rows`, `note` | Offline policy reference; no online fitting or exploration |

Fast polling fetches status, devices and decisions. Chain, governance, IEC and Q-table responses are cached for five polls. A new poll begins two seconds after completion; requests time out after eight seconds. Failed or malformed responses show RECONNECTING and identify retained observations as not current. There is no synthetic fallback, WebSocket or write endpoint.

`decision` is displayed verbatim. ALLOW / ALERT / STEP_UP / BLOCK are gateway policy results. REJECTED is an ingress event: the logged Security Trust is a read-only snapshot, Process Trust is absent, and accepted state is unchanged. SILENT with `reason_category=device_silent` is a watchdog event displayed as OFFLINE; it is not converted into a policy action. Never-seen identities and identities absent from the finite audit window display UNKNOWN. Watchdog `auth_ok=1` is not treated as evidence of a currently authenticated connection. Resumed accepted rows replace SILENT; the current watchdog does not log a separate recovery event.

The two named hardware identities are labelled PHYSICAL ID, not live physical measurements. Known software identities are labelled SIMULATED ID; unknown identities retain UNKNOWN provenance. The API cannot prove whether a message for a physical identity came from a board or a software stand-in. LIVE API MODE denotes the data connection only.

## Requires backend integration

- Raw MPU6050 `rms`, `peak`, `crest_factor`, `kurtosis`, `dominant_freq` and SW-420 `trigger_rate`, `duty_cycle`, `burst_max_ms`, `inter_event_cv` readings, sensor event timestamps and histories. These values are not in the dashboard audit API, so no raw telemetry chart is fabricated.
- Last accepted timestamp, authoritative online/freshness status, connected count, revocation/key status and independent HMAC/replay/freshness checks. Authentication is displayed only where an accepted audit observation supplies it.
- Model-loaded, fallback, pending, schema mismatch and all-invalid snapshot status. The frontend cannot relabel a backend numeric fallback as measured evidence or determine its cause from the current fields.
- A simulation provenance field and safe scenario control API. Offline checks run in a terminal, not through dashboard buttons. No automatic replay, signing keys or external-target controls are embedded in the UI.

The existing timeline's dashed 0.6 line is a static reference; header thresholds come from configuration. Shading is score disagreement, not a prediction of the configured bandit's action. The actual decision and backend explanation are authoritative.
