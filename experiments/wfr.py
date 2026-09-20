"""
WFR（Writes-Follow-Reads，写跟随读）实验

一、WFR 在验证什么？

    核心问题：

    我刚刚 READ 看到了某个版本，
    那么我接下来的 WRITE 是否建立在这个版本
    或者比它更新的版本之上？

    操作顺序：

        READ -> WRITE

    Writes-Follow-Reads 要求：

    同一个 Client 在读取某个数据之后，
    后续对该数据进行 WRITE 时，
    这个 WRITE 不能建立在比刚才 READ 更旧的状态上。


二、实验设计思路

    每一次 trial：

    1. 使用稳定配置初始化：

           version = 1
           based_on_version = 0

    2. 开启一个 MongoDB causally consistent session。

    3. 在该 session 中从 Secondary 执行 READ：

           READ -> Secondary

       记录：

           read_version

    4. 在同一个 session 中执行 WRITE：

           WRITE -> Primary

       写入：

           version = read_version + 1
           based_on_version = read_version

    5. 等待 WRITE 根据当前 Write Concern 返回。

    6. 从 Primary 读取最终状态，检查这个 WRITE
       是否建立在之前 READ 看到的版本或更新版本上。

    7. 判断：

           based_on_version >= read_version
               -> PASS

           based_on_version < read_version
               -> VIOLATION

           操作无法完成
               -> FAILED


    我们故意设计：

        Secondary READ -> Primary WRITE

    是为了让 READ 和 WRITE 有机会发生在具有不同数据状态
    的 replica 上，从而真正测试 Writes-Follow-Reads。


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

    READ 使用 local。

    Client 从 Secondary READ 时，
    可能看到这个 Secondary 当前自己的本地状态。

    接下来 WRITE 又只使用 w:1，
    只需要当前 Primary 确认即可返回。

    因此在故障、网络分区等情况下，
    MongoDB 不能保证后面的 WRITE 一定建立在
    前面 READ 所看到的状态之后。

    官方预测：
        WFR NOT GUARANTEED


C2:
    readConcern  = majority
    writeConcern = w:1

    READ 使用 majority。

    因此 Client 读取的是 majority-committed 的状态。

    在同一个 causally consistent session 中，
    MongoDB 会记录 Client 已经 READ 到的因果位置。

    后面的 WRITE 必须发生在这个 READ 之后，
    不能建立在比刚刚 READ 更早的状态上。

    因此可以保证 Writes-Follow-Reads。

    官方预测：
        WFR GUARANTEED


C3:
    readConcern  = local
    writeConcern = majority

    WRITE 使用 majority，
    所以后面的 WRITE 比较可靠。

    但是 WFR 的前半部分是：

        READ -> WRITE
        ↑
      这里很重要

    READ 使用的是 local。

    Client 从某个 Secondary 读取时，
    可能看到一个并没有被 majority 确认、
    甚至之后可能发生 rollback 的状态。

    即使后面的 WRITE 使用 majority，
    也不能弥补前面 READ 本身没有提供
    所要求的 causal consistency guarantee。

    因此不能保证 Writes-Follow-Reads。

    官方预测：
        WFR NOT GUARANTEED


C4:
    readConcern  = majority
    writeConcern = majority

    READ 使用 majority，
    WRITE 也使用 majority。

    两个操作又位于同一个
    causally consistent session 中。

    MongoDB 会知道：

        “这个 Client 已经 READ 到了某个状态，
         后面的 WRITE 必须发生在这个 READ 之后。”

    因此可以保证 Writes-Follow-Reads。

    官方预测：
        WFR GUARANTEED


五、最终预测总结

    C1: local    + w:1
        -> WFR NOT GUARANTEED

    C2: majority + w:1
        -> WFR GUARANTEED

    C3: local    + majority
        -> WFR NOT GUARANTEED

    C4: majority + majority
        -> WFR GUARANTEED


六、重要说明

    NOT GUARANTEED 不代表每次实验都会出现 VIOLATION。

    C1 和 C3 在正常运行情况下仍然很可能全部 PASS。

    特别是我们的三个 MongoDB 节点运行在同一台机器的
    Docker containers 中，节点之间通信和复制速度很快，
    因此很难在正常运行时观察到明显的 inconsistent state。

    Node failure 和 network partition 等场景
    更有可能暴露不同配置之间的差异。

    GUARANTEED 也不代表故障情况下操作一定能够立即完成。

    MongoDB 可能等待所需要的因果状态，
    或者操作可能因为无法满足要求而失败。

    因此实验中需要把：

        VIOLATION
        和
        FAILED

    分开统计。

    READ 和 WRITE 使用同一个 causally consistent session，
    从而与 MongoDB 官方 causal consistency guarantee
    的条件保持一致。
"""

