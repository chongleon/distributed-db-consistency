"""
Normal Operation - Run All Experiments

功能：
    自动运行四种 Client-Centric Consistency 实验：

        RYW
        MR
        MW
        WFR

    每种实验分别测试四种 MongoDB 配置：

        C1: local    + w:1
        C2: majority + w:1
        C3: local    + majority
        C4: majority + majority

    总共：
        4 consistency models × 4 configurations
        = 16 组实验

    同时记录：
        1. MongoDB 官方对该配置的 consistency guarantee
        2. 实际实验观察结果

输出：
    1. 在终端打印每组实验结果
    2. 将所有实验结果保存到：

        results/normal.csv
"""

import csv
import os
import sys

import ryw
import mr
import mw
import wfr


# ============================================================
# Experiment settings
# ============================================================

CONFIGS = [
    "C1",
    "C2",
    "C3",
    "C4"
]


EXPERIMENTS = {
    "RYW": ryw.run_experiment,
    "MR": mr.run_experiment,
    "MW": mw.run_experiment,
    "WFR": wfr.run_experiment
}


# ============================================================
# MongoDB documented predictions
# ============================================================
#
# Predictions under causally consistent client sessions.
#
# GUARANTEED:
#     MongoDB provides the corresponding consistency guarantee.
#
# NOT_GUARANTEED:
#     MongoDB does not guarantee that the consistency model
#     will hold in all situations.
#

PREDICTIONS = {

    "RYW": {
        "C1": "NOT_GUARANTEED",
        "C2": "NOT_GUARANTEED",
        "C3": "NOT_GUARANTEED",
        "C4": "GUARANTEED"
    },

    "MR": {
        "C1": "NOT_GUARANTEED",
        "C2": "GUARANTEED",
        "C3": "NOT_GUARANTEED",
        "C4": "GUARANTEED"
    },

    "MW": {
        "C1": "NOT_GUARANTEED",
        "C2": "NOT_GUARANTEED",
        "C3": "GUARANTEED",
        "C4": "GUARANTEED"
    },

    "WFR": {
        "C1": "NOT_GUARANTEED",
        "C2": "GUARANTEED",
        "C3": "NOT_GUARANTEED",
        "C4": "GUARANTEED"
    }
}


# ============================================================
# Determine observed result
# ============================================================

def get_observed_result(result):
    """
    Convert numerical experiment results into a simple
    observation label.

    VIOLATION_OBSERVED:
        At least one completed trial violated the
        consistency model.

    NO_VIOLATION_WITH_FAILURES:
        No violation was observed, but some trials
        could not complete.

    NO_VIOLATION_OBSERVED:
        All completed trials passed and no failures occurred.
    """

    if result["violations"] > 0:

        return "VIOLATION_OBSERVED"

    if result["failed"] > 0:

        return "NO_VIOLATION_WITH_FAILURES"

    return "NO_VIOLATION_OBSERVED"


# ============================================================
# Run all experiments
# ============================================================

