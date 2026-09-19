"""
我 WRITE 了什么
        ↓
我之后 READ 有没有看到它？

WRITE → READ
"""
import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one RYW trial
# ============================================================

def run_one_trial(
    setup_collection,
    write_collection,
    read_collection,
    config_name,
    trial_id
):
    """
    Run one Read-Your-Writes (RYW) trial.

    Setup:
        Prepare version = 0 using a stable configuration.

    Experiment:
        1. WRITE version = 1.
        2. Wait for the WRITE acknowledgement.
        3. READ the same document from a Secondary.
        4. Check whether the READ observes version >= 1.

    Returns
    -------
    "PASS"
        The client observed its own write.

    "VIOLATION"
        The client read a version older than its own write.

    "FAILED"
        The operation could not complete.
    """

    # Every trial uses its own document.
    document_id = f"ryw_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================
        #
        # This is NOT part of the RYW experiment.
        #
        # We prepare a stable starting state:
        #
        # version = 0
        #

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

        # ----------------------------------------------------
        # WRITE
        # ----------------------------------------------------
        #
        # MongoDB writes are handled by the Primary.
        #

        written_version = 1

        write_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": written_version
                }
            }
        )

        # At this point the WRITE has returned according
        # to the selected Write Concern.

        # ----------------------------------------------------
        # READ
        # ----------------------------------------------------
        #
        # This collection uses Read Preference = Secondary.
        #
        # Therefore the READ is served by a Secondary replica.
        #

        result = read_collection.find_one(
            {"_id": document_id}
        )

        if result is None:
            return "FAILED"

        read_version = result["version"]

        # ----------------------------------------------------
        # Check Read-Your-Writes
        # ----------------------------------------------------

        if read_version >= written_version:
            return "PASS"

        return "VIOLATION"

    except Exception as e:

        print(
            f"Trial {trial_id} failed: "
            f"{type(e).__name__}: {e}"
        )

        return "FAILED"


# ============================================================
# Run complete RYW experiment
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
        # SETUP COLLECTION
        # ====================================================
        #
        # Fixed majority + majority configuration.
        #
        # This is used ONLY to prepare the starting state.
        #

        setup_collection = (
            client["consistency_test"]
            .get_collection(
                "items",

                read_concern=ReadConcern(
                    "majority"
                ),

                write_concern=WriteConcern(
                    w="majority"
                )
            )
        )

        # ====================================================
        # WRITE COLLECTION
        # ====================================================
        #
        # Uses the selected C1/C2/C3/C4 configuration.
        #
        # Read Preference is Primary.
        #

        write_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # READ COLLECTION
        # ====================================================
        #
        # Uses the SAME C1/C2/C3/C4 RC/WC configuration,
        # but READ operations are served by a Secondary.
        #

        read_collection = get_collection(
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
                write_collection,
                read_collection,
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
    # Calculate statistics
    # ========================================================

    total_trials = num_trials

    completed_trials = (
        pass_count
        + violation_count
    )

    # --------------------------------------------------------
    # Violation Rate
    # --------------------------------------------------------
    #
    # Only completed trials are used in the denominator.
    #

    if completed_trials > 0:

        violation_rate = (
            violation_count
            / completed_trials
            * 100
        )

    else:

        violation_rate = 0.0

    # --------------------------------------------------------
    # Failure Rate
    # --------------------------------------------------------

    failure_rate = (
        failed_count
        / total_trials
        * 100
    )

    # ========================================================
    # Print summary
    # ========================================================

    print(
        "\n========== RYW RESULTS =========="
    )

    print(
        f"Configuration:      {config_name}"
    )

    print(
        "Read path:          "
        "Primary WRITE -> Secondary READ"
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
        "================================="
    )


# ============================================================
# Command-line entry point
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:

        print(
            "Usage: "
            "python ryw.py "
            "<C1|C2|C3|C4> "
            "<num_trials>"
        )

        sys.exit(1)

    config_name = (
        sys.argv[1].upper()
    )

    num_trials = int(
        sys.argv[2]
    )

    run_experiment(
        config_name,
        num_trials
    )