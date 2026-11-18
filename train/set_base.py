#!/usr/bin/env python3
"""The checkpoint the next training continues from, made from a chosen model's weights (called by train.sh).

    python train/set_base.py <training_parameters.yaml> <best_weights.weights.h5> mixednet <model args…>

microWakeWord continues a run from ``<train_dir>/restore/`` (``--restore_checkpoint``), the state the
previous run ended with - not from its best weights. To start from another model (card 6 of the
panel: Models → Choose) the model is built with the same arguments as for training, its weights
are loaded and saved as that checkpoint. The optimizer starts fresh, as in a new run.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    config_path, weights, model_name, *model_args = sys.argv[1:]
    import tensorflow as tf
    from microwakeword import inception, mixednet
    from microwakeword.model_train_eval import load_config

    module = {"mixednet": mixednet, "inception": inception}[model_name]
    parser = argparse.ArgumentParser()
    parser.add_argument("--training_config")
    module.model_parameters(parser)
    flags = parser.parse_args(["--training_config", config_path, *model_args])
    config = load_config(flags, module)
    model = module.model(flags, config["training_input_shape"], config["batch_size"])
    model.load_weights(weights)
    restore = os.path.join(config["train_dir"], "restore")
    os.makedirs(restore, exist_ok=True)
    tf.train.Checkpoint(model=model).save(os.path.join(restore, "ckpt"))
    print(f"checkpoint for the next run: {restore} (from {weights})", flush=True)


if __name__ == "__main__":
    main()
