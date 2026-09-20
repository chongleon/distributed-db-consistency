# Client-Centric Consistency Experiments with MongoDB

This project experimentally evaluates client-centric consistency guarantees in a MongoDB replica set under different consistency configurations and failure scenarios.

## Overview

We evaluate four client-centric consistency models:

- **RYW** — Read-Your-Writes
- **MR** — Monotonic Reads
- **MW** — Monotonic Writes
- **WFR** — Writes-Follow-Reads

Each model is tested under four MongoDB configurations:

| Config | Read Concern | Write Concern |
|--------|--------------|---------------|
| C1 | `local` | `w:1` |
| C2 | `majority` | `w:1` |
| C3 | `local` | `majority` |
| C4 | `majority` | `majority` |

The main experiments are evaluated under three scenarios:

1. Normal operation
2. Node failure
3. Network partition

This gives a total of:

```text
4 consistency models × 4 configurations × 3 scenarios = 48 experiments
```

## Project Structure

```text
distributed-db-consistency/
├── experiments/
│   ├── common.py
│   ├── mr.py
│   ├── mw.py
│   ├── ryw.py
│   ├── wfr.py
│   ├── run_all.py
│   ├── targeted_ryw.py
│   └── results/
│       ├── normal.csv
│       ├── node_failure.csv
│       ├── network_partition.csv
│       └── targeted_ryw.png
├── scripts/
│   ├── normal.bat
│   ├── node_failure.bat
│   └── network_partition.bat
├── docker-compose.yml
├── init-replica.js
└── README.md
```

## Requirements

- Docker Desktop
- Python 3
- PyMongo

Install the Python dependency with:

```powershell
pip install pymongo
```

## Setup

Start the three MongoDB containers:

```powershell
docker compose up -d
```

Initialize the replica set:

```powershell
docker exec -it mongo1 mongosh
```

Then the replica set can also be initialized manually:

```javascript
rs.initiate({
    _id: "rs0",
    members: [
        { _id: 0, host: "mongo1:27017", priority: 2 },
        { _id: 1, host: "mongo2:27018", priority: 1 },
        { _id: 2, host: "mongo3:27019", priority: 1 }
    ]
})
```

Verify the replica-set state with:

```javascript
rs.status()
```

The expected normal state is:

```text
mongo1: PRIMARY
mongo2: SECONDARY
mongo3: SECONDARY
```

## Running the Main Experiments

From the `experiments` directory:

```powershell
cd experiments
python run_all.py 100
```

The argument specifies the number of trials per experiment.

`run_all.py` automatically runs all four consistency models under all four configurations for the three scenarios.

Results are saved to:

```text
results/normal.csv
results/node_failure.csv
results/network_partition.csv
```

After all experiments finish, the script attempts to restore the MongoDB cluster to the normal configuration automatically.

## Running an Individual Experiment

An individual consistency experiment can also be run separately:

```powershell
python ryw.py C1 100
python mr.py C2 100
python mw.py C3 100
python wfr.py C4 100
```

The arguments are:

```text
python <experiment>.py <configuration> <number_of_trials>
```

where the configuration is one of `C1`, `C2`, `C3`, or `C4`.

## Additional Targeted RYW Experiment

In addition to the main experiments, we include a small targeted replication-lag experiment for Read-Your-Writes (RYW) under C1 (`readConcern = local`, `writeConcern = w:1`).

The purpose is to create a controlled stale-secondary condition and test whether an RYW violation can be observed when the read is explicitly directed to a delayed Secondary.

### Configuration

The experiment uses `mongo3` as the deliberately delayed Secondary.

Connect to the Primary:

```powershell
docker exec -it mongo1 mongosh
```

Configure `mongo3` with a 5-second replication delay:

```javascript
cfg = rs.conf()
cfg.members[2].secondaryDelaySecs = 5
cfg.members[2].priority = 0
rs.reconfig(cfg)
```

Verify the configuration:

```javascript
rs.conf().members[2]
```

The relevant settings should be:

```text
host: 'mongo3:27019'
priority: 0
secondaryDelaySecs: 5
```

### Run the Experiment

From the `experiments` directory:

```powershell
python targeted_ryw.py
```

The experiment performs 10 trials using C1 and immediately reads from the deliberately delayed `mongo3` after each new write.

### Restore the Replica Set

After the experiment, restore `mongo3` to its original configuration:

```javascript
cfg = rs.conf()
cfg.members[2].secondaryDelaySecs = 0
cfg.members[2].priority = 1
rs.reconfig(cfg)
```

The normal replica-set configuration is:

```text
mongo1: priority 2
mongo2: priority 1
mongo3: priority 1
secondaryDelaySecs: 0
```

Finally, verify the replica set:

```javascript
rs.status()
```

The expected state is:

```text
mongo1: PRIMARY
mongo2: SECONDARY
mongo3: SECONDARY
```

## Results

The main experimental results are stored as CSV files in `experiments/results/`.

Each experiment records:

- passes
- violations
- failed trials
- violation rate
- failure rate

A **PASS** means the tested execution satisfied the client-centric consistency property, while a **VIOLATION** means an inconsistent execution was observed. A **FAILED** trial means the operation could not complete under the tested scenario.

Note that **NOT GUARANTEED does not imply that every execution will produce a violation**. In a local three-node Docker environment, replication can be fast enough that configurations without a formal guarantee may still pass many or all trials.