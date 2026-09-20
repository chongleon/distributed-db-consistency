"""
MR（Monotonic Reads，单调读）实验
我们大部分pass的原因可能是因为 设置的节点数量比较少，在同台机器的docker容器里跑mongoDB 节点之间的通讯很快
很少出现secondary没有同步更新的情况
一、MR 在验证什么？

    核心问题：

    我第一次 READ 看到了什么，
    我第二次 READ 会不会反而看到更旧的数据？

    操作顺序：

        READ 1 -> READ 2

    Monotonic Reads 要求：

    同一个 Client 第一次读取某个数据之后，
    后续再次读取这个数据时，
    只能看到相同或者更新的版本，
    不能看到比第一次 READ 更旧的版本。


二、实验设计思路

    每一次 trial：

    1. 使用稳定配置初始化：

           version = 1

    2. 将数据更新为：

           version = 2

    3. 开启一个 MongoDB causally consistent session。

    4. 在该 session 中进行第一次 READ：

           READ 1 -> Primary

       Primary 更有机会读到最新的 version = 2。

    5. 在同一个 session 中进行第二次 READ：

           READ 2 -> Secondary

       Secondary 可能因为复制延迟而比 Primary 落后。

    6. 比较：

           second_version >= first_version
               -> PASS

           second_version < first_version
               -> VIOLATION

           操作无法完成
               -> FAILED


    我们故意设计：

        Primary READ -> Secondary READ

    就是为了让第二次 READ 有机会访问一个比第一次 READ
    更落后的 replica，从而测试 Monotonic Reads。


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

    两次 READ 使用 local。

    第一次从 Primary 读到比较新的数据之后，
    第二次去 Secondary 读取时，
    Secondary 可能还比较落后。

    local 允许 Secondary 返回自己当前看到的数据，
    因此第二次 READ 有可能比第一次 READ 更旧。

    例如：

        READ 1 -> version = 2
        READ 2 -> version = 1

    这样就发生了 Monotonic Reads violation。

    官方预测：
        MR NOT GUARANTEED


C2:
    readConcern  = majority
    writeConcern = w:1

    两次 READ 都使用 majority。

    第一次 READ 已经看到某个 majority-committed 状态之后，
    在同一个 causally consistent session 中，
    MongoDB 会记录这个 Client 已经看到的因果位置。

    第二次即使去另一个 Secondary 读取，
    也不能直接返回一个比第一次 READ 更早的状态。

    如果 Secondary 还没有追上，
    READ 可能需要等待，而不是直接返回旧数据。

    因此可以保证 Monotonic Reads。

    官方预测：
        MR GUARANTEED


C3:
    readConcern  = local
    writeConcern = majority

    WRITE 使用 majority，
    所以 version = 2 的写入比较可靠。

    但是 MR 真正检查的是：

        READ -> READ

    而这里两个 READ 仍然使用 local。

    第一次从 Primary 读取之后，
    第二次从 Secondary 读取时，
    即使majority已经确认write了 
    但read用的是local 
    还是可能读到那些少数没有更新同步的secondary 
    所以才not guaranteed

    官方预测：
        MR NOT GUARANTEED


C4:
    readConcern  = majority
    writeConcern = majority

    READ 使用 majority，
    WRITE 也使用 majority。

    两次 READ 又位于同一个
    causally consistent session 中。

    第一次 READ 已经看到某个状态之后，
    MongoDB 会保证后面的 READ 不会返回
    比第一次 READ 更早的状态。

    因此可以保证 Monotonic Reads。

    官方预测：
        MR GUARANTEED


五、最终预测总结

    C1: local    + w:1
        -> MR NOT GUARANTEED

    C2: majority + w:1
        -> MR GUARANTEED

    C3: local    + majority
        -> MR NOT GUARANTEED

    C4: majority + majority
        -> MR GUARANTEED


六、重要说明

    NOT GUARANTEED 不代表每一次实验都会出现 VIOLATION。

    C1 和 C3 在正常运行时仍然可能全部 PASS，
    例如 Secondary 同步速度很快，
    第二次 READ 时已经追上 Primary。

    GUARANTEED 也不代表故障情况下 READ 一定马上成功。

    在某些情况下 MongoDB 可能等待所需要的数据状态，
    或者操作因为节点故障、网络分区等原因无法完成。

    因此实验中需要把：

        VIOLATION
        和
        FAILED

    分开统计。

    本实验中的两个 READ 使用同一个
    causally consistent session，
    从而与 MongoDB 官方 causal consistency
    guarantee 的实验条件保持一致。
"""

import sys

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from common import create_client, get_collection


# ============================================================
# Run one MR trial
# ============================================================

def run_one_trial(
    client,
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
        2. Start a causally consistent session.
        3. READ 1 from the Primary.
        4. READ 2 from a Secondary using the SAME session.
        5. Check whether READ 2 is at least as new as READ 1.

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
        #
        # This is not part of the MR check.
        #
        # Prepare a stable starting state:
        #
        # version = 1
        #

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
        # CREATE A NEWER VERSION
        # ====================================================
        #
        # Uses the selected C1/C2/C3/C4 configuration.
        #
        # This update creates a newer state so that Primary
        # and Secondary may temporarily observe different
        # versions.
        #

        update_collection.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "version": 2
                }
            }
        )

        # ====================================================
        # CAUSALLY CONSISTENT SESSION
        # ====================================================
        #
        # Both READ operations belong to the SAME client
        # session.
        #

        with client.start_session(
            causal_consistency=True
        ) as session:

            # ------------------------------------------------
            # FIRST READ
            # ------------------------------------------------
            #
            # Read from Primary.
            #

            first_result = primary_read_collection.find_one(
                {"_id": document_id},
                session=session
            )

            if first_result is None:
                return "FAILED"

            first_version = first_result["version"]

            # ------------------------------------------------
            # SECOND READ
            # ------------------------------------------------
            #
            # Read from Secondary using the SAME session.
            #
            # This deliberately tests whether the client can
            # move backwards to an older version.
            #

            second_result = secondary_read_collection.find_one(
                {"_id": document_id},
                session=session
            )

            if second_result is None:
                return "FAILED"

            second_version = second_result["version"]

            # ------------------------------------------------
            # Check Monotonic Reads
            # ------------------------------------------------

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
        # STABLE SETUP COLLECTION
        # ====================================================
        #
        # Fixed majority + majority.
        #
        # Used only to prepare version = 1.
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
        # UPDATE COLLECTION
        # ====================================================
        #
        # Uses tested C1/C2/C3/C4 configuration.
        #

        update_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # FIRST READ -> PRIMARY
        # ====================================================

        primary_read_collection = get_collection(
            client,
            config_name,
            read_from="primary"
        )

        # ====================================================
        # SECOND READ -> SECONDARY
        # ====================================================

        secondary_read_collection = get_collection(
            client,
            config_name,
            read_from="secondary"
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
    # STATISTICS
    # ========================================================

    total_trials = num_trials

    completed_trials = (
        pass_count
        + violation_count
    )

    # --------------------------------------------------------
    # Violation rate
    # --------------------------------------------------------

    if completed_trials > 0:

        violation_rate = (
            violation_count
            / completed_trials
            * 100
        )

    else:

        violation_rate = 0.0

    # --------------------------------------------------------
    # Failure rate
    # --------------------------------------------------------

    failure_rate = (
        failed_count
        / total_trials
        * 100
    )

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print(
        "\n========== MR RESULTS =========="
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