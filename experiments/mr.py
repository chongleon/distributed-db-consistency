"""
我第一次 READ 看到了什么
        ↓
我第二次 READ 有没有倒退？

READ → READ
现在让第一次从Primary 读、第二次从 Secondary 读，让第二次 READ 真正有机会“倒退”
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
    update_collection,
    primary_read_collection,
    secondary_read_collection,
    config_name,
    trial_id
):
    """
    Run one Monotonic-Reads (MR) trial.

    Setup:
        Prepare version = 1.

    Experiment:
        1. Update the document to version = 2.
        2. READ 1 from the Primary.
        3. READ 2 from a Secondary.
        4. Check whether READ 2 is at least as new as READ 1.

    Returns:
        "PASS"
        "VIOLATION"
        "FAILED"
    """

    document_id = f"mr_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================

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

        # ----------------------------------------------------
        # Create a newer version
        # ----------------------------------------------------

        update_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 2
                }
            }
        )

        # ----------------------------------------------------
        # FIRST READ
        # ----------------------------------------------------
        # Read from Primary.

        first_result = primary_read_collection.find_one(
            {"_id": document_id}
        )

        if first_result is None:
            return "FAILED"

        first_version = first_result["version"]

        # ----------------------------------------------------
        # SECOND READ
        # ----------------------------------------------------
        # Read from Secondary.

        second_result = secondary_read_collection.find_one(
            {"_id": document_id}
        )

        if second_result is None:
            return "FAILED"

        second_version = second_result["version"]

        # ----------------------------------------------------
        # Check Monotonic Reads
        # ----------------------------------------------------

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

def run_experiment(
    config_name,
    num_trials
):

    client = create_client()

    pass_count = 0
    violation_count = 0
    failed_count = 0

    try:

        # ====================================================
        # Stable setup
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
        # Update collection
        # ====================================================
        # Uses the tested C1/C2/C3/C4 configuration.

        update_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # First READ -> Primary
        # ====================================================

        primary_read_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # Second READ -> Secondary
        # ====================================================

        secondary_read_collection = get_collection(
            client,
            config_name,
            read_from="secondary"
        )

        # ====================================================
        # Run N trials
        # ====================================================

        for trial_id in range(
            1,
            num_trials + 1
        ):

            result = run_one_trial(
                setup_collection,
                update_collection,
                primary_read_collection,
                secondary_read_collection,
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
        pass_count
        + violation_count
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

    print(
        "\n========== MR RESULTS =========="
    )

    print(
        f"Configuration:      {config_name}"
    )

    print(
        "Read path:          "
        "Primary READ -> Secondary READ"
    )

    print(
        f"Total trials:       {total_trials}"
    )

    print(
        f"Completed trials:   {completed_trials}"
    )

    print(
        f"Passes:             {pass_count}"
    )

    print(
        f"Violations:         {violation_count}"
    )

    print(
        f"Failed trials:      {failed_count}"
    )

    print(
        f"Violation rate:     "
        f"{violation_rate:.2f}%"
    )

    print(
        f"Failure rate:       "
        f"{failure_rate:.2f}%"
    )

    print(
        "================================"
    )


# ============================================================
# Command-line entry point
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:

        print(
            "Usage: "
            "python mr.py "
            "<C1|C2|C3|C4> "
            "<num_trials>"
        )

        sys.exit(1)

    config_name = sys.argv[1].upper()

    num_trials = int(
        sys.argv[2]
    )

    run_experiment(
        config_name,
        num_trials
    )