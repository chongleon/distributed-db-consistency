"""
同一个 process 对数据项 x 的一次 write
要在这个 process 后续对 x 的 write 之前完成
"""
import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one MW trial
# ============================================================

def run_one_trial(
    setup_collection,
    experiment_collection,
    config_name,
    trial_id
):
    """
    Run one Monotonic-Writes (MW) trial.

    Setup phase:
        Prepare a stable initial state: version = 0.

    Experiment phase:
        1. Perform WRITE 1: version = 1.
        2. Wait for WRITE 1 to return.
        3. Perform WRITE 2: version = 2.
        4. Read the final state.
        5. Check whether the later write is preserved.

    Returns:
        "PASS"
        "VIOLATION"
        "FAILED"
    """

    # Every trial uses its own document.
    document_id = f"mw_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================

        setup_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 0
                }
            },
            upsert=True
        )

        # ====================================================
        # EXPERIMENT PHASE
        # ====================================================

        # -------------------------
        # FIRST WRITE
        # -------------------------

        first_version = 1

        experiment_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": first_version
                }
            }
        )

        # WRITE 1 has returned according to
        # the selected write concern.

        # -------------------------
        # SECOND WRITE
        # -------------------------

        second_version = 2

        experiment_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": second_version
                }
            }
        )

        # -------------------------
        # FINAL READ
        # -------------------------

        result = experiment_collection.find_one(
            {"_id": document_id}
        )

        if result is None:
            return "FAILED"

        final_version = result["version"]

        # -------------------------
        # Basic MW check
        # -------------------------

        if final_version >= second_version:
            return "PASS"

        return "VIOLATION"

    except Exception as e:

        print(
            f"Trial {trial_id} failed: "
            f"{type(e).__name__}: {e}"
        )

        return "FAILED"


# ============================================================
# Run complete MW experiment
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

    print("\n========== MW RESULTS ==========")

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
            "python mw.py <C1|C2|C3|C4> "
            "<num_trials>"
        )

        sys.exit(1)

    config_name = sys.argv[1].upper()

    num_trials = int(sys.argv[2])

    run_experiment(
        config_name,
        num_trials
    )