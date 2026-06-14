import os
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.mongo_uri = os.getenv("MONGO_URI")
        self.client = None
        self.db = None
        self.users = None
        self.settings = None
        self.use_memory = True

        # In-memory fallback
        # Schema: user_id -> {"is_blocked": bool, "is_approved": bool, "usage_count": int, "last_reset_date": "YYYY-MM-DD"}
        self.memory_db = {}

        # Default global settings
        self.default_settings = {
            "daily_limit": 10,
            "max_file_size_bytes": 2 * 1024 * 1024 * 1024, # 2 GB
            "min_file_size_bytes": 0
        }
        self.memory_settings = self.default_settings.copy()

        if self.mongo_uri:
            try:
                self.client = AsyncIOMotorClient(self.mongo_uri)
                self.db = self.client.terabox_bot
                self.users = self.db.users
                self.settings = self.db.settings
                self.use_memory = False
                logger.info("MongoDB connected successfully.")
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB: {e}. Falling back to in-memory database.")
                self.use_memory = True
        else:
            logger.info("MONGO_URI not set. Using in-memory database.")

    async def get_user(self, user_id):
        if self.use_memory:
            return self.memory_db.get(user_id)
        else:
            return await self.users.find_one({"user_id": user_id})

    async def add_user(self, user_id):
        user = await self.get_user(user_id)
        if not user:
            today = datetime.date.today().isoformat()
            new_user = {
                "user_id": user_id,
                "is_blocked": False,
                "is_approved": False,
                "usage_count": 0,
                "last_reset_date": today
            }
            if self.use_memory:
                self.memory_db[user_id] = new_user
            else:
                await self.users.insert_one(new_user)
            return new_user
        return user

    async def block_user(self, user_id):
        await self.add_user(user_id)
        if self.use_memory:
            self.memory_db[user_id]["is_blocked"] = True
        else:
            await self.users.update_one({"user_id": user_id}, {"$set": {"is_blocked": True}})

    async def unblock_user(self, user_id):
        await self.add_user(user_id)
        if self.use_memory:
            self.memory_db[user_id]["is_blocked"] = False
        else:
            await self.users.update_one({"user_id": user_id}, {"$set": {"is_blocked": False}})

    async def approve_user(self, user_id):
        await self.add_user(user_id)
        if self.use_memory:
            self.memory_db[user_id]["is_approved"] = True
        else:
            await self.users.update_one({"user_id": user_id}, {"$set": {"is_approved": True}})

    async def disapprove_user(self, user_id):
        await self.add_user(user_id)
        if self.use_memory:
            self.memory_db[user_id]["is_approved"] = False
        else:
            await self.users.update_one({"user_id": user_id}, {"$set": {"is_approved": False}})

    async def get_all_users(self):
        if self.use_memory:
            return list(self.memory_db.values())
        else:
            return await self.users.find().to_list(length=None)

    async def get_settings(self):
        if self.use_memory:
            return self.memory_settings
        else:
            settings = await self.settings.find_one({"_id": "global_settings"})
            if not settings:
                await self.settings.insert_one({"_id": "global_settings", **self.default_settings})
                return self.default_settings
            return settings

    async def update_settings(self, key, value):
        if self.use_memory:
            self.memory_settings[key] = value
        else:
            await self.settings.update_one(
                {"_id": "global_settings"},
                {"$set": {key: value}},
                upsert=True
            )

    async def check_and_update_limit(self, user_id):
        user = await self.get_user(user_id)
        if not user:
            user = await self.add_user(user_id)

        if user.get("is_approved"):
            return True

        today = datetime.date.today().isoformat()
        last_reset = user.get("last_reset_date")
        usage_count = user.get("usage_count", 0)

        if last_reset != today:
            usage_count = 0
            last_reset = today

        settings = await self.get_settings()
        daily_limit = settings.get("daily_limit", self.default_settings["daily_limit"])

        if usage_count >= daily_limit:
            return False

        usage_count += 1

        if self.use_memory:
            self.memory_db[user_id]["usage_count"] = usage_count
            self.memory_db[user_id]["last_reset_date"] = last_reset
        else:
            await self.users.update_one(
                {"user_id": user_id},
                {"$set": {"usage_count": usage_count, "last_reset_date": last_reset}}
            )

        return True

    async def check_file_size_limit(self, user_id, size_in_bytes):
        user = await self.get_user(user_id)
        if not user:
            user = await self.add_user(user_id)

        if user.get("is_approved"):
            return True, ""

        settings = await self.get_settings()
        max_size = settings.get("max_file_size_bytes", self.default_settings["max_file_size_bytes"])
        min_size = settings.get("min_file_size_bytes", self.default_settings["min_file_size_bytes"])

        if size_in_bytes > max_size:
            return False, f"exceeds maximum allowed size of {max_size / (1024*1024):.0f} MB"

        if size_in_bytes < min_size:
            return False, f"is smaller than minimum allowed size of {min_size / (1024*1024):.0f} MB"

        return True, ""

db = Database()
