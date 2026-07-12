"""Train the die-blade reliability classifier and export plain-JSON artifacts.

Mirrors train_reliability.py (task1) exactly: fit StandardScaler + LogisticRegression
on ml-training/data/reliability_dieblade_dataset.csv, then write the runtime
artifacts the backend loads with pure numpy:
  webapp/backend/ml/reliability_dieblade_model.json
  webapp/backend/ml/reliability_dieblade_meta.json
"""

import datetime
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, accuracy_score, confusion_matrix

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
from reliability_dieblade import FEATURE_NAMES, FEATURE_SCHEMA_VERSION  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "reliability_dieblade_dataset.csv")
ML_DIR = os.path.join(_BACKEND_DIR, "ml")
MODEL_PATH = os.path.join(ML_DIR, "reliability_dieblade_model.json")
META_PATH = os.path.join(ML_DIR, "reliability_dieblade_meta.json")

# 0.4 instead of task1's 0.5: threshold sweep on the validation set showed
# 0.4 as the precision==recall balance point (93.2%/93.2%), and spec.md's
# "치명 결함 미검출 0" priority favors erring toward recall — a missed FN here
# means a real defect goes unflagged, while a FP just asks a human to double-
# check (no rejection). The frontend badge threshold (DetectionListDieBlade.tsx)
# must be kept in sync with this value.
DECISION_THRESHOLD = 0.4
RANDOM_STATE = 20260711


def load_dataset():
    df = pd.read_csv(CSV_PATH)
    versions = set(df["schema_version"].unique().tolist())
    if versions != {FEATURE_SCHEMA_VERSION}:
        raise SystemExit(
            f"schema_version mismatch: CSV has {versions}, code expects {FEATURE_SCHEMA_VERSION}"
        )
    X = df[FEATURE_NAMES].to_numpy(dtype=np.float64)
    y = df["label"].to_numpy(dtype=np.int64)
    return df, X, y


def main():
    os.makedirs(ML_DIR, exist_ok=True)
    df, X, y = load_dataset()

    X_tr, X_val, y_tr, y_val = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE, stratify=y
    )

    scaler = StandardScaler().fit(X_tr)
    clf = LogisticRegression(
        class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE
    ).fit(scaler.transform(X_tr), y_tr)

    proba_val = clf.predict_proba(scaler.transform(X_val))[:, 1]
    pred_val = (proba_val >= DECISION_THRESHOLD).astype(int)
    val_acc = float(accuracy_score(y_val, pred_val))
    val_prec = float(precision_score(y_val, pred_val, zero_division=0))
    val_rec = float(recall_score(y_val, pred_val, zero_division=0))
    cm = confusion_matrix(y_val, pred_val, labels=[0, 1]).tolist()

    model = {
        "coef": [float(c) for c in clf.coef_.reshape(-1)],
        "intercept": float(clf.intercept_.reshape(-1)[0]),
        "scaler_mean": [float(m) for m in scaler.mean_.reshape(-1)],
        "scaler_scale": [float(s) for s in scaler.scale_.reshape(-1)],
    }
    meta = {
        "model_type": "logreg_json",
        "schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "decision_threshold": DECISION_THRESHOLD,
        "trained_at": datetime.datetime.now().astimezone().isoformat(),
        "train_rows": int(len(y_tr)),
        "val_rows": int(len(y_val)),
        "val_accuracy": round(val_acc, 4),
        "val_precision": round(val_prec, 4),
        "val_recall": round(val_rec, 4),
        "val_confusion_matrix": cm,
        "class_weight": "balanced",
        "n_positive_total": int((y == 1).sum()),
        "n_negative_total": int((y == 0).sum()),
    }

    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("=== trained die-blade reliability classifier ===")
    print(f"rows total={len(y)}  train={len(y_tr)}  val={len(y_val)}")
    print(f"val: acc={val_acc:.3f} precision={val_prec:.3f} recall={val_rec:.3f}")
    print(f"val confusion [ [TN,FP],[FN,TP] ] = {cm}")
    print("coef (per feature):")
    for name, c in zip(FEATURE_NAMES, model["coef"]):
        print(f"   {name:26s} {c:+.4f}")
    print(f"intercept = {model['intercept']:+.4f}")
    print(f"model : {MODEL_PATH}")
    print(f"meta  : {META_PATH}")


if __name__ == "__main__":
    main()
