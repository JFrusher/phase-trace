"""Pre-game calibration: fold logged corrections into fit.py's weight proposal.

Reads the local correction DB (feedback.py), adds the reclassify corrections to
fit.py's fixture-corpus training set, and reruns the SAME L2-anchored logistic
regression fit.py uses. Prints what operators corrected + the proposed config
block. Like fit.py and sweep.py it NEVER writes config: read the block, decide,
edit config.py by hand. An empty DB makes this identical to `python -m tracer.fit`.

Run before a session:
  .venv/Scripts/python -m tracer.calibrate [--epochs 500] [--lr 0.2] [--l2 0.01]
"""

import argparse

from . import features, feedback, fit


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--epochs", type=int, default=500)
    ap.add_argument("--lr", type=float, default=0.2)
    ap.add_argument("--l2", type=float, default=0.01)
    args = ap.parse_args(argv)

    xs, labels, _ = fit.training_set()
    fx, fl = feedback.training_pairs()
    corpus_n = len(xs)
    xs, labels = xs + fx, labels + fl

    print(feedback.summary())
    per_class = ", ".join(f"{c}: {labels.count(c)}" for c in features.CLASSES)
    print(f"training set: {corpus_n} corpus + {len(fx)} logged corrections "
          f"= {len(xs)} segments {{{per_class}}}")
    if not fx:
        print("(no reclassify corrections logged yet — output equals tracer.fit)")

    params, losses = fit.train(xs, labels, args.epochs, args.lr, args.l2)
    print(f"loss: {losses[0]:.4f} -> {losses[-1]:.4f} over {args.epochs} epochs")
    fit._report_corpus(params, xs, labels)
    fit._print_config_block(params)


if __name__ == "__main__":
    main()
