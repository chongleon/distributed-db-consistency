import csv
import os
import time

from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import Primary


# ============================================================
# Experiment settings
# ============================================================

NUM_TRIALS = 10
REPLICATION_DELAY_SECONDS = 5

SCENARIO = "targeted_replication_lag"
CONSISTENCY = "RYW"
CONFIG = "C1"
PREDICTED_GUARANTEE = "NOT_GUARANTEED"


# ============================================================
# MongoDB clients
# ============================================================

# Replica-set client used for writes to the Primary.
client = MongoClient(
    "mongodb://mongo1:27017,mongo2:27018,mongo3:27019/"
    "?replicaSet=rs0",
    serverSelectionTimeoutMS=5000
)

db = client["consistency_test"]


# C1:
# readConcern  = local
# writeConcern = w:1
write_collection = db.get_collection(
    "targeted_ryw",
    read_concern=ReadConcern("local"),
    write_concern=WriteConcern(w=1),
    read_preference=Primary()
)


# Direct connection to the deliberately delayed Secondary.
#
# Before running this experiment, mongo3 is configured with:
#
#     secondaryDelaySecs = 5
#     priority = 0
#
mongo3_client = MongoClient(
    "mongodb://localhost:27019/?directConnection=true",
    serverSelectionTimeoutMS=2000
)

read_collection = (
    mongo3_client["consistency_test"]
    .get_collection(
        "targeted_ryw",
        read_concern=ReadConcern("local")
    )
)


# ============================================================
# Counters
# ============================================================

passes = 0
violations = 0
failed = 0


# ============================================================
# Run targeted RYW experiment
# ============================================================

print("\n")
print("=" * 74)
print("TARGETED REPLICATION-LAG EXPERIMENT")
print("=" * 74)

print(f"Consistency model:    {CONSISTENCY}")
print(f"Configuration:        {CONFIG} (local + w:1)")
print("Target Secondary:     mongo3")

print(
    f"Replication delay:    "
    f"{REPLICATION_DELAY_SECONDS} seconds"
)

print(f"Trials:               {NUM_TRIALS}")

print("=" * 74)


try:

    for trial in range(
        1,
        NUM_TRIALS + 1
    ):

        # Each trial uses an independent document.
        document_id = (
            f"targeted_ryw_{trial}"
        )

        try:

            # =================================================
            # SETUP PHASE
            # =================================================
            #
            # Prepare version = 0.
            #
            # This establishes the old version that will later
            # remain temporarily visible on delayed mongo3.
            #

            write_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "version": 0
                    }
                },
                upsert=True
            )


            # mongo3 applies replicated operations 5 seconds
            # later than the Primary.
            #
            # Wait slightly longer than the configured delay
            # so that version 0 is present on mongo3 before
            # beginning the actual RYW test.

            time.sleep(
                REPLICATION_DELAY_SECONDS + 1
            )


            # =================================================
            # WRITE
            # =================================================
            #
            # Under C1, w:1 means that the write may return
            # after acknowledgement from the Primary without
            # waiting for mongo3 to apply the update.
            #

            written_version = 1

            write_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "version":
                            written_version
                    }
                }
            )


            # =================================================
            # READ
            # =================================================
            #
            # Immediately read directly from mongo3.
            #
            # mongo3 is deliberately delayed, so it may still
            # contain version 0 when the read occurs.
            #

            result = (
                read_collection.find_one(
                    {"_id": document_id}
                )
            )


            # =================================================
            # Evaluate RYW
            # ============================================================

            if result is None:

                print(
                    f"Trial {trial:02d}: "
                    f"FAILED "
                    f"(document not found)"
                )

                failed += 1
                continue


            read_version = (
                result["version"]
            )


            if (
                read_version
                < written_version
            ):

                print(
                    f"Trial {trial:02d}: "
                    f"wrote={written_version}, "
                    f"read={read_version} "
                    f"-> VIOLATION"
                )

                violations += 1


            else:

                print(
                    f"Trial {trial:02d}: "
                    f"wrote={written_version}, "
                    f"read={read_version} "
                    f"-> PASS"
                )

                passes += 1


        except Exception as e:

            print(
                f"Trial {trial:02d}: "
                f"FAILED "
                f"({type(e).__name__}: {e})"
            )

            failed += 1


finally:

    client.close()
    mongo3_client.close()


# ============================================================
# Calculate statistics
# ============================================================

total_trials = NUM_TRIALS

completed_trials = (
    passes
    + violations
)


if completed_trials > 0:

    violation_rate = (
        violations
        / completed_trials
        * 100
    )

else:

    violation_rate = 0.0


failure_rate = (
    failed
    / total_trials
    * 100
)


# ============================================================
# Determine observed result
#
# Same rule as run_all.py
# ============================================================

if violations > 0:

    observed_result = (
        "VIOLATION_OBSERVED"
    )

elif failed > 0:

    observed_result = (
        "NO_VIOLATION_WITH_FAILURES"
    )

else:

    observed_result = (
        "NO_VIOLATION_OBSERVED"
    )


# ============================================================
# Build result dictionary
#
# Uses the SAME fields as run_all.py.
# ============================================================

result = {

    "scenario":
        SCENARIO,

    "consistency":
        CONSISTENCY,

    "config":
        CONFIG,

    "predicted_guarantee":
        PREDICTED_GUARANTEE,

    "observed_result":
        observed_result,

    "total_trials":
        total_trials,

    "completed_trials":
        completed_trials,

    "passes":
        passes,

    "violations":
        violations,

    "failed":
        failed,

    "violation_rate":
        violation_rate,

    "failure_rate":
        failure_rate
}


# ============================================================
# Print summary
# ============================================================

print("\n")
print("=" * 90)

print(
    "FINAL SUMMARY - "
    "TARGETED REPLICATION LAG"
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
# Save CSV
#
# Same schema and column order as run_all.py.
# ============================================================

os.makedirs(
    "results",
    exist_ok=True
)

output_file = os.path.join(
    "results",
    "targeted_ryw.csv"
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

    writer.writerow(
        result
    )


print(
    f"\nResults saved to: "
    f"{output_file}"
)