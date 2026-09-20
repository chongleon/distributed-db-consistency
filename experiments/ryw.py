"""
RYW(Read-Your-Writes)实验
here 加入了 causally consistent session 帮助MongoDB保证操作有逻辑上的先后顺序
一、RYW 在验证什么？

    核心问题：
    我 WRITE 了什么，我之后 READ 的时候能不能看到它？

    操作顺序：

        WRITE -> READ

    Read-Your-Writes 要求：
    同一个 Client 成功写入某个值之后，后续读取同一个数据时，
    必须能够看到自己刚刚写入的值，或者比它更新的值。


二、实验设计思路

    每一次 trial:

    1. 使用稳定配置初始化：
           version = 0

    2. 开启一个 MongoDB causally consistent session。

    3. 在该 session 中向 Primary 写入：
           version = 1

    4. 等待 WRITE 根据当前 Write Concern 返回成功。

    5. 在同一个 session 中，从 Secondary 读取该 document。

    6. 比较：

           read_version >= written_version
               -> PASS

           read_version < written_version
               -> VIOLATION

           操作无法完成
               -> FAILED

    (WRITE 和 READ 使用同一个 causally consistent session,
    从而使实验条件与 MongoDB 官方关于 causal consistency
    的 Read-Your-Writes guarantee 相对应。)


三、输出指标

    - Total trials
    - Completed trials
    - Passes
    - Violations
    - Failed trials
    - Violation rate
    - Failure rate


四、四种配置及预测

C1:
    readConcern  = local
    writeConcern = w:1

    写操作只需要 Primary 确认就可以返回成功，
    不需要等待多数副本确认。

    因此，当 WRITE 返回时,secondary可能还没有同步
    所以用local的标准有可能读到 Secondary 上还没更新的旧数据
    
    官方预测：
        RYW NOT GUARANTEED


C2:
    readConcern  = majority
    writeConcern = w:1

    READ 使用 majority,但 WRITE 仍然只要求 Primary 确认。

    因此 WRITE 返回成功时，它并不一定已经被 majority 确认。
    所以仍然不能保证一定能读到自己刚刚写的数据。

    官方预测：
        RYW NOT GUARANTEED


C3:
    readConcern  = local
    writeConcern = majority

    WRITE 会等待 majority acknowledgement,
    因此写入端比 C1/C2 更强。

    但是 READ 使用 local,可能还是读到未更新数据的secondary

    官方预测：
        RYW NOT GUARANTEED


C4:
    readConcern  = majority
    writeConcern = majority

    WRITE 等待 majority acknowledgement
    READ 使用 majority read concern。

    在 MongoDB causally consistent client session 中，
    MongoDB 官方说明该组合能够提供 Read-Your-Writes guarantee。

    官方预测：
        RYW GUARANTEED


五、重要说明

    NOT GUARANTEED 不代表每一次实验都会出现 VIOLATION。

    C1/C2/C3 在正常运行时仍然可能全部 PASS
    只是 MongoDB 不保证它们在所有情况下都满足 RYW。

    Node failure、replication lag、network partition 等场景
    更有可能暴露不同配置之间的区别。

    C4 的预测则是在 MongoDB 官方规定的 causally consistent
    session 条件下提供 RYW guarantee。
"""

import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one RYW trial
# ============================================================

def run_one_trial(
    client,
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
        1. Start a causally consistent session.
        2. WRITE version = 1 to the Primary.
        3. Wait for the WRITE acknowledgement.
        4. READ the same document from a Secondary
           using the SAME session.
        5. Check whether READ observes version >= 1.

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
        # Prepare a stable starting state:
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
        # START CAUSALLY CONSISTENT SESSION
        # ====================================================
        #
        # WRITE and READ below belong to the SAME client
        # session.
        #
        # causal_consistency=True allows MongoDB to preserve
        # causal relationships between operations in this
        # session.
        #

        with client.start_session(
            causal_consistency=True
        ) as session:

            # ================================================
            # EXPERIMENT PHASE
            # ================================================

            # -----------------------------------------------
            # WRITE
            # -----------------------------------------------
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
                },
                session=session
            )

            # At this point the WRITE has returned according
            # to the selected Write Concern.
            #
            # The session remembers the causal position of
            # this operation.

            # -----------------------------------------------
            # READ
            # -----------------------------------------------
            #
            # Read Preference = Secondary.
            #
            # IMPORTANT:
            # The READ uses the SAME session as the WRITE.
            #
            # Therefore MongoDB can preserve the causal
            # relationship:
            #
            # WRITE -> READ
            #

            result = read_collection.find_one(
                {"_id": document_id},
                session=session
            )

            if result is None:
                return "FAILED"

            read_version = result["version"]

            # -----------------------------------------------
            # Check Read-Your-Writes
            # -----------------------------------------------

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
        # This collection is ONLY used to prepare version = 0.
        # It is not part of the actual RYW test.
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
        # Uses selected C1/C2/C3/C4 Read/Write Concern.
        #
        # Write operations go to the Primary.
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
        # Uses the SAME C1/C2/C3/C4 Read/Write Concern.
        #
        # Read Preference = Secondary.
        #
        # This deliberately makes the experiment sensitive
        # to replication lag and replica consistency.
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
                client,
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
    # Only successfully completed READ/WRITE trials are used
    # in the denominator.
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
        "Session:            "
        "Causally Consistent"
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

    return {
        "consistency": "RYW",
        "config": config_name,
        "total_trials": total_trials,
        "completed_trials": completed_trials,
        "passes": pass_count,
        "violations": violation_count,
        "failed": failed_count,
        "violation_rate": violation_rate,
        "failure_rate": failure_rate
    }    


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

    if config_name not in {
        "C1",
        "C2",
        "C3",
        "C4"
    }:

        print(
            "Invalid configuration. "
            "Choose C1, C2, C3, or C4."
        )

        sys.exit(1)

    try:

        num_trials = int(
            sys.argv[2]
        )

        if num_trials <= 0:
            raise ValueError

    except ValueError:

        print(
            "num_trials must be "
            "a positive integer."
        )

        sys.exit(1)

    run_experiment(
        config_name,
        num_trials
    )