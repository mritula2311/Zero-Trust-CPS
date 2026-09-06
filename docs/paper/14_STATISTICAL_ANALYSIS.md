# Statistical analysis and reporting rules

[VERIFIED: saved statistical implementation] The source [mean_ci and paired-effect code](../../scripts/benchmark_crossdevice_models.py) uses Student-t intervals over training seeds. The [seed study](../../results/crossdevice_benchmark/seed_study.json) records seeds 0–9, SD, half-width or interval endpoints, paired t statistics and raw per-seed differences. Degrees of freedom are 9 for ten refits. The [M9 seed study](../../results/crossdevice_benchmark/m9_seed_study.json) and [ablation](../../results/crossdevice_benchmark/m9_ablation_investigation.json) similarly retain per-seed samples.

| Statistical unit | Permitted statement | Invalid extrapolation |
|---|---|---|
| Training seed, same split | Refit mean/SD/95% t interval | Population or dataset sampling CI |
| Paired endpoint within seed | Mean within-fit intervention difference | Independent device causal effect |
| Node/tick test row | Descriptive confusion matrix, F1/AUC | Independent trials when sessions/events overlap |
| Hardware reading after warm-up | Observed detection/FPR with descriptive Wilson interval | Large-sample physical population guarantee |
| Generator residual row | Internal discrepancy/diagnostic effect size | Independent-sample realism hypothesis confirmation |

For seed results, report mean, SD, n and interval method; do not report only a favorable seed. The paired degree and peer-density results are tabulated in [13](13_RESULTS_MASTER_TABLES.md). Some peer-density seed effects reverse sign, and that variation remains visible. Flat-by-construction set-model effects should not be presented as a powered null-hypothesis discovery. Multiple intervention/model comparisons are not documented as multiplicity-adjusted.

No Wilcoxon or standardized paired effect-size values were found in the canonical JSONs; mark them [NOT REPORTED]. Do not invent p-values from a prose “significant” label. The saved paired t statistics/critical threshold support the stated within-seed test only. Single-seed M1–M9 rankings are descriptive even when their point estimates differ.

Anomaly-positive precision/recall are `TP/(TP+FP)` and `TP/(TP+FN)`; FPR is `FP/(FP+TN)`. Local replay uses normal-positive class1 and therefore its printed F1 means something different. Event recall counts whether at least one qualifying window detects an event; 15 events must not be conflated with 1,500 anomalous rows. Undefined normal-only F1 remains null, while false-alarm rate remains valid.

Recommended strengthening: grouped capture/session/device bootstrap or new independent capture splits; paired multi-seed M1–M9 comparisons under one frozen protocol; declared multiplicity policy and clinically/operationally meaningful alarm budgets. A bootstrap over repeated resampled raw rows would not create independent hardware evidence.