import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one WFR trial
# ============================================================

def run_one_trial(
    client,
    setup_collection,
    read_collection,
    write_collection,
    observation_collection,
    config_name,
    trial_id
):
    """
    Run one Writes-Follow-Reads (WFR) trial.

    Setup:
        Prepare version = 1.

    Experiment:
        1. Start a causally consistent session.
        2. READ from a Secondary.
        3. Record the version observed by the READ.
        4. WRITE to the Primary using the SAME session.
        5. Observe the final state from the Primary.
        6. Check whether the WRITE followed the READ.

    Returns:
        "PASS"
        "VIOLATION"
        "FAILED"
    """

    document_id = f"wfr_{config_name}_{trial_id}"

    try:

        # ====================================================
        # SETUP PHASE
        # ====================================================
        #
        # Not part of the WFR test.
        # Prepare a stable starting state.
        #

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
        # CAUSALLY CONSISTENT SESSION
        # ====================================================

        with client.start_session(
            causal_consistency=True
        ) as session:

            # ------------------------------------------------
            # READ
            # ------------------------------------------------
            #
            # Deliberately read from a Secondary.
            #

            read_result = read_collection.find_one(
                {"_id": document_id},
                session=session
            )

            if read_result is None:
                return "FAILED"

            read_version = read_result["version"]

            # ------------------------------------------------
            # WRITE FOLLOWING THE READ
            # ------------------------------------------------
            #
            # The WRITE goes to the Primary.
            #
            # It uses the SAME causal session as the READ.
            #

            new_version = read_version + 1

            write_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "version": new_version,
                        "based_on_version": read_version
                    }
                },
                session=session
            )

            # ------------------------------------------------
            # FINAL OBSERVATION
            # ------------------------------------------------
            #
            # This READ is only used to inspect the final state.
            # It is not one of the READ -> WRITE operations
            # defining WFR.
            #

            final_result = observation_collection.find_one(
                {"_id": document_id},
                session=session
            )

            if final_result is None:
                return "FAILED"

            final_version = final_result["version"]
            based_on_version = final_result["based_on_version"]

            # ------------------------------------------------
            # Check Writes-Follow-Reads
            # ------------------------------------------------

            if (
                based_on_version >= read_version
                and final_version >= read_version
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
# Run complete WFR experiment
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
        # Used only to prepare the stable starting state.
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
        # READ COLLECTION
        # ====================================================
        #
        # Uses selected C1/C2/C3/C4 configuration.
        #
        # READ -> Secondary
        #

        read_collection = get_collection(
            client,
            config_name,
            read_from="secondary"
        )

        # ====================================================
        # WRITE COLLECTION
        # ====================================================
        #
        # Uses the SAME C1/C2/C3/C4 configuration.
        #
        # WRITE -> Primary
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
        # Final READ -> Primary.
        #
        # Only used to inspect the final result.
        #

        observation_collection = get_collection(
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
                read_collection,
                write_collection,
                observation_collection,
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
        "\n========== WFR RESULTS =========="
    )

    print(
        f"Configuration:      {config_name}"
    )

    print(
        "Session:            "
        "Causally Consistent"
    )

    print(
        "Operation path:     "
        "Secondary READ -> Primary WRITE"
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
        "================================="
    )


# ============================================================
# Command-line entry point
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:

        print(
            "Usage: "
            "python wfr.py "
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