"""
Run all Client-Centric Consistency experiments under three scenarios.

Scenarios:
    1. Normal operation
    2. Node failure
    3. Network partition

For each scenario:
    4 consistency models x 4 MongoDB configurations = 16 experiments

Total:
    3 scenarios x 16 experiments = 48 experiments

Usage:
    python run_all.py <num_trials>

Example:
    python run_all.py 100

Output:
    results/normal.csv
    results/node_failure.csv
    results/network_partition.csv
"""

import csv
import os
import subprocess
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
# Scenario settings
# ============================================================

SCENARIOS = {
    "normal": os.path.join(
        "..",
        "scripts",
        "normal.bat"
    ),

    "node_failure": os.path.join(
        "..",
        "scripts",
        "node_failure.bat"
    ),

    "network_partition": os.path.join(
        "..",
        "scripts",
        "network_partition.bat"
    )
}


# ============================================================
# MongoDB documented predictions
# ============================================================

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

    if result["violations"] > 0:
        return "VIOLATION_OBSERVED"

    if result["failed"] > 0:
        return "NO_VIOLATION_WITH_FAILURES"

    return "NO_VIOLATION_OBSERVED"


# ============================================================
# Activate scenario
# ============================================================

def activate_scenario(scenario_name):

    script_path = SCENARIOS[scenario_name]

    print("\n")
    print("=" * 74)
    print(f"ACTIVATING SCENARIO: {scenario_name.upper()}")
    print("=" * 74)
    print(f"Running: {script_path}")
    print("=" * 74)

    completed = subprocess.run(
        script_path,
        shell=True
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Scenario setup failed: {scenario_name}"
        )

    print(
        f"\nScenario '{scenario_name}' "
        f"activated successfully."
    )


# ============================================================
# Run all 16 experiments for ONE scenario
# ============================================================

def run_scenario(scenario_name, num_trials):

    results = []

    total_experiments = (
        len(CONFIGS)
        * len(EXPERIMENTS)
    )

    current_experiment = 0

    print("\n")
    print("=" * 74)
    print(
        f"{scenario_name.upper()} EXPERIMENTS"
    )
    print("=" * 74)

    print(
        f"Trials per experiment: {num_trials}"
    )

    print(
        f"Experiments in scenario: {total_experiments}"
    )

    print("=" * 74)

    for consistency_name, experiment_function in (
        EXPERIMENTS.items()
    ):

        for config_name in CONFIGS:

            current_experiment += 1

            print("\n")
            print("#" * 74)

            print(
                f"[{current_experiment}/{total_experiments}] "
                f"{scenario_name} | "
                f"{consistency_name} | "
                f"{config_name}"
            )

            print("#" * 74)

            try:

                result = experiment_function(
                    config_name,
                    num_trials
                )

                if result is None:
                    raise RuntimeError(
                        f"{consistency_name}.run_experiment() "
                        "returned None. "
                        "Check that the tester returns "
                        "its statistics dictionary."
                    )

                result["scenario"] = scenario_name

                result["predicted_guarantee"] = (
                    PREDICTIONS[
                        consistency_name
                    ][
                        config_name
                    ]
                )

                result["observed_result"] = (
                    get_observed_result(
                        result
                    )
                )

                results.append(result)

            except Exception as e:

                print(
                    f"\nExperiment failed: "
                    f"{consistency_name} - "
                    f"{config_name}"
                )

                print(
                    f"{type(e).__name__}: {e}"
                )

                results.append(
                    {
                        "scenario": scenario_name,

                        "consistency":
                            consistency_name,

                        "config":
                            config_name,

                        "predicted_guarantee":
                            PREDICTIONS[
                                consistency_name
                            ][
                                config_name
                            ],

                        "observed_result":
                            "EXPERIMENT_FAILED",

                        "total_trials":
                            num_trials,

                        "completed_trials":
                            0,

                        "passes":
                            0,

                        "violations":
                            0,

                        "failed":
                            num_trials,

                        "violation_rate":
                            0.0,

                        "failure_rate":
                            100.0
                    }
                )

    return results


# ============================================================
# Save ONE scenario to CSV
# ============================================================

def save_results(
    scenario_name,
    results
):

    os.makedirs(
        "results",
        exist_ok=True
    )

    output_file = os.path.join(
        "results",
        f"{scenario_name}.csv"
    )

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
            writer.writerow(result)

    return output_file


# ============================================================
# Print scenario summary
# ============================================================

def print_summary(
    scenario_name,
    results
):

    print("\n")
    print("=" * 90)

    print(
        f"FINAL SUMMARY - "
        f"{scenario_name.upper()}"
    )

    print("=" * 90)

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

    print("-" * 90)

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

    print("=" * 90)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 2:

        print(
            "Usage: "
            "python run_all.py "
            "<num_trials>"
        )

        sys.exit(1)

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
    # Run 3 scenarios x 16 experiments = 48 experiments
    # ========================================================

    print("\n")
    print("=" * 74)
    print("FULL EXPERIMENT SUITE")
    print("=" * 74)

    print(
        f"Trials per experiment: {num_trials}"
    )

    print(
        "Scenarios:             3"
    )

    print(
        "Experiments/scenario:  16"
    )

    print(
        "Total experiments:     48"
    )

    print(
        f"Total trials:          "
        f"{48 * num_trials}"
    )

    print("=" * 74)


    generated_files = []

    try:

        for scenario_name in SCENARIOS:

            # -----------------------------------------------
            # Change Docker environment
            # -----------------------------------------------

            activate_scenario(
                scenario_name
            )

            # -----------------------------------------------
            # Run 16 experiments
            # -----------------------------------------------

            results = run_scenario(
                scenario_name,
                num_trials
            )

            # -----------------------------------------------
            # Save CSV immediately
            # -----------------------------------------------

            output_file = save_results(
                scenario_name,
                results
            )

            generated_files.append(
                output_file
            )

            # -----------------------------------------------
            # Print summary
            # -----------------------------------------------

            print_summary(
                scenario_name,
                results
            )

            print(
                f"\nResults saved to: "
                f"{output_file}"
            )

    finally:

        # ====================================================
        # Always restore the cluster to NORMAL
        # ====================================================

        print("\n")
        print("=" * 74)
        print("RESTORING CLUSTER TO NORMAL")
        print("=" * 74)

        try:

            activate_scenario(
                "normal"
            )

        except Exception as e:

            print(
                "WARNING: automatic restoration "
                "failed."
            )

            print(
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # Final output
    # ========================================================

    print("\n")
    print("=" * 74)
    print("ALL EXPERIMENTS FINISHED")
    print("=" * 74)

    print(
        f"Total experiment groups: 48"
    )

    print(
        f"Total trials: "
        f"{48 * num_trials}"
    )

    print("\nGenerated files:")

    for output_file in generated_files:
        print(
            f"  {output_file}"
        )

    print("=" * 74)