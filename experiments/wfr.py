"""
WFR READ → WRITE
我的写是否建立在刚才读到的版本或更新版本上？
"""
import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one WFR trial
# ============================================================

def run_one_trial(
    setup_collection,
    experiment_collection,
    config_name,
    trial_id
):
    """
    Run one Writes-Follow-Reads (WFR) trial.

    Setup phase:
        Prepare a stable initial state: version = 1.

    Experiment phase:
        1. READ the current version.
        2. Perform a WRITE based on the version just read.
        3. Read the final state.
        4. Check whether the write was based on the same
           or a newer version than the version previously read.

    Returns:
        "PASS"
        "VIOLATION"
        "FAILED"
    """

    # Every trial uses an independent document.
    document_id = f"wfr_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================
        # Establish a stable starting state.
        # This is not part of the tested WFR operations.

        setup_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 1,
                    "based_on_version": 0
                }
            },
            upsert=True
        )

        # ====================================================
        # EXPERIMENT PHASE
        # ====================================================

        # -------------------------
        # READ
        # -------------------------

        read_result = experiment_collection.find_one(
            {"_id": document_id}
        )

        if read_result is None:
            return "FAILED"

        read_version = read_result["version"]

        # -------------------------
        # WRITE following the READ
        # -------------------------

        new_version = read_version + 1

        experiment_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": new_version,
                    "based_on_version": read_version
                }
            }
        )

        # -------------------------
        # FINAL READ
        # -------------------------

        final_result = experiment_collection.find_one(
            {"_id": document_id}
        )

        if final_result is None:
            return "FAILED"

        based_on_version = final_result["based_on_version"]

        # -------------------------
        # Basic WFR check
        # -------------------------

        if based_on_version >= read_version:
            return "PASS"

        return "VIOLATION"

    except Exception as e:

        print(
            f"Trial {trial_id} failed: "
            f"{type(e).__name__}: {e}"
        )

        return "FAILED"


# ============================================================
# Run complete WFR experiment
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
        # Fixed majority + majority configuration used only
        # to prepare a stable starting state.

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
        # Uses C1 / C2 / C3 / C4.

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

    print("\n========== WFR RESULTS ==========")

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

    print("=================================")


# ============================================================
# Command-line entry point
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:

        print(
            "Usage: "
            "python wfr.py <C1|C2|C3|C4> "
            "<num_trials>"
        )

        sys.exit(1)

    config_name = sys.argv[1].upper()

    num_trials = int(sys.argv[2])

    run_experiment(
        config_name,
        num_trials
    )