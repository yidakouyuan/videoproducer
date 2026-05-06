"""
视频数据统计 SQLite 数据库层。

两张表：
  videos      — 视频档案（platform + title + publish_time 唯一标识）
  video_stats — 指标快照（每次写入新增一条，保留历史）

video_id 由 sha256(platform::title::publish_time)[:16] 自动生成，调用方无需传。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB_PATH = "C:/Users/Administrator/AppData/Local/Temp/openclaw/video_stats.db"

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db_path = os.environ.get("STATS_DB_PATH", _DEFAULT_DB_PATH)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id     TEXT PRIMARY KEY,
            platform     TEXT NOT NULL,
            title        TEXT NOT NULL,
            publish_time TEXT NOT NULL,
            duration_sec REAL,
            created_at   TEXT NOT NULL,
            UNIQUE(platform, title, publish_time)
        );

        CREATE TABLE IF NOT EXISTS video_stats (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id          TEXT NOT NULL REFERENCES videos(video_id),
            snapshot_at       TEXT NOT NULL,
            play_count        INTEGER,
            like_count        INTEGER,
            comment_count     INTEGER,
            share_count       INTEGER,
            collect_count     INTEGER,
            danmaku_count     INTEGER,
            completion_rate   REAL,
            two_sec_exit_rate REAL,
            follower_gain     INTEGER,
            follower_loss     INTEGER,
            fan_play_ratio    REAL,
            extra             TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_stats_video_snapshot
            ON video_stats(video_id, snapshot_at);

        CREATE INDEX IF NOT EXISTS idx_stats_snapshot
            ON video_stats(snapshot_at);
    """)
    conn.commit()


def _make_video_id(platform: str, title: str, publish_time: str) -> str:
    key = f"{platform}::{title}::{publish_time}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------


def write_snapshot(item: dict) -> tuple[str, int]:
    """
    写入一条快照。返回 (video_id, snapshot_id)。
    item 必须包含 platform, title, publish_time。
    """
    platform = item["platform"]
    title = item["title"]
    publish_time = item["publish_time"]
    video_id = _make_video_id(platform, title, publish_time)
    now = _now_iso()

    conn = _get_conn()
    with _lock:
        # upsert videos（如果已存在则不覆盖 created_at）
        conn.execute("""
            INSERT INTO videos(video_id, platform, title, publish_time, duration_sec, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, title, publish_time) DO UPDATE SET
                duration_sec = excluded.duration_sec
        """, (
            video_id, platform, title, publish_time,
            item.get("duration_sec"), now,
        ))

        # insert snapshot
        cur = conn.execute("""
            INSERT INTO video_stats(
                video_id, snapshot_at,
                play_count, like_count, comment_count, share_count, collect_count,
                danmaku_count, completion_rate, two_sec_exit_rate,
                follower_gain, follower_loss, fan_play_ratio, extra
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id, now,
            item.get("play_count"),
            item.get("like_count"),
            item.get("comment_count"),
            item.get("share_count"),
            item.get("collect_count"),
            item.get("danmaku_count"),
            item.get("completion_rate"),
            item.get("two_sec_exit_rate"),
            item.get("follower_gain"),
            item.get("follower_loss"),
            item.get("fan_play_ratio"),
            json.dumps(item.get("extra"), ensure_ascii=False) if item.get("extra") else None,
        ))
        conn.commit()
        return video_id, cur.lastrowid


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def query_stats(
    platform: Optional[str] = None,
    title: Optional[str] = None,
    publish_since: Optional[str] = None,
    publish_until: Optional[str] = None,
    snapshot_since: Optional[str] = None,
    snapshot_until: Optional[str] = None,
    latest_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """
    查询快照，返回 (total_count, rows)。
    rows 为 video 信息 + 指标合并的字典列表。
    """
    conn = _get_conn()

    # 构造 WHERE 子句
    conditions: list[str] = []
    params: list[Any] = []

    if platform:
        conditions.append("v.platform = ?")
        params.append(platform)
    if title:
        conditions.append("v.title LIKE ?")
        params.append(f"%{title}%")
    if publish_since:
        conditions.append("v.publish_time >= ?")
        params.append(publish_since)
    if publish_until:
        conditions.append("v.publish_time <= ?")
        params.append(publish_until)
    if snapshot_since:
        conditions.append("s.snapshot_at >= ?")
        params.append(snapshot_since)
    if snapshot_until:
        conditions.append("s.snapshot_at <= ?")
        params.append(snapshot_until)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    if latest_only:
        # 每个 video_id 只取最新快照
        base_sql = f"""
            FROM video_stats s
            JOIN videos v ON v.video_id = s.video_id
            JOIN (
                SELECT video_id, MAX(snapshot_at) AS max_snap
                FROM video_stats
                GROUP BY video_id
            ) latest ON s.video_id = latest.video_id AND s.snapshot_at = latest.max_snap
            {where}
        """
    else:
        base_sql = f"""
            FROM video_stats s
            JOIN videos v ON v.video_id = s.video_id
            {where}
        """

    with _lock:
        total = conn.execute(f"SELECT COUNT(*) {base_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT
                v.video_id, v.platform, v.title, v.publish_time, v.duration_sec,
                s.id AS snapshot_id, s.snapshot_at,
                s.play_count, s.like_count, s.comment_count, s.share_count,
                s.collect_count, s.danmaku_count, s.completion_rate,
                s.two_sec_exit_rate, s.follower_gain, s.follower_loss,
                s.fan_play_ratio, s.extra
            {base_sql}
            ORDER BY s.snapshot_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return total, [dict(r) for r in rows]
