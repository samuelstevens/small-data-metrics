import marimo

__generated_with = "0.11.14"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import math
    import sqlite3
    import numpy as np

    import polars as pl
    import matplotlib.pyplot as plt
    import matplotlib as mpl

    import sys

    if "." not in sys.path:
        sys.path.append(".")
    import small_data_metrics.reporting

    return math, mo, mpl, np, pl, plt, small_data_metrics, sqlite3, sys


@app.cell
def _(pl, sqlite3):
    bin_edges = [0, 1, 3, 10, 30, 100, 200, 300, 400, 500, 600]

    conn = sqlite3.connect("results/results.sqlite")

    preds_df = pl.read_database(
        f"SELECT results.task_name, results.task_cluster, results.task_subcluster, results.model_ckpt, predictions.score, predictions.n_train FROM results JOIN predictions ON results.rowid = predictions.result_id",
        conn,
        infer_schema_length=100_000,
    ).with_columns(
        n_train_bucketed=pl.col("n_train")
        .cut(bin_edges, include_breaks=True, left_closed=False)
        .struct.field("breakpoint")
    )
    return bin_edges, conn, preds_df


@app.cell
def _(preds_df):
    preds_df
    return


@app.cell
def _(np, pl, preds_df):
    def bootstrap_ci(scores, n_resamples=1000):
        scores = np.array(scores)
        # Vectorized bootstrap: sample all at once
        boot_samples = np.random.choice(
            scores, size=(n_resamples, len(scores)), replace=True
        )
        boot_means = boot_samples.mean(axis=1)
        ci_lower = np.percentile(boot_means, 2.5)
        ci_upper = np.percentile(boot_means, 97.5)
        return np.mean(scores), ci_lower, ci_upper

    def boot_func(scores):
        mean, ci_lower, ci_upper = bootstrap_ci(scores, 1000)
        return {"mean": mean, "ci_lower": ci_lower, "ci_upper": ci_upper}

    df = (
        preds_df.group_by("task_name", "n_train_bucketed", "model_ckpt")
        .all()
        .with_columns(
            pl.col("score")
            .map_elements(
                boot_func,
                return_dtype=pl.Struct([
                    pl.Field("mean", pl.Float64),
                    pl.Field("ci_lower", pl.Float64),
                    pl.Field("ci_upper", pl.Float64),
                ]),
            )
            .alias("boot")
        )
        .with_columns(
            mean=pl.col("boot").struct.field("mean"),
            ci_lower=pl.col("boot").struct.field("ci_lower"),
            ci_upper=pl.col("boot").struct.field("ci_upper"),
        )
    )

    df.sort(by=("model_ckpt", "task_name"))
    return boot_func, bootstrap_ci, df


@app.cell
def _(bin_edges):
    bin_edges
    return


@app.cell
def _(df, pl, plt, small_data_metrics):
    fig, ax = plt.subplots()
    for model, color in zip(
        sorted(df.get_column("model_ckpt").unique().to_list()),
        small_data_metrics.reporting.ALL_RGB01 * 10,
    ):
        filtered_df = df.filter((pl.col("model_ckpt") == model)).sort("n_train")

        means = filtered_df.get_column("mean").to_list()
        lowers = filtered_df.get_column("ci_lower").to_list()
        uppers = filtered_df.get_column("ci_upper").to_list()
        xs = filtered_df.get_column("n_train_bucketed").to_list()

        ax.plot(xs, means, marker="o", label=model, color=color)
        ax.fill_between(xs, lowers, uppers, alpha=0.2, color=color, linewidth=0)
        ax.set_xlabel("Number of Training Samples")
        ax.set_ylabel("Mean Accuracy")
        ax.set_ylim(0, 1.05)
        # ax.set_title(cluster.capitalize())
        ax.set_xscale("symlog", linthresh=2)
        ax.set_xticks(
            [0, 1, 3, 10, 30, 100, 300, 1000], [0, 1, 3, 10, 30, 100, 300, "1K"]
        )
        ax.set_xlim(-0.15, 1100)

        ax.legend(loc="best")

    fig.tight_layout()
    fig
    return ax, color, fig, filtered_df, lowers, means, model, uppers, xs


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
