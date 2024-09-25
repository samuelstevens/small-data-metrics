"""
Entrypoint for running all benchmarks.

.. include:: ./tutorial.md
"""

import collections
import csv
import dataclasses
import json
import logging
import os
import resource
import sqlite3
import time
import typing

import beartype
import matplotlib.pyplot as plt
import numpy as np
import submitit
import torch
import tyro

from biobench import (
    ModelOrg,
    birds525,
    interfaces,
    iwildcam,
    kabr,
    newt,
    plantnet,
    rarespecies,
)

log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger("biobench")


@beartype.beartype
@dataclasses.dataclass(frozen=True)
class Args:
    """Params to run one or more benchmarks in a parallel setting."""

    slurm: bool = False
    """whether to use submitit to run jobs on a slurm cluster."""

    model_args: typing.Annotated[
        list[tuple[ModelOrg, str]], tyro.conf.arg(name="model")
    ] = dataclasses.field(
        default_factory=lambda: [
            ("open-clip", "RN50/openai"),
            ("open-clip", "ViT-B-16/openai"),
            ("open-clip", "ViT-B-16/laion400m_e32"),
            ("open-clip", "hf-hub:imageomics/bioclip"),
            ("open-clip", "ViT-B-16-SigLIP/webli"),
            ("timm-vit", "vit_base_patch14_reg4_dinov2.lvd142m"),
        ]
    )
    """model; a pair of model org (interface) and checkpoint."""
    device: typing.Literal["cpu", "cuda"] = "cuda"
    """which kind of accelerator to use."""
    debug: bool = False
    """whether to run in debug mode."""

    # Individual benchmarks.
    newt_run: bool = True
    """whether to run the NeWT benchmark."""
    newt_args: newt.Args = dataclasses.field(default_factory=newt.Args)
    """arguments for the NeWT benchmark."""
    kabr_run: bool = True
    """whether to run the KABR benchmark."""
    kabr_args: kabr.Args = dataclasses.field(default_factory=kabr.Args)
    """arguments for the KABR benchmark."""
    plantnet_run: bool = True
    """whether to run the Pl@ntNet benchmark."""
    plantnet_args: plantnet.Args = dataclasses.field(default_factory=plantnet.Args)
    """arguments for the Pl@ntNet benchmark."""
    iwildcam_run: bool = True
    """whether to run the iWildCam benchmark."""
    iwildcam_args: iwildcam.Args = dataclasses.field(default_factory=iwildcam.Args)
    """arguments for the iWildCam benchmark."""
    birds525_run: bool = True
    """whether to run the Birds 525 benchmark."""
    birds525_args: birds525.Args = dataclasses.field(default_factory=birds525.Args)
    """arguments for the Birds 525 benchmark."""
    rarespecies_run: bool = True
    """whether to run the RareSpecies benchmark."""
    rarespecies_args: rarespecies.Args = dataclasses.field(
        default_factory=rarespecies.Args
    )
    """arguments for the Birds 525 benchmark."""

    # Reporting and graphing.
    report_to: str = os.path.join(".", "reports")
    """where to save reports to."""
    graph: bool = True
    """whether to make a graph."""
    graph_to: str = os.path.join(".", "graphs")
    """where to save graphs to."""

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    def get_sqlite_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(os.path.join(self.report_to, "reports.sqlite"))


