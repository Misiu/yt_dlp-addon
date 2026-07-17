"""SQLite persistence with lightweight migrations."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import aiosqlite

from .models import ACTIVE_STATES, TERMINAL_STATES, Job, JobState

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_video_state ON jobs(video_id, state);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.execute("PRAGMA busy_timeout=5000")
        await self.connection.executescript(_MIGRATION_1)
        await self.connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")
        await self.connection.commit()

    def _connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not open")
        return self.connection

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    async def save(self, job: Job) -> None:
        await self.save_many([job])

    async def save_many(self, jobs: Iterable[Job]) -> None:
        values = [
            (
                job.id,
                job.video_id,
                job.state.value,
                job.created_at.isoformat(),
                job.finished_at.isoformat() if job.finished_at else None,
                job.model_dump_json(),
            )
            for job in jobs
        ]
        if not values:
            return
        async with self._lock:
            connection = self._connection()
            await connection.executemany(
                """
                INSERT INTO jobs(id, video_id, state, created_at, finished_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    video_id=excluded.video_id,
                    state=excluded.state,
                    created_at=excluded.created_at,
                    finished_at=excluded.finished_at,
                    payload=excluded.payload
                """,
                values,
            )
            await connection.commit()

    async def get(self, job_id: str) -> Job | None:
        cursor = await self._connection().execute(
            "SELECT payload FROM jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return Job.model_validate_json(row["payload"]) if row else None

    async def delete(self, job_id: str) -> bool:
        async with self._lock:
            connection = self._connection()
            cursor = await connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await connection.commit()
            return cursor.rowcount > 0

    async def list_by_states(
        self,
        states: Iterable[JobState],
        *,
        limit: int = 10_000,
        offset: int = 0,
        newest_first: bool = False,
    ) -> list[Job]:
        values = [state.value for state in states]
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        order = "DESC" if newest_first else "ASC"
        cursor = await self._connection().execute(
            f"SELECT payload FROM jobs WHERE state IN ({placeholders}) "  # noqa: S608
            f"ORDER BY created_at {order} LIMIT ? OFFSET ?",
            (*values, limit, offset),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [Job.model_validate_json(row["payload"]) for row in rows]

    async def count_by_states(self, states: Iterable[JobState]) -> int:
        values = [state.value for state in states]
        if not values:
            return 0
        placeholders = ",".join("?" for _ in values)
        cursor = await self._connection().execute(
            f"SELECT COUNT(*) AS count FROM jobs WHERE state IN ({placeholders})",  # noqa: S608
            values,
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        return int(row["count"])

    async def active_video_exists(self, video_id: str) -> bool:
        return bool(await self.active_video_ids([video_id]))

    async def active_video_ids(self, video_ids: Iterable[str]) -> set[str]:
        ids = list(video_ids)
        if not ids:
            return set()
        states = [JobState.QUEUED, *ACTIVE_STATES]
        id_placeholders = ",".join("?" for _ in ids)
        placeholders = ",".join("?" for _ in states)
        cursor = await self._connection().execute(
            f"SELECT video_id FROM jobs WHERE video_id IN ({id_placeholders}) "  # noqa: S608
            f"AND state IN ({placeholders})",
            (*ids, *(state.value for state in states)),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {str(row["video_id"]) for row in rows}

    async def recover_interrupted(self) -> int:
        jobs = await self.list_by_states(ACTIVE_STATES)
        for job in jobs:
            job.state = JobState.QUEUED
            job.progress = 0
            job.downloaded_bytes = None
            job.total_bytes = None
            job.speed_bytes_per_second = None
            job.eta_seconds = None
            job.error_code = "restart_requeued"
            job.error_message = "The app restarted while this job was active; it was requeued."
            await self.save(job)
        return len(jobs)

    async def trim_history(self, limit: int) -> None:
        terminal = [state.value for state in TERMINAL_STATES]
        placeholders = ",".join("?" for _ in terminal)
        async with self._lock:
            connection = self._connection()
            if limit == 0:
                await connection.execute(
                    f"DELETE FROM jobs WHERE state IN ({placeholders})",  # noqa: S608
                    terminal,
                )
            else:
                await connection.execute(
                    f"""DELETE FROM jobs WHERE id IN (
                        SELECT id FROM jobs WHERE state IN ({placeholders})
                        ORDER BY COALESCE(finished_at, created_at) DESC LIMIT -1 OFFSET ?
                    )""",  # noqa: S608
                    (*terminal, limit),
                )
            await connection.commit()

    async def clear_history(self) -> int:
        states = [state.value for state in TERMINAL_STATES]
        placeholders = ",".join("?" for _ in states)
        async with self._lock:
            connection = self._connection()
            cursor = await connection.execute(
                f"DELETE FROM jobs WHERE state IN ({placeholders})",  # noqa: S608
                states,
            )
            await connection.commit()
            return cursor.rowcount
