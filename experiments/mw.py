"""
MW（Monotonic Writes，单调写）实验

一、MW 在验证什么？

    核心问题：

    同一个 Client 连续进行了两次 WRITE：

        WRITE 1 -> WRITE 2

    那么 WRITE 2 必须建立在 WRITE 1 已经完成的状态之后，
    不能出现后面的 WRITE 2 先发生，
    或者 WRITE 1 最后反过来覆盖 WRITE 2 的情况。

    可以简单理解成：

        我先写 version = 1
        再写 version = 2

    最终应该保持：

        version = 2

    而不能重新变回：

        version = 1


二、实验设计思路

    每一次 trial：

    1. 使用稳定配置初始化：

           version = 0
           client_seq = 0

    2. 开启一个 MongoDB causally consistent session。

    3. 在同一个 session 中执行第一次 WRITE：

           WRITE 1:
               version = 1
               client_seq = 1

    4. 等待 WRITE 1 根据当前 Write Concern 返回。

    5. 在同一个 session 中执行第二次 WRITE：

           WRITE 2:
               version = 2
               client_seq = 2

    6. 等待 WRITE 2 返回。

    7. 从 Primary 读取最终状态。

    8. 检查：

           version == 2
           AND
           client_seq == 2

               -> PASS

       否则：

               -> VIOLATION

       如果操作无法完成：

               -> FAILED


    两次 WRITE 使用同一个 causally consistent session，
    从而让 MongoDB 知道：

        WRITE 1 -> WRITE 2

    是同一个 Client 的连续操作。


三、输出指标

    - Total trials
    - Completed trials
    - Passes
    - Violations
    - Failed trials
    - Violation rate
    - Failure rate


四、四种配置及 MongoDB 官方预测

C1:
    readConcern  = local
    writeConcern = w:1

    两次 WRITE 都使用 w:1。

    也就是说，只要当前 Primary 接受 WRITE，
    就可以向 Client 返回成功，
    不需要等待多数节点确认。

    正常情况下，两次 WRITE 很可能仍然按照：

        WRITE 1 -> WRITE 2

    正确执行，所以实验可能全部 PASS。

    但是在 Primary failure、network partition 等情况下，
    w:1 的 WRITE 可能只存在于某一部分节点上，
    之后还可能发生 rollback。

    因此 MongoDB 不保证 Monotonic Writes。

    官方预测：
        MW NOT GUARANTEED


C2:
    readConcern  = majority
    writeConcern = w:1

    虽然 Read Concern 是 majority，
    但是 MW 真正检查的是：

        WRITE -> WRITE

    两次 WRITE 仍然都只使用 w:1。

    所以把 READ 调成 majority，
    并不能解决 WRITE 本身没有 majority acknowledgement
    的问题。

    因此 MongoDB 仍然不保证 Monotonic Writes。

    官方预测：
        MW NOT GUARANTEED


C3:
    readConcern  = local
    writeConcern = majority

    两次 WRITE 都使用 majority。

    WRITE 1 只有在多数节点确认之后，
    才会告诉 Client：

        “WRITE 1 成功了。”

    然后 Client 才执行 WRITE 2。

    因此 WRITE 2 是发生在已经被多数节点确认的
    WRITE 1 之后。

    即使 Read Concern 是 local，
    对 MW 来说关键仍然是两个 WRITE 的顺序。

    因此 MongoDB 可以保证 Monotonic Writes。

    官方预测：
        MW GUARANTEED


C4:
    readConcern  = majority
    writeConcern = majority

    两次 WRITE 都使用 majority。

    WRITE 1 等待多数节点确认后才返回，
    然后才执行 WRITE 2。

    两个 WRITE 又位于同一个
    causally consistent session 中。

    因此 MongoDB 可以保证：

        WRITE 1 -> WRITE 2

    的因果顺序。

    官方预测：
        MW GUARANTEED


五、最终预测总结

    C1: local    + w:1
        -> MW NOT GUARANTEED

    C2: majority + w:1
        -> MW NOT GUARANTEED

    C3: local    + majority
        -> MW GUARANTEED

    C4: majority + majority
        -> MW GUARANTEED


六、重要说明

    NOT GUARANTEED 不代表一定出现 VIOLATION。

    在正常运行情况下，
    C1 和 C2 很可能仍然全部 PASS。

    因为两个 WRITE：

        WRITE 1
        -> 等待返回
        -> WRITE 2

    通常都会由同一个 Primary 按顺序处理。

    w:1 和 majority 的差异更可能在：

        - Primary failure
        - Network partition
        - Rollback

    等情况下体现出来。

    因此 normal operation 中没有观察到 violation，
    并不代表 C1/C2 能够保证 Monotonic Writes。

    本实验中的两个 WRITE 使用同一个
    causally consistent session，
    从而与 MongoDB 官方 causal consistency
    guarantee 的条件保持一致。
"""

import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one MW trial
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
    Run one Monotonic-Writes (MW) trial.

    Setup:
        Prepare a stable initial state.

    Experiment:
        1. Start a causally consistent session.
        2. WRITE 1 with client_seq = 1.
        3. Wait for WRITE 1 to return.
        4. WRITE 2 with client_seq = 2 using the SAME session.
        5. Wait for WRITE 2 to return.
        6. Read the final state.
        7. Check whether WRITE 2 remains visible.

    Returns:
        "PASS"
        "VIOLATION"
        "FAILED"
    """

    document_id = f"mw_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================

        setup_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 0,
                    "client_seq": 0
                }
            },
            upsert=True
        )

        # ====================================================
        # CAUSALLY CONSISTENT SESSION
        # ====================================================

        with client.start_session(
            causal_consistency=True
        ) as session:

            # ------------------------------------------------
            # WRITE 1
            # ------------------------------------------------

            write_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "version": 1,
                        "client_seq": 1
                    }
                },
                session=session
            )

            # WRITE 1 has returned according to the selected
            # Write Concern.

            # ------------------------------------------------
            # WRITE 2
            # ------------------------------------------------

            write_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "version": 2,
                        "client_seq": 2
                    }
                },
                session=session
            )

            # WRITE 2 has returned.

            # ------------------------------------------------
            # FINAL READ
            # ------------------------------------------------
            #
            # This READ is only used to observe the final state.
            # It is not one of the operations defining MW.
            #

            result = read_collection.find_one(
                {"_id": document_id},
                session=session
            )

            if result is None:
                return "FAILED"

            final_version = result["version"]
            final_seq = result["client_seq"]

            # ------------------------------------------------
            # Check Monotonic Writes
            # ------------------------------------------------

            if (
                final_version == 2
                and final_seq == 2
            ):
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
        # Fixed majority + majority.
        # Used only to prepare the baseline.
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
        # Uses actual C1/C2/C3/C4 configuration.
        #

        write_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # OBSERVATION COLLECTION
        # ====================================================
        #
        # Final READ comes from Primary.
        #

        read_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # RUN N TRIALS
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
    # STATISTICS
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
    # PRINT RESULTS
    # ========================================================

    print(
        "\n========== MW RESULTS =========="
    )

    print(
        f"Configuration:      {config_name}"
    )

    print(
        "Session:            "
        "Causally Consistent"
    )

    print(
        "Write path:         "
        "W1 -> ACK -> W2 -> ACK"
    )

    print(
        "Final observation:  "
        "Primary"
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

    return {
        "consistency": "MW",
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
            "python mw.py "
            "<C1|C2|C3|C4> "
            "<num_trials>"
        )

        sys.exit(1)

    config_name = sys.argv[1].upper()

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