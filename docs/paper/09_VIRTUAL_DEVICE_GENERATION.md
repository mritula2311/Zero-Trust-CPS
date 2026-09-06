# Real-derived virtual-device generator

[VERIFIED: implementation; EXPERIMENTAL: validity regime] Sources: [generator](../../src/virtual_device_generator.py), [network generator](../../scripts/generate_virtual_network_data.py), [configuration](../../config/virtual_generator.json), [validation](../../scripts/validate_virtual_device_generator.py), [fresh diagnostic log](../../results/final_verification/generator_validation.log).

For free coordinates `(rms, peak, kurtosis, dominant_freq)`, the implemented form is

`x_v(t) = scale_v ⊙ x_base(t) + bias_v + AR1_v(t) + drift_v(t) + anomaly_v(t)`.

The scale is per-coordinate (a diagonal affine transform), not an arbitrary full matrix. Drift is sinusoidal with a 400-tick period and device-specific amplitude/phase. AR(1) residual innovations use the measured covariance and lag structure; the covariance construction accounts for `1−rho rho^T`. The anomaly term shifts a split-specific measured fault displacement with severity and coordination lag. Crest factor is re-derived from peak/RMS, RMS is bounded and dominant frequency is snapped to the MPU DFT grid.

Persistent virtual identity and fixed seeds produce reproducible transforms. Base trajectories wrap a contiguous real run; wrapping repeats physical samples and must not be counted as new acquisition. The five virtual streams all derive from the single MPU6050 source. This generator does not create independently validated SW-420 data or estimate manufacturing variability across devices.

| Preset | Scale range | Bias SD multiplier | Extra residual-noise fraction | Drift SD multiplier | Fault severity | Lag limit |
|---|---|---:|---:|---:|---|---|
| LOW | ±1.0% | 0.25 | 0.10 | 0.15 | 0.85–1.15 | 1 tick |
| MEDIUM | ±2.1% | 0.75 | 0.25 | 0.40 | 0.70–1.30 | 2 ticks |
| HIGH | ±5.0% | 2.00 | 0.50 | 1.00 | 0.50–1.60 | 3 ticks |

These ranges are controlled sensitivity parameters. MEDIUM's between-session proxy is still one board, not a between-device measurement.

The current diagnostic compares 103 TRAIN resting rows in seven runs with 618 generated residual rows per preset. LOW passes the selected marginal/correlation/lag/discriminator checks. MEDIUM and HIGH fail marginal checks; the script intentionally reports an overall nonzero status. Record LOW as internal TRAIN-residual consistency and MEDIUM/HIGH as OOD stress. The row-wise discriminator and KS comparisons use dependent data and the same source used to fit the generator, so they do not prove out-of-sample realism. “No easily separable residual signature was detected by the tested discriminator” is permissible with this qualifier; “indistinguishable from real” is not.

M9 stress evaluates downstream calibration as well as detection. Recall near one under HIGH accompanies very high FPR; it is not robustness. The [negative-results record](16_ABLATIONS_AND_NEGATIVE_RESULTS.md) preserves that failure and the unresolved virtual-only/hybrid chronology. Reproduce deterministic behavior with `tests/test_virtual_generator.py`; reproduce statistical diagnostics with the command in [24](24_REPRODUCIBILITY_GUIDE.md).
