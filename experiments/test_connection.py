from common import create_client, get_collection


client = create_client()

try:
    # 1. Test replica-set connection
    client.admin.command("ping")
    print("MongoDB connection successful!")

    # 2. Use configuration C1
    collection = get_collection(client, "C1")

    # 3. Write
    collection.update_one(
        {"_id": "connection_test"},
        {
            "$set": {
                "value": 100
            }
        },
        upsert=True
    )

    # 4. Read
    result = collection.find_one(
        {"_id": "connection_test"}
    )

    print("Read result:")
    print(result)

finally:
    client.close()