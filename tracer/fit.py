"""Propose classification weights from the labelled corpus. NEVER writes config.

Multinomial logistic regression (CARRY = fixed reference class) over the
segments the corpus produces, L2-regularized toward the CURRENT config
values so proposals stay anchored to the hand-set cascade encoding unless
the data disagrees. Pure stdlib: the corpus is tiny, closed-form gradients
and batch gradient descent finish in milliseconds.

Day one (labels match the cascade) weights barely move — correct. The tool
earns its keep as misclassified real traces are promoted into tests/traces/.

Run: .venv/Scripts/python -m tracer.fit [--epochs 500] [--lr 0.2] [--l2 0.01]
Read the proposed block, decide, edit config.py by hand (sweep philosophy).
"""

import argparse
import math

from . import config, features, fixtures, sweep
from .match_state import MatchState

HINT_KEYS = set(config.TYPE_HINT_KEYS)

PARAM_NAMES = tuple(f"B_{c}" for c in features.SCORED_CLASSES) + tuple(
    f"W_{c}_{f.upper()}" for c in features.SCORED_CLASSES for f in features.FEATURES)


def training_set():
    """(feature dicts, labels, scenario names) from exact-actions scenarios.

    Hint-tap scenarios are excluded: k/p/r relabels poison geometric labels
    (hint_k traces a carry gesture labelled KICK). Scenarios whose segment
    count disagrees with expect are skipped — boundary errors are sweep's
    problem, not the classifier's.
    """
    xs, labels, names = [], [], []
    cases = [(sc.name, sc) for sc in fixtures.SCENARIOS.values()
             if "actions" in sc.expect
             and not any(k in HINT_KEYS for _, k in sc.taps)]
    for name, sc in cases:
        m = fixtures.open_play_match(sc.attack_dir, sc.possession)
        fixtures.inject(m, sc)
        segs = m.last_chain.segments if m.last_chain else []
        if len(segs) != len(sc.expect["actions"]):
            continue
        for ev, label in zip(m.last_debug["segments"], sc.expect["actions"]):
            xs.append(ev["features"])
            labels.append(label)
            names.append(name)
    return xs, labels, names


def _scores(params, x):
    out = {"CARRY": 0.0}
    for c in features.SCORED_CLASSES:
        out[c] = params[f"B_{c}"] + sum(
            params[f"W_{c}_{f.upper()}"] * x[f] for f in features.FEATURES)
    return out


def _probs(scores):
    peak = max(scores.values())
    exps = {c: math.exp(s - peak) for c, s in scores.items()}
    total = sum(exps.values())
    return {c: e / total for c, e in exps.items()}


def _accumulate_grad(params, xs, labels):
    """(gradient, cross-entropy loss) summed over the dataset for one epoch."""
    grad = dict.fromkeys(PARAM_NAMES, 0.0)
    loss = 0.0
    for x, label in zip(xs, labels):
        probs = _probs(_scores(params, x))
        loss -= math.log(max(probs[label], 1e-12))
        for c in features.SCORED_CLASSES:
            err = probs[c] - (1.0 if label == c else 0.0)
            grad[f"B_{c}"] += err
            for f in features.FEATURES:
                grad[f"W_{c}_{f.upper()}"] += err * x[f]
    return grad, loss


def train(xs, labels, epochs, lr, l2):
    """(fitted params, per-epoch losses). Reads config priors, never writes."""
    prior = {n: getattr(config, n) for n in PARAM_NAMES}
    params = dict(prior)
    losses = []
    n = len(xs)
    for _ in range(epochs):
        grad, loss = _accumulate_grad(params, xs, labels)
        loss /= n
        for name in PARAM_NAMES:
            reg = params[name] - prior[name]
            loss += l2 * reg * reg / n
            params[name] -= lr * (grad[name] / n + 2 * l2 * reg / n)
        losses.append(loss)
    return params, losses


def _confusion(params, xs, labels):
    counts = {}
    for x, label in zip(xs, labels):
        scores = _scores(params, x)
        got = max(features.CLASSES, key=lambda c: (scores[c], -features.CLASSES.index(c)))
        counts[(label, got)] = counts.get((label, got), 0) + 1
    return counts


def _corpus_pass(params):
    """Corpus pass count under params, config restored afterwards (sweep pattern)."""
    baseline = {n: getattr(config, n) for n in PARAM_NAMES}
    try:
        for n, v in params.items():
            setattr(config, n, v)
        return sweep.score()
    finally:
        for n, v in baseline.items():
            setattr(config, n, v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--epochs", type=int, default=500)
    ap.add_argument("--lr", type=float, default=0.2)
    ap.add_argument("--l2", type=float, default=0.01)
    args = ap.parse_args(argv)

    xs, labels, names = training_set()
    per_class = {c: labels.count(c) for c in features.CLASSES}
    skipped = sorted({sc.name for sc in fixtures.SCENARIOS.values()
                      if "actions" in sc.expect} - set(names))
    print(f"training set: {len(xs)} segments {per_class}")
    if skipped:
        print(f"skipped (hints or segment-count mismatch): {', '.join(skipped)}")

    params, losses = train(xs, labels, args.epochs, args.lr, args.l2)
    print(f"loss: {losses[0]:.4f} -> {losses[-1]:.4f} over {args.epochs} epochs")
    _report_corpus(params, xs, labels)
    _print_config_block(params)


def _report_corpus(params, xs, labels):
    """Corpus pass count and the label->predicted confusion under the proposal."""
    before_p, total, _ = sweep.score()
    after_p, _, after_fail = _corpus_pass(params)
    print(f"corpus: {before_p}/{total} at current config -> {after_p}/{total} proposed")
    if after_fail:
        print(f"  proposed fails: {', '.join(after_fail)}")
    print("confusion (label -> predicted) under proposal:")
    for (label, got), count in sorted(_confusion(params, xs, labels).items()):
        marker = "" if label == got else "   <-- MISS"
        print(f"  {label:>5} -> {got:<5} {count}{marker}")


def _print_config_block(params):
    print("\nproposed config block (paste by hand if the numbers convince you):")
    for c in features.SCORED_CLASSES:
        print(f"B_{c} = {params[f'B_{c}']:.3f}")
        for f in features.FEATURES:
            name = f"W_{c}_{f.upper()}"
            print(f"{name} = {params[name]:.3f}")


if __name__ == "__main__":
    main()