def run_all(num_trials):

    results = []

    total_experiments = (
        len(CONFIGS)
        * len(EXPERIMENTS)
    )

    current_experiment = 0

    print(
        "\n=========================================="
    )

    print(
        "       NORMAL OPERATION EXPERIMENTS"
    )

    print(
        "=========================================="
    )

    print(
        f"Trials per experiment: {num_trials}"
    )

    print(
        f"Total experiments:     {total_experiments}"
    )

    print(
        "=========================================="
    )

    # ========================================================
    # Run RYW / MR / MW / WFR
    # ========================================================

    for consistency_name, experiment_function in (
        EXPERIMENTS.items()
    ):

        # ====================================================
        # Run C1 / C2 / C3 / C4
        # ====================================================

        for config_name in CONFIGS:

            current_experiment += 1

            print(
                "\n##########################################"
            )

            print(
                f"[{current_experiment}/{total_experiments}] "
                f"{consistency_name} - {config_name}"
            )

            print(
                "##########################################"
            )

            try:

                # --------------------------------------------
                # Run experiment
                # --------------------------------------------

                result = experiment_function(
                    config_name,
                    num_trials
                )

                # --------------------------------------------
                # Add scenario
                # --------------------------------------------

                result["scenario"] = "normal"

                # --------------------------------------------
                # Add MongoDB documented prediction
                # --------------------------------------------

                result["predicted_guarantee"] = (
                    PREDICTIONS[
                        consistency_name
                    ][
                        config_name
                    ]
                )

                # --------------------------------------------
                # Add observed result
                # --------------------------------------------

                result["observed_result"] = (
                    get_observed_result(
                        result
                    )
                )

                results.append(
                    result
                )

            except Exception as e:

                # --------------------------------------------
                # If an entire experiment crashes,
                # record it as failed but continue running
                # the remaining experiments.
                # --------------------------------------------

                print(
                    f"\nExperiment failed: "
                    f"{consistency_name} - {config_name}"
                )

                print(
                    f"{type(e).__name__}: {e}"
                )

                results.append(
                    {
                        "scenario": "normal",

                        "consistency": consistency_name,

                        "config": config_name,

                        "predicted_guarantee": (
                            PREDICTIONS[
                                consistency_name
                            ][
                                config_name
                            ]
                        ),

                        "observed_result": (
                            "EXPERIMENT_FAILED"
                        ),

                        "total_trials": num_trials,

                        "completed_trials": 0,

                        "passes": 0,

                        "violations": 0,

                        "failed": num_trials,

                        "violation_rate": 0.0,

                        "failure_rate": 100.0
                    }
                )

    return results


# ============================================================
# Save results to CSV
# ============================================================

def save_results(results):

    # --------------------------------------------------------
    # Create results folder automatically
    # --------------------------------------------------------

    os.makedirs(
        "results",
        exist_ok=True
    )

    output_file = os.path.join(
        "results",
        "normal.csv"
    )

    # --------------------------------------------------------
    # CSV columns
    # --------------------------------------------------------

    fieldnames = [
        "scenario",
        "consistency",
        "config",
        "predicted_guarantee",
        "observed_result",
        "total_trials",
        "completed_trials",
        "passes",
        "violations",
        "failed",
        "violation_rate",
        "failure_rate"
    ]

    # --------------------------------------------------------
    # Write CSV
    # --------------------------------------------------------

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as csvfile:

        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for result in results:

            writer.writerow(
                result
            )

    return output_file


# ============================================================
# Print final summary
# ============================================================

def print_summary(results):

    print(
        "\n\n"
        "=========================================================================="
    )

    print(
        "                              FINAL SUMMARY"
    )

    print(
        "=========================================================================="
    )

    print(
        f"{'Model':<8}"
        f"{'Config':<8}"
        f"{'Prediction':<18}"
        f"{'Pass':<8}"
        f"{'Violation':<12}"
        f"{'Failed':<8}"
        f"{'V-Rate':<10}"
        f"{'F-Rate':<10}"
    )

    print(
        "--------------------------------------------------------------------------"
    )

    for result in results:

        print(
            f"{result['consistency']:<8}"
            f"{result['config']:<8}"
            f"{result['predicted_guarantee']:<18}"
            f"{result['passes']:<8}"
            f"{result['violations']:<12}"
            f"{result['failed']:<8}"
            f"{result['violation_rate']:<10.2f}"
            f"{result['failure_rate']:<10.2f}"
        )

    print(
        "=========================================================================="
    )


# ============================================================
# Command-line entry point
# ============================================================

if __name__ == "__main__":

    # ========================================================
    # Check command-line arguments
    # ========================================================

    if len(sys.argv) != 2:

        print(
            "Usage: "
            "python run_all.py "
            "<num_trials>"
        )

        sys.exit(1)

    # ========================================================
    # Parse number of trials
    # ========================================================

    try:

        num_trials = int(
            sys.argv[1]
        )

        if num_trials <= 0:
            raise ValueError

    except ValueError:

        print(
            "num_trials must be "
            "a positive integer."
        )

        sys.exit(1)

    # ========================================================
    # Run all 16 experiments
    # ========================================================

    results = run_all(
        num_trials
    )

    # ========================================================
    # Save results
    # ========================================================

    output_file = save_results(
        results
    )

    # ========================================================
    # Print summary
    # ========================================================

    print_summary(
        results
    )

    print(
        f"\nResults saved to: {output_file}"
    )