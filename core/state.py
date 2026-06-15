import asyncio

MAX_CONCURRENT_TASKS = 80
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

user_tasks = {}
