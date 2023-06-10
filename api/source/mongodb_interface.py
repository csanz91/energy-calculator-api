from pymongo import MongoClient
from bson.objectid import ObjectId

client = MongoClient("mongodb")
db = client["data"]

collection = db['energy_data']


def initIndex():
    collection.create_index("createdAt", expireAfterSeconds=3600*24*30*2) # 2 months retention


def insertEnergyData(energy_data) -> str:
    result = collection.insert_one(energy_data)
    del energy_data["_id"]
    return str(result.inserted_id)

def getEnergyData(db_id):
    result = collection.find_one({"_id": ObjectId(db_id)})
    if not result:
        return {}
    del result["_id"]
    result["id"] = db_id
    return result