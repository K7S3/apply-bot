"""DS metrics toolkit: reference implementations + interview explanations.

Pure stdlib, no numpy. Every metric is a pure function over plain lists.

Usage:
    python -m candid ds-metrics f1 --y-true 1 0 1 1 --y-score 0.9 0.2 0.8 0.4
    python -m candid ds-metrics explain auc
    python -m candid ds-metrics list

Metric subcommands take space-separated values:
    --y-true   ground truth labels / outcomes
    --y-score  predicted scores (probabilities, or relevance scores)
    --y-treat  binary treatment indicator (only for `uplift`)
    --threshold 0.5   score -> 0/1 cutoff for threshold metrics
    --k 10    cutoff rank for lift/gain/ndcg/map
    --bins 10 number of calibration bins
"""

from __future__ import annotations

import math


class DSMetricsError(Exception):
    """Raised for ds-metrics usage errors (bad inputs, unknown metric)."""


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------

def _as_list(xs, name: str) -> list[float]:
    if xs is None:
        raise DSMetricsError(f"--{name} is required for this metric.")
    vals = [float(x) for x in xs]
    if not vals:
        raise DSMetricsError(f"--{name} must not be empty.")
    return vals


def _check_same(a: list[float], b: list[float]) -> None:
    if len(a) != len(b):
        raise DSMetricsError(
            f"Length mismatch: y_true has {len(a)} values, "
            f"the other input has {len(b)}.")


def thresholdize(y_score: list[float], threshold: float = 0.5) -> list[int]:
    """Binarize scores at a threshold."""
    return [1 if s >= threshold else 0 for s in y_score]


# ---------------------------------------------------------------------------
# binary classification metrics
# ---------------------------------------------------------------------------

def confusion(y_true: list[float], y_pred: list[float]) -> dict:
    """TP/TN/FP/FN counts."""
    _check_same(y_true, y_pred)
    tp = tn = fp = fn = 0
    for t, p in zip(y_true, y_pred):
        t, p = int(t), int(p)
        if p == 1 and t == 1:
            tp += 1
        elif p == 0 and t == 0:
            tn += 1
        elif p == 1:
            fp += 1
        else:
            fn += 1
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def accuracy(y_true, y_pred) -> float:
    """Fraction of correct predictions."""
    _check_same(y_true, y_pred)
    return sum(1 for t, p in zip(y_true, y_pred) if int(t) == int(p)) / len(y_true)


def precision(y_true, y_pred) -> float:
    """TP / (TP + FP): of predicted positives, how many are right."""
    c = confusion(y_true, y_pred)
    denom = c["tp"] + c["fp"]
    return c["tp"] / denom if denom else 0.0


def recall(y_true, y_pred) -> float:
    """TP / (TP + FN): of actual positives, how many we caught."""
    c = confusion(y_true, y_pred)
    denom = c["tp"] + c["fn"]
    return c["tp"] / denom if denom else 0.0


