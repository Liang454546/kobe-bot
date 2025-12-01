import copy
import os
from datetime import datetime
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB", "kobe_bot")

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None

DEFAULT_USER: Dict[str, Any] = {
    "wallet": 0,
    "bank": 0,
    "items": {},
    "joined": False,
    "xp": 0,
    "level": 1,
    "loan": {"balance": 0, "next_due": None},
    "stats": {"wins": 0, "losses": 0, "work": 0},
    "cooldowns": {},
    "created_at": None,
    "updated_at": None,
}


async def init_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db:
        return _db
    if not MONGO_URI:
        raise RuntimeError("環境變數 MONGO_URI 未設定，無法連線 MongoDB。")
    _client = AsyncIOMotorClient(MONGO_URI)
    _db = _client[DB_NAME]
    await _db.command("ping")
    return _db


async def get_db() -> AsyncIOMotorDatabase:
    if not _db:
        return await init_db()
    return _db


async def close_db() -> None:
    global _client, _db
    if _client:
        _client.close()
    _client = None
    _db = None


async def get_user(user_id: int) -> Dict[str, Any]:
    db = await get_db()
    collection = db["users"]
    _id = str(user_id)
    doc = await collection.find_one({"_id": _id})
    if doc:
        return doc

    now = datetime.utcnow()
    new_doc = copy.deepcopy(DEFAULT_USER)
    new_doc["_id"] = _id
    new_doc["created_at"] = now
    new_doc["updated_at"] = now
    await collection.insert_one(new_doc)
    return new_doc


async def update_user(user_id: int, update: Dict[str, Any]) -> Dict[str, Any]:
    db = await get_db()
    collection = db["users"]
    update.setdefault("$set", {})
    update["$set"]["updated_at"] = datetime.utcnow()
    await collection.update_one({"_id": str(user_id)}, update, upsert=True)
    return await get_user(user_id)


async def increment_balances(
    user_id: int, *, wallet_delta: int = 0, bank_delta: int = 0
) -> Dict[str, Any]:
    inc: Dict[str, Any] = {}
    if wallet_delta:
        inc["wallet"] = wallet_delta
    if bank_delta:
        inc["bank"] = bank_delta

    update: Dict[str, Any] = {}
    if inc:
        update["$inc"] = inc
    return await update_user(user_id, update)


async def set_cooldown(user_id: int, name: str, when: datetime) -> None:
    await update_user(user_id, {"$set": {f"cooldowns.{name}": when}})


async def get_cooldown(user_id: int, name: str) -> Optional[datetime]:
    user = await get_user(user_id)
    value = user.get("cooldowns", {}).get(name)
    if isinstance(value, datetime):
        return value
    return None


async def log_transaction(
    user_id: int,
    *,
    kind: str,
    amount: int,
    balance_after: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    db = await get_db()
    await db["transactions"].insert_one(
        {
            "user_id": str(user_id),
            "kind": kind,
            "amount": amount,
            "balance_after": balance_after,
            "meta": meta or {},
            "created_at": datetime.utcnow(),
        }
    )