@beartype.beartype
def save(
    args: Args, model_args: interfaces.ModelArgs, report: interfaces.TaskReport
) -> None:
    """
    Saves the report to disk in a machine-readable SQLite format.
    """
    conn = args.get_sqlite_connection()
    with open("schema.sql") as fd:
        schema = fd.read()
    conn.execute(schema)

    model_org, model_ckpt = model_args
    lower, upper = report.get_confidence_interval()
    values = (
        model_org,
        model_ckpt,
        report.name,
        int(time.time()),
        report.get_mean_score(),
        lower,
        upper,
        json.dumps(dataclasses.asdict(args)),
        json.dumps(report.to_dict()),
    )
    conn.execute("INSERT INTO reports VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
    conn.commit()

    logger.info(
        "%s on %s: %.1f%%", model_ckpt, report.name, report.get_mean_score() * 100
    )
    for key, value in report.splits.items():
        logger.info("%s on %s; split '%s': %.3f", model_ckpt, report.name, key, value)


@beartype.beartype
def export_to_csv(args: Args) -> None:
    """
    Exports to a wide table format for viewing (long table formats are better for additional manipulation/graphing, but wide is easy for viewing).
    """
    conn = args.get_sqlite_connection()
    stmt = "SELECT model_ckpt, task_name, mean_score, MAX(posix) AS posix FROM reports GROUP BY model_ckpt, task_name ORDER BY model_ckpt ASC;"
    data = conn.execute(stmt, ()).fetchall()

    tasks = set()
    rows = collections.defaultdict(lambda: collections.defaultdict(float))
    for model_ckpt, task_name, mean_score, _ in data:
        rows[model_ckpt][task_name] = mean_score
        tasks.add(task_name)

    for model, scores in rows.items():
        scores["mean"] = np.mean([scores[task] for task in tasks]).item()

    path = os.path.join(args.report_to, "results.csv")
    with open(path, "w") as fd:
        writer = csv.writer(fd)
        writer.writerow(["model", "mean"] + sorted(tasks))
        for model in sorted(rows, key=lambda model: rows[model]["mean"], reverse=True):
            scores = rows[model]
            writer.writerow(
                [model, scores["mean"]] + [scores[task] for task in sorted(tasks)]
            )
    logger.info("Wrote results to '%s'.", path)


@beartype.beartype
def main(args: Args):
    # 1. Setup executor.
    if args.slurm:
        raise NotImplementedError("submitit not implemented.")
        executor = submitit.SlurmExecutor()
    else:
        executor = submitit.DebugExecutor(folder="logs")

    # 2. Run benchmarks.
    jobs = []
    for model_args in args.model_args:
        if args.newt_run:
            newt_args = dataclasses.replace(
                args.newt_args, device=args.device, debug=args.debug
            )
            jobs.append(executor.submit(newt.benchmark, newt_args, model_args))
        if args.kabr_run:
            kabr_args = dataclasses.replace(
                args.kabr_args, device=args.device, debug=args.debug
            )
            jobs.append(executor.submit(kabr.benchmark, kabr_args, model_args))
        if args.plantnet_run:
            plantnet_args = dataclasses.replace(
                args.plantnet_args, device=args.device, debug=args.debug
            )
            job = executor.submit(plantnet.benchmark, plantnet_args, model_args)
            jobs.append(job)
        if args.iwildcam_run:
            iwildcam_args = dataclasses.replace(
                args.iwildcam_args, device=args.device, debug=args.debug
            )
            job = executor.submit(iwildcam.benchmark, iwildcam_args, model_args)
            jobs.append(job)
        if args.birds525_run:
            birds525_args = dataclasses.replace(
                args.birds525_args, device=args.device, debug=args.debug
            )
            job = executor.submit(birds525.benchmark, birds525_args, model_args)
            jobs.append(job)
        if args.rarespecies_run:
            rarespecies_args = dataclasses.replace(
                args.rarespecies_args, device=args.device, debug=args.debug
            )
            job = executor.submit(rarespecies.benchmark, rarespecies_args, model_args)
            jobs.append(job)

    logger.info("Submitted %d jobs.", len(jobs))

    # 3. Display results.
    os.makedirs(args.report_to, exist_ok=True)
    for i, future in enumerate(submitit.helpers.as_completed(jobs)):
        err = future.exception()
        if err:
            logger.warning("Error running job: %s: %s", err, err.__cause__)
            continue

        model_args, report = future.result()
        save(args, model_args, report)
        logger.info("Finished %d/%d jobs.", i + 1, len(jobs))

    # 4. Save results to CSV file for committing to git.
    export_to_csv(args)

    # 5. Make graphs.
    if args.graph:
        # For each combination of model/task, get the most recent version from the database. Then make a graph and save it to disk.
        conn = args.get_sqlite_connection()
        for task in ("KABR", "NeWT", "Pl@ntNet", "iWildCam", "Birds525"):
            fig = plot_task(conn, task)
            if fig is None:
                continue
            os.makedirs(args.graph_to, exist_ok=True)
            path = os.path.join(args.graph_to, f"{task}.png")
            fig.savefig(path)
            logger.info("Saved fig for %s to %s.", task, path)

    logger.info("Finished.")


@beartype.beartype
def plot_task(conn: sqlite3.Connection, task: str) -> plt.Figure | None:
    """
    Plots the most recent result for each model on given task, including confidence intervals.
    Returns the figure so the caller can save or display it.
    """
    orig_row_factory = conn.row_factory

    conn.row_factory = sqlite3.Row
    fig, ax = plt.subplots()
    stmt = "SELECT model_ckpt, task_name, mean_score, confidence_lower, confidence_upper, MAX(posix) FROM reports WHERE task_name = (?) GROUP BY model_ckpt, task_name ORDER BY model_ckpt ASC;"
    data = conn.execute(stmt, (task,)).fetchall()

    conn.row_factory = orig_row_factory

    if not data:
        return

    xs = [row["model_ckpt"] for row in data]
    ys = [row["mean_score"] for row in data]

    yerr = np.array([ys, ys])
    yerr[0] = np.maximum(yerr[0] - [row["confidence_lower"] for row in data], 0)
    yerr[1] = np.maximum([row["confidence_upper"] for row in data] - yerr[1], 0)

    ax.errorbar(xs, ys, yerr, fmt="o", linewidth=2, capsize=6)
    ax.set_title(f"Mean {task} Performance")
    ax.tick_params(axis="x", labelrotation=20)

    fig.tight_layout()

    return fig


if __name__ == "__main__":
    args = tyro.cli(Args)

    # 0. Check on hardware accelerator.
    if args.device == "cuda" and not torch.cuda.is_available():
        logger.warning("No CUDA GPU found. Using CPU instead.")
        # Can't use CUDA, so might be on macOS, which cannot use spawn with pickle.
        torch.multiprocessing.set_start_method("fork")
        args = dataclasses.replace(args, device="cpu")
    elif args.device == "cuda" and torch.cuda.is_available():
        torch.multiprocessing.set_start_method("spawn")

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    min_nofile = 1024 * 8
    if soft < min_nofile:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min_nofile, hard))

    main(args)
