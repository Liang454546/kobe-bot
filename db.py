import os
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

DB_FILE = os.getenv("DB_FILE", "data.json")
_lock = asyncio.Lock()

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


def _read_file() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return {"users": {}, "transactions": []}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "transactions": []}


def _write_file(data: Dict[str, Any]) -> None:
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=default, ensure_ascii=False)


async def get_user(user_id: int) -> Dict[str, Any]:
    async with _lock:
        data = _read_file()
        users = data.setdefault("users", {})
        sid = str(user_id)
        user = users.get(sid)
        if user:
            return user
        new_user = DEFAULT_USER.copy()
        new_user.update({"_id": sid, "created_at": datetime.utcnow().isoformat(), "updated_at": datetime.utcnow().isoformat()})
        users[sid] = new_user
        _write_file(data)
        return new_user


async def update_user(user_id: int, update: Dict[str, Any]) -> Dict[str, Any]:
    async with _lock:
        data = _read_file()
        users = data.setdefault("users", {})
        sid = str(user_id)
        user = users.get(sid)
        if not user:
            user = await get_user(user_id)

        update.setdefault("$set", {})
        update["$set"]["updated_at"] = datetime.utcnow().isoformat()

        if "$set" in update:
            for k, v in update["$set"].items():
                if "." in k:
                    p, c = k.split(".", 1)
                    if p not in user:
                        user[p] = {}
                    user[p][c] = v
                else:
                    user[k] = v

        if "$inc" in update:
            for k, v in update["$inc"].items():
                user[k] = user.get(k, 0) + v

        users[sid] = user
        _write_file(data)
        return user


async def get_all_users() -> Dict[str, Any]:
    async with _lock:
        data = _read_file()
        return data.get("users", {}).copy()


async def increment_balances(user_id: int, *, wallet_delta: int = 0, bank_delta: int = 0) -> Dict[str, Any]:
    inc: Dict[str, Any] = {}
    if wallet_delta:
        inc["wallet"] = wallet_delta
    if bank_delta:
        inc["bank"] = bank_delta
    if inc:
        return await update_user(user_id, {"$inc": inc})
    return await get_user(user_id)


async def set_cooldown(user_id: int, name: str, when: datetime) -> None:
    await update_user(user_id, {"$set": {f"cooldowns.{name}": when.isoformat()}})


async def get_cooldown(user_id: int, name: str) -> Optional[datetime]:
    user = await get_user(user_id)
    raw = user.get("cooldowns", {}).get(name)
    if raw and isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None
    return None


async def log_transaction(user_id: int, *, kind: str, amount: int, balance_after: Optional[int] = None, meta: Optional[Dict[str, Any]] = None) -> None:
    async with _lock:
        data = _read_file()
        txs = data.setdefault("transactions", [])
        tx = {
            "user_id": str(user_id),
            "kind": kind,
            "amount": amount,
            "balance_after": balance_after,
            "meta": meta or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        txs.append(tx)
        _write_file(data)
