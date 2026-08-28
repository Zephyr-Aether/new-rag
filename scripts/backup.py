"""备份 / 恢复（§Backup）：SQLite 拷贝 / PostgreSQL pg_dump。

用法：
    python scripts/backup.py backup            # 备份到 backups/agent-<ts>.<ext>
    python scripts/backup.py restore <file>    # 恢复（SQLite 覆盖 dev.db；PG 走 psql 需手动确认）
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups"


def _database_url() -> str:
    from app.settings import get_settings

    return get_settings().database_url


def _sqlite_file(url: str) -> Path:
    # sqlite+aiosqlite:///./dev.db 或绝对路径
    raw = url.split("///", 1)[-1]
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def backup() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    url = _database_url()
    ts = time.strftime("%Y%m%d-%H%M%S")
    if url.startswith("sqlite"):
        src = _sqlite_file(url)
        dest = BACKUP_DIR / f"agent-{ts}.sqlite3"
        # 拷贝前做一次 WAL checkpoint，保证一致性
        subprocess.run(["sqlite3", str(src), "PRAGMA wal_checkpoint(TRUNCATE);"], capture_output=True)
        shutil.copy2(src, dest)
        print(f"备份完成: {dest} ({src.stat().st_size} bytes)")
        return dest
    if url.startswith("postgresql"):
        import re

        m = re.match(r"postgresql(?:\+asyncpg)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(\w+)", url)
        user, pwd, host, port, db = m.group(1), m.group(2), m.group(3), m.group(4) or "5432", m.group(5)
        dest = BACKUP_DIR / f"agent-{ts}.sql"
        env = dict(os.environ, PGPASSWORD=pwd)
        subprocess.run(
            ["pg_dump", "-h", host, "-p", port, "-U", user, "-d", db, "-f", str(dest)],
            env=env,
            check=True,
        )
        print(f"备份完成: {dest}")
        return dest
    raise SystemExit(f"不支持的数据库: {url}")


def restore(path: str) -> None:
    src = Path(path)
    url = _database_url()
    if url.startswith("sqlite"):
        dest = _sqlite_file(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"已恢复: {src} -> {dest}")
        print("提示: 如服务在运行，请重启后端加载恢复的数据。")
    elif url.startswith("postgresql"):
        import re

        m = re.match(r"postgresql(?:\+asyncpg)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(\w+)", url)
        user, pwd, host, port, db = m.group(1), m.group(2), m.group(3), m.group(4) or "5432", m.group(5)
        env = dict(os.environ, PGPASSWORD=pwd)
        # 恢复前建议先 drop/recreate 目标库；这里直接 psql 导入
        subprocess.run(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", db, "-f", str(src)],
            env=env,
            check=True,
        )
        print(f"已恢复: {src} -> {db}")
    else:
        raise SystemExit(f"不支持的数据库: {url}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python scripts/backup.py backup|restore <file>")
    if sys.argv[1] == "backup":
        backup()
    elif sys.argv[1] == "restore" and len(sys.argv) >= 3:
        restore(sys.argv[2])
    else:
        raise SystemExit("用法: python scripts/backup.py backup|restore <file>")