def f1(y_true, y_pred) -> float:
    """Harmonic mean of precision and recall."""
    p, r = precision(y_true, y_pred), recall(y_true, y_pred)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def auc(y_true: list[float], y_score: list[float]) -> float:
    """Area under the ROC curve (Mann-Whitney U / average-rank form).

    P(a random positive scores higher than a random negative). Ties count
    as half a win.
    """
    _check_same(y_true, y_score)
    order = sorted(range(len(y_score)), key=lambda i: y_score[i])
    # average ranks for ties, ranks are 1-based
    ranks = [0.0] * len(y_score)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and y_score[order[j + 1]] == y_score[order[i]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    n_pos = sum(1 for t in y_true if int(t) == 1)
    n_neg = len(y_true) - n_pos
    if not n_pos or not n_neg:
        raise DSMetricsError("AUC needs both classes present in y_true.")
    rank_sum = sum(r for t, r in zip(y_true, ranks) if int(t) == 1)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def log_loss(y_true: list[float], y_score: list[float], eps: float = 1e-15) -> float:
    """Binary log-loss (cross-entropy) with probability clipping."""
    _check_same(y_true, y_score)
    total = 0.0
    for t, s in zip(y_true, y_score):
        p = min(max(s, eps), 1.0 - eps)
        total += -(t * math.log(p) + (1 - t) * math.log(1 - p))
    return total / len(y_true)


# ---------------------------------------------------------------------------
# regression metrics
# ---------------------------------------------------------------------------

def rmse(y_true: list[float], y_pred: list[float]) -> float:
    """Root mean squared error."""
    _check_same(y_true, y_pred)
    return math.sqrt(sum((t - p) ** 2 for t, p in zip(y_true, y_pred))
                     / len(y_true))


def mae(y_true: list[float], y_pred: list[float]) -> float:
    """Mean absolute error."""
    _check_same(y_true, y_pred)
    return sum(abs(t - p) for t, p in zip(y_true, y_pred)) / len(y_true)


# ---------------------------------------------------------------------------
# experimentation / uplift
# ---------------------------------------------------------------------------

def uplift(y_outcome: list[float], y_treat: list[float]) -> float:
    """Mean outcome in treated minus mean outcome in control.

    The simple difference-in-means estimator of the average treatment
    effect; y_treat is a binary 0/1 indicator.
    """
    _check_same(y_outcome, y_treat)
    treat = [o for o, t in zip(y_outcome, y_treat) if int(t) == 1]
    control = [o for o, t in zip(y_outcome, y_treat) if int(t) == 0]
    if not treat or not control:
        raise DSMetricsError("uplift needs both treated and control units.")
    return sum(treat) / len(treat) - sum(control) / len(control)


# ---------------------------------------------------------------------------
# ranking metrics
# ---------------------------------------------------------------------------

def _topk_indices(y_score: list[float], k: int) -> list[int]:
    if not 1 <= k <= len(y_score):
        raise DSMetricsError(f"--k must be between 1 and {len(y_score)}, got {k}.")
    return sorted(range(len(y_score)), key=lambda i: y_score[i],
                  reverse=True)[:k]


def lift_at_k(y_true: list[float], y_score: list[float], k: int) -> float:
    """Positive rate in the top-k by score, divided by the overall rate."""
    _check_same(y_true, y_score)
    top = _topk_indices(y_score, k)
    base_rate = sum(1 for t in y_true if int(t) == 1) / len(y_true)
    if base_rate == 0:
        return 0.0
    top_rate = sum(1 for i in top if int(y_true[i]) == 1) / k
    return top_rate / base_rate


def gain_at_k(y_true: list[float], y_score: list[float], k: int) -> float:
    """Fraction of all positives captured in the top-k by score (recall@k)."""
    _check_same(y_true, y_score)
    top = _topk_indices(y_score, k)
    total_pos = sum(1 for t in y_true if int(t) == 1)
    if total_pos == 0:
        return 0.0
    return sum(1 for i in top if int(y_true[i]) == 1) / total_pos


def ndcg_at_k(y_true: list[float], y_score: list[float], k: int) -> float:
    """Normalized discounted cumulative gain at k.

    y_true holds relevance grades (binary or graded); higher = more
    relevant. NDCG = DCG / ideal DCG.
    """
    _check_same(y_true, y_score)
    top = _topk_indices(y_score, k)
    dcg = sum((2.0 ** y_true[i] - 1.0) / math.log2(rank + 2)
              for rank, i in enumerate(top))
    ideal = sorted(y_true, reverse=True)[:k]
    idcg = sum((2.0 ** r - 1.0) / math.log2(rank + 2)
               for rank, r in enumerate(ideal))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def map_at_k(y_true: list[float], y_score: list[float], k: int) -> float:
    """Average precision at k: mean of precision@i over relevant hits in the
    top-k, normalized by the total number of relevant items overall."""
    _check_same(y_true, y_score)
    top = _topk_indices(y_score, k)
    total_rel = sum(1 for t in y_true if int(t) == 1)
    if total_rel == 0:
        return 0.0
    hits, running = 0, 0.0
    for rank, i in enumerate(top, 1):
        if int(y_true[i]) == 1:
            hits += 1
            running += hits / rank
    return running / total_rel


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------

def calibration(y_true: list[float], y_score: list[float],
                bins: int = 10) -> dict:
    """Reliability summary of predicted probabilities.

    Returns expected calibration error (ECE), max calibration error (MCE),
    and per-bin (predicted mean, actual rate, count).
    """
    _check_same(y_true, y_score)
    if bins < 1:
        raise DSMetricsError("--bins must be >= 1.")
    width = 1.0 / bins
    ece, mce, rows = 0.0, 0.0, []
    for b in range(bins):
        lo, hi = b * width, (b + 1) * width
        in_bin = [(t, s) for t, s in zip(y_true, y_score)
                  if (lo <= s < hi) or (b == bins - 1 and s == 1.0)]
        if not in_bin:
            continue
        pred_mean = sum(s for _, s in in_bin) / len(in_bin)
        actual = sum(t for t, _ in in_bin) / len(in_bin)
        gap = abs(pred_mean - actual)
        ece += (len(in_bin) / len(y_true)) * gap
        mce = max(mce, gap)
        rows.append({"bin": f"[{lo:.2f},{hi:.2f}]",
                     "pred_mean": round(pred_mean, 4),
                     "actual_rate": round(actual, 4),
                     "count": len(in_bin)})
    return {"ece": round(ece, 6), "mce": round(mce, 6), "bins": rows}


# ---------------------------------------------------------------------------
# registry: CLI wiring + interview explanations
# ---------------------------------------------------------------------------

#: input kind per metric: thresholded preds | raw scores | treatment labels
_INPUT_KIND = {
    "accuracy": "pred", "precision": "pred", "recall": "pred", "f1": "pred",
    "auc": "score", "log-loss": "score", "rmse": "score", "mae": "score",
    "uplift": "treat", "lift": "score", "gain": "score",
    "ndcg": "score", "map": "score", "calibration": "score",
}


def compute_metric(name: str, *, y_true, y_score=None, threshold: float = 0.5,
                   k: int | None = None, bins: int = 10,
                   y_treat=None) -> float | dict:
    """Compute a registered metric by name from raw CLI inputs."""
    if name not in _INPUT_KIND:
        raise DSMetricsError(
            f"Unknown metric {name!r}. Available: {', '.join(METRIC_NAMES)}")
    t = _as_list(y_true, "y-true")
    kind = _INPUT_KIND[name]
    if kind == "treat":
        treat = _as_list(y_treat, "y-treat")
        return uplift(t, treat)
    s = _as_list(y_score, "y-score")
    _check_same(t, s)
    if kind == "pred":
        return {
            "accuracy": accuracy, "precision": precision,
            "recall": recall, "f1": f1,
        }[name](t, thresholdize(s, threshold))
    if k is None and name in ("lift", "gain", "ndcg", "map"):
        k = max(1, len(s) // 2)
    if name == "auc":
        return auc(t, s)
    if name == "log-loss":
        return log_loss(t, s)
    if name == "rmse":
        return rmse(t, s)
    if name == "mae":
        return mae(t, s)
    if name == "lift":
        return lift_at_k(t, s, k)
    if name == "gain":
        return gain_at_k(t, s, k)
    if name == "ndcg":
        return ndcg_at_k(t, s, k)
    if name == "map":
        return map_at_k(t, s, k)
    if name == "calibration":
        return calibration(t, s, bins=bins)
    raise DSMetricsError(f"Unknown metric {name!r}.")


METRIC_NAMES = list(_INPUT_KIND)


EXPLANATIONS = {
    "accuracy": {
        "what": "Fraction of all predictions that are correct: (TP+TN)/(TP+TN+FP+FN).",
        "formula": "accuracy = correct / total",
        "when": "Use when classes are balanced and errors cost about the same. Never alone on imbalanced data (a 99%-negative model scores 99% by always saying no).",
    },
    "precision": {
        "what": "Of the items you predicted positive, how many were actually positive: TP/(TP+FP).",
        "formula": "precision = TP / (TP + FP)",
        "when": "Use when false positives are expensive: spam filters, fraud alerts, medical screening follow-ups. Raising the threshold raises precision at the cost of recall.",
    },
    "recall": {
        "what": "Of the actual positives, how many you caught: TP/(TP+FN). Also called sensitivity or hit rate.",
        "formula": "recall = TP / (TP + FN)",
        "when": "Use when missing a positive is expensive: disease detection, churn rescue, defect inspection. Lowering the threshold raises recall at the cost of precision.",
    },
    "f1": {
        "what": "Harmonic mean of precision and recall: 2PR/(P+R). Punishes a model that is good at only one of the two.",
        "formula": "F1 = 2 * precision * recall / (precision + recall)",
        "when": "Use as a single summary for imbalanced classification when you need both precision and recall. Harmonic mean is low if either component is low.",
    },
    "auc": {
        "what": "Area under the ROC curve: the probability a random positive is scored above a random negative. Threshold-free ranking quality.",
        "formula": "AUC = P(score(pos) > score(neg)); 0.5 = random, 1.0 = perfect",
        "when": "Use for ranking quality independent of threshold (ads, recommendations, lead scoring). Caveat: ignores calibration and can look great on imbalanced data where precision@k is poor.",
    },
    "log-loss": {
        "what": "Binary cross-entropy: -mean(y*log(p) + (1-y)*log(1-p)). Penalizes confident wrong predictions heavily.",
        "formula": "log-loss = -mean( y*log(p) + (1-y)*log(1-p) )",
        "when": "Use as a training/eval objective when you need well-calibrated probabilities. Unlike accuracy, it rewards being 90% sure when right vs 51% sure.",
    },
    "rmse": {
        "what": "Root mean squared error: sqrt(mean((y - yhat)^2)). In the same units as y; large errors dominate because of the square.",
        "formula": "RMSE = sqrt( mean( (y - yhat)^2 ) )",
        "when": "Use when big misses are disproportionately costly (forecasting, pricing). Sensitive to outliers; prefer MAE if you want robustness.",
    },
    "mae": {
        "what": "Mean absolute error: mean(|y - yhat|). Each unit of error counts equally; median is its minimizer.",
        "formula": "MAE = mean( |y - yhat| )",
        "when": "Use when you want an interpretable 'typical miss' robust to outliers. Pairs naturally with median-based baselines.",
    },
    "uplift": {
        "what": "Difference in mean outcome between treated and control: E[Y|T=1] - E[Y|T=0]. The simple difference-in-means estimator of the average treatment effect.",
        "formula": "uplift = mean(outcome | treated) - mean(outcome | control)",
        "when": "Use for A/B test readout of the primary metric. Only causal under randomization (or proper adjustment); watch for SRM and peeking.",
    },
    "lift": {
        "what": "Positive rate in the top-k by score divided by the overall positive rate. 'How much better is our targeting than random?'",
        "formula": "lift@k = (positives in top-k / k) / overall positive rate",
        "when": "Use to justify a model for targeting: 'the top decile converts 3x the base rate'. Decile/lift charts are the standard stakeholder view.",
    },
    "gain": {
        "what": "Fraction of all positives captured in the top-k by score (also called recall@k). The cumulative-gain chart plots this across k.",
        "formula": "gain@k = positives in top-k / total positives",
        "when": "Use when coverage matters: 'what share of fraudsters do we catch by reviewing the top 5%?'. Cumulative gain charts show diminishing returns.",
    },
    "ndcg": {
        "what": "Normalized discounted cumulative gain: relevance-weighted sum of the ranked list with logarithmic position discounts, normalized by the ideal ranking.",
        "formula": "NDCG@k = sum((2^rel_i - 1)/log2(i+2)) / ideal DCG",
        "when": "Use for graded relevance in search/recommendation (positions matter, relevance is not binary). NDCG@k is the industry-standard ranking metric.",
    },
    "map": {
        "what": "Mean average precision at k: average of precision@i over each relevant hit in the top-k, normalized by total relevant items.",
        "formula": "AP@k = (1/R) * sum_{relevant hits i<=k} precision@i",
        "when": "Use for retrieval evaluation when both ranking and coverage matter (search quality, document retrieval). Sensitive to the full relevant set.",
    },
    "calibration": {
        "what": "Do predicted probabilities match observed frequencies? Bin predictions, compare mean predicted vs actual rate per bin; ECE is the count-weighted mean gap.",
        "formula": "ECE = sum_b (|bin_b|/n) * |pred_mean_b - actual_b|",
        "when": "Use before trusting 'probability' outputs for decisions, pricing, or expected-value math. Fix miscalibration with Platt scaling or isotonic regression.",
    },
}


def explain(name: str) -> str:
    """Interview-ready explanation: what the metric is, formula, when to use."""
    if name not in EXPLANATIONS:
        raise DSMetricsError(
            f"Unknown metric {name!r}. Available: {', '.join(METRIC_NAMES)}")
    e = EXPLANATIONS[name]
    return (f"{name}\n"
            f"{'=' * len(name)}\n\n"
            f"What it is:\n  {e['what']}\n\n"
            f"Formula:\n  {e['formula']}\n\n"
            f"When to use it:\n  {e['when']}")


def render_metric_list() -> str:
    """One-line summary of every registered metric."""
    lines = []
    for name in METRIC_NAMES:
        lines.append(f"{name:<12} {EXPLANATIONS[name]['what']}")
    return "\n".join(lines)


def render_result(name: str, value: float | dict) -> str:
    """Human-readable one-shot rendering of a computed metric."""
    if isinstance(value, dict):  # calibration
        lines = [f"{name}: ECE={value['ece']:.4f}  MCE={value['mce']:.4f}",
                 f"{'bin':<14}{'pred_mean':>10}{'actual':>10}{'n':>6}"]
        for b in value["bins"]:
            lines.append(f"{b['bin']:<14}{b['pred_mean']:>10.4f}"
                         f"{b['actual_rate']:>10.4f}{b['count']:>6}")
        return "\n".join(lines)
    return f"{name} = {value:.4f}"
