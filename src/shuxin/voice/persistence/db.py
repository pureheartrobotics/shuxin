from __future__ import annotations

from pathlib import Path


class PostgresDatabase:
    """Voice 模块的 Postgres 连接池和迁移入口。"""

    def __init__(
        self,
        database_url: str | None,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self.database_url = database_url or ""
        self.min_size = min_size
        self.max_size = max_size
        self.pool = None

    async def connect(self) -> None:
        """创建 asyncpg 连接池；没有 DATABASE_URL 时直接失败。"""
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for voice web server")
        import asyncpg

        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=self.min_size,
            max_size=self.max_size,
            command_timeout=30,
        )

    async def close(self) -> None:
        """关闭连接池。"""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def migrate(self) -> None:
        """执行幂等 SQL 迁移。"""
        if self.pool is None:
            raise RuntimeError("database pool is not connected")
        migrations_dir = Path(__file__).with_name("migrations")
        async with self.pool.acquire() as conn:
            for path in sorted(migrations_dir.glob("*.sql")):
                await conn.execute(path.read_text(encoding="utf-8"))
