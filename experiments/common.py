from pymongo import MongoClient
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import Primary, Secondary

# ============================================================
# MongoDB Replica Set
# ============================================================

MONGO_URI = (
    "mongodb://mongo1:27017,"
    "mongo2:27018,"
    "mongo3:27019/"
    "?replicaSet=rs0"
)


# ============================================================
# MongoDB consistency configurations
# ============================================================

CONFIGS = {
    "C1": {
        "read_concern": "local",
        "write_concern": 1,
    },

    "C2": {
        "read_concern": "majority",
        "write_concern": 1,
    },

    "C3": {
        "read_concern": "local",
        "write_concern": "majority",
    },

    "C4": {
        "read_concern": "majority",
        "write_concern": "majority",
    },
}


# ============================================================
# Create MongoDB client
# ============================================================

def create_client():
    return MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000
    )


# ============================================================
# Get collection with a selected consistency configuration
# ============================================================

def get_collection(client, config_name, read_from="primary"):
    """
    Return a collection using the selected RC/WC configuration.

    read_from:
        "primary"   -> reads are served by the Primary
        "secondary" -> reads are served by a Secondary
    """

    if config_name not in CONFIGS:
        raise ValueError(f"Unknown configuration: {config_name}")

    config = CONFIGS[config_name]

    if read_from == "primary":
        read_preference = Primary()

    elif read_from == "secondary":
        read_preference = Secondary()

    else:
        raise ValueError(
            f"Unknown read preference: {read_from}"
        )

    db = client["consistency_test"]

    collection = db.get_collection(
        "items",
        read_concern=ReadConcern(
            config["read_concern"]
        ),
        write_concern=WriteConcern(
            w=config["write_concern"]
        ),
        read_preference=read_preference,
    )

    return collection