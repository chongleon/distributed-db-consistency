"""
我第一次 READ 看到了什么
        ↓
我第二次 READ 有没有倒退？

READ → READ
"""
import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one MR trial
# ============================================================

def run_one_trial(
    setup_collection,
    experiment_collection,
    config_name,
    trial_id
):
    """
    Run one Monotonic-Reads (MR) trial.

    Setup phase:
        Prepare a stable initial state: version = 1.

    Experiment phase:
        1. Perform the first READ.
        2. Write a newer version = 2.
        3. Perform the second READ.
        4. Check whether the second read returns the same
           or a newer version than the first read.

    Returns:
        "PASS"
        "VIOLATION"
        "FAILED"
    """

    # Each trial uses a different document.
    # This prevents different trials/configurations
    # from interfering with each other.
    document_id = f"mr_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================
        # Prepare a stable baseline.
        # This operation is NOT part of the MR experiment.

        setup_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 1
                }
            },
            upsert=True
        )

        # ====================================================
        # EXPERIMENT PHASE
        # ====================================================

        # -------------------------
        # FIRST READ
        # -------------------------

        first_result = experiment_collection.find_one(
            {"_id": document_id}
        )

        if first_result is None:
            return "FAILED"

        first_version = first_result["version"]

        # -------------------------
        # Create a newer version
        # -------------------------

        experiment_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 2
                }
            }
        )

        # -------------------------
        # SECOND READ
        # -------------------------

        second_result = experiment_collection.find_one(
            {"_id": document_id}
        )

        if second_result is None:
            return "FAILED"

        second_version = second_result["version"]

        # -------------------------
        # Check MR
        # -------------------------

        if second_version >= first_version:
            return "PASS"

        return "VIOLATION"

    except Exception as e:

        print(
            f"Trial {trial_id} failed: "
            f"{type(e).__name__}: {e}"
        )

        return "FAILED"


# ============================================================
# Run complete MR experiment
# ============================================================

def run_experiment(config_name, num_trials):

    client = create_client()

    pass_count = 0
    violation_count = 0
    failed_count = 0

    try:

        # ====================================================
        # SETUP COLLECTION
        # ====================================================
        # Use a fixed, reliable configuration to prepare
        # the initial state before each trial.

        setup_collection = (
            client["consistency_test"]
            .get_collection(
                "items",
                read_concern=ReadConcern("majority"),
                write_concern=WriteConcern(w="majority")
            )
        )

        # ====================================================
        # EXPERIMENT COLLECTION
        # ====================================================
        # This collection uses the actual configuration
        # being tested: C1 / C2 / C3 / C4.

        experiment_collection = get_collection(
            client,
            config_name
        )

        # ====================================================
        # Run N trials
        # ====================================================

        for trial_id in range(1, num_trials + 1):

            result = run_one_trial(
                setup_collection,
                experiment_collection,
                config_name,
                trial_id
            )

            if result == "PASS":
                pass_count += 1

            elif result == "VIOLATION":
                violation_count += 1

            else:
                failed_count += 1

    finally:
        client.close()

    # ========================================================
    # Statistics
    # ========================================================

    total_trials = num_trials

    completed_trials = (
        pass_count + violation_count
    )

    if completed_trials > 0:

        violation_rate = (
            violation_count
            / completed_trials
            * 100
        )

    else:
        violation_rate = 0.0

    failure_rate = (
        failed_count
        / total_trials
        * 100
    )

    # ========================================================
    # Print results
    # ========================================================

    print("\n========== MR RESULTS ==========")

    print(f"Configuration:      {config_name}")
    print(f"Total trials:       {total_trials}")
    print(f"Completed trials:   {completed_trials}")
    print(f"Passes:             {pass_count}")
    print(f"Violations:         {violation_count}")
    print(f"Failed trials:      {failed_count}")

    print(
        f"Violation rate:     "
        f"{violation_rate:.2f}%"
    )

    print(
        f"Failure rate:       "
        f"{failure_rate:.2f}%"
    )

    print("================================")


# ============================================================
# Command-line entry point
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:

        print(
            "Usage: "
            "python mr.py <C1|C2|C3|C4> "
            "<num_trials>"
        )

        sys.exit(1)

    config_name = sys.argv[1].upper()

    num_trials = int(sys.argv[2])

    run_experiment(
        config_name,
        num_trials
    )