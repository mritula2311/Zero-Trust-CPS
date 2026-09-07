"""
Explicit relational-model + fusion artifact pinning for GCN-vs-M6 comparator
scripts.

Background: scripts/evaluate_ablation_m6.py, evaluate_real_hardware.py,
evaluate_policy_comparison.py and evaluate_explainability_level2.py each
built a "GCN arm" by constructing GNNScorer() (true GCN) alongside
FusionEngine() (ambient config.FUSION_MODEL_PATH) -- which was a correct
pairing until the 2026-09-07 M6 deployment (3c827e8) overwrote
FUSION_MODEL_PATH with the M6-fitted model. After that, every "GCN arm"
silently paired true GCN relational scores with M6-calibrated fusion
coefficients: not a reproduction of anything real. See
docs/paper/17_CLAIM_EVIDENCE_MATRIX.md C03/C05/C15 and
docs/PAPER_READINESS_VERIFICATION.md.

A RelationalPin names one comparison arm's relational checkpoint AND its
matched fusion artifact together, by explicit path -- never by reading
whatever config.GNN_MODEL_PATH / config.FUSION_MODEL_PATH currently mean --
and verifies both against a hash recorded when this fix was written, so a
future artifact swap (accidental overwrite, a new deployment) makes a
comparator FAIL LOUDLY instead of silently mixing model families again.

Three known arms:
  gcn          -- the true, pre-deployment GCN checkpoint + its own fusion.
  m6_deployed  -- exactly what the live gateway runs today.
  m6_corrected -- a GCN-vs-M6 checkpoint retrained after fixing
                  train_set_transformer.py's class-weight bug (see that
                  file's docstring and
                  results/gcn_m6_corrected_comparison/summary.md). NOT
                  deployed -- evaluation/comparison only.
"""
import hashlib
import os
from dataclasses import dataclass

import sys
sys.path.insert(0, os.path.dirname(__file__))

from config import (
    GNN_MODEL_PATH,
    FUSION_MODEL_PATH_GCN_BACKUP, FUSION_BACKGROUND_PATH_GCN_BACKUP,
    SET_TRANSFORMER_MODEL_PATH,
    FUSION_MODEL_PATH_M6_VARIANT, FUSION_BACKGROUND_PATH_M6_VARIANT,
    SET_TRANSFORMER_MODEL_PATH_CORRECTED,
    FUSION_MODEL_PATH_M6_CORRECTED_VARIANT, FUSION_BACKGROUND_PATH_M6_CORRECTED_VARIANT,
)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ArtifactMismatchError(RuntimeError):
    """Raised by RelationalPin.verify() when a pinned file's actual hash no
    longer matches the hash recorded for that comparison arm -- i.e. the
    exact failure mode this module exists to make loud instead of silent."""


@dataclass(frozen=True)
class RelationalPin:
    name: str
    family: str  # "gcn" or "m6" -- which scorer class this arm loads
    relational_checkpoint: str
    relational_checkpoint_sha256: str
    fusion_model_path: str
    fusion_model_sha256: str
    fusion_background_path: str
    fusion_background_sha256: str

    def verify(self) -> None:
        checks = [
            (self.relational_checkpoint, self.relational_checkpoint_sha256, "relational checkpoint"),
            (self.fusion_model_path, self.fusion_model_sha256, "fusion model"),
            (self.fusion_background_path, self.fusion_background_sha256, "fusion background"),
        ]
        for path, expected, label in checks:
            if not os.path.exists(path):
                raise ArtifactMismatchError(
                    f"pin '{self.name}': {label} missing at {path} -- expected sha256 {expected}")
            got = sha256_of(path)
            if got != expected:
                raise ArtifactMismatchError(
                    f"pin '{self.name}': {label} at {path} has sha256 {got}, "
                    f"expected {expected}. An artifact this pin relies on changed "
                    f"since it was recorded -- do not trust a comparison built on "
                    f"this pin until it is re-verified/re-pinned.")

    def load_relational_scorer(self):
        self.verify()
        if self.family == "gcn":
            from gnn_scorer import GNNScorer
            return GNNScorer(checkpoint_path=self.relational_checkpoint)
        elif self.family == "m6":
            from set_transformer_scorer import SetTransformerScorer
            return SetTransformerScorer(checkpoint_path=self.relational_checkpoint)
        raise ValueError(f"unknown family {self.family!r}")

    def load_fusion_engine(self):
        self.verify()
        from fusion_engine import FusionEngine
        return FusionEngine(model_path=self.fusion_model_path, background_path=self.fusion_background_path)


# Hashes recorded 2026-09-07 while writing this fix -- see
# results/gcn_m6_corrected_comparison/artifact_lineage.json for the full
# lineage table (dataset, split, code version, commit) behind each one.
GCN = RelationalPin(
    name="gcn",
    family="gcn",
    relational_checkpoint=GNN_MODEL_PATH,
    relational_checkpoint_sha256="1d2028708aba69ff8b004eae6e2c58e6641959df10c4ec5ab9769e4cf925fa50",
    fusion_model_path=FUSION_MODEL_PATH_GCN_BACKUP,
    fusion_model_sha256="20ea7bcbba43861b21736c857c47d80434cd8e0daea42cd645a6aabd4abbf8e8",
    fusion_background_path=FUSION_BACKGROUND_PATH_GCN_BACKUP,
    fusion_background_sha256="8aa968a671ace9d1495b5f710a68e54e817094000f0f32d62ba8c16cc4fe8684",
)

M6_DEPLOYED = RelationalPin(
    name="m6_deployed",
    family="m6",
    relational_checkpoint=SET_TRANSFORMER_MODEL_PATH,
    relational_checkpoint_sha256="e4a65b5d899a6e9db18b47092bfc4a3b45ddc2db2ee49cef8adba593ae53b1bb",
    fusion_model_path=FUSION_MODEL_PATH_M6_VARIANT,
    fusion_model_sha256="d5e2bfeecc57142bf432ed233ec8f50c0e45a787f448a3590c8d849af955e934",
    fusion_background_path=FUSION_BACKGROUND_PATH_M6_VARIANT,
    fusion_background_sha256="c49113191841753e7d7c9f7b9537a0c9a643defc303581e07f18d251a4b37a71",
)

M6_CORRECTED = RelationalPin(
    name="m6_corrected",
    family="m6",
    relational_checkpoint=SET_TRANSFORMER_MODEL_PATH_CORRECTED,
    relational_checkpoint_sha256="910ed7a4b7388ea4025c3de922648e71f7b463459df9b125d84a7e241707859d",
    fusion_model_path=FUSION_MODEL_PATH_M6_CORRECTED_VARIANT,
    fusion_model_sha256="6d89db099e2fd4efd438af27ad2d6da6ea72d093fb7e31f055f11c69bfed19fa",
    fusion_background_path=FUSION_BACKGROUND_PATH_M6_CORRECTED_VARIANT,
    fusion_background_sha256="8d9018218a8881e0eb244e3b23678f7a23902b75b61bf74331644ec576aa1dee",
)

KNOWN_PINS = {p.name: p for p in (GCN, M6_DEPLOYED, M6_CORRECTED)}
