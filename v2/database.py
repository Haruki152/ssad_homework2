"""SQLite 引擎与连接约束。每个版本使用独立数据库。"""
import os
from pathlib import Path
from sqlalchemy import create_engine, event


def make_engine(url):
    if not url.startswith("sqlite:"):
        raise ValueError("本作业仅配置 SQLite 数据库")
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys_on(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


data_dir = Path(__file__).resolve().parents[1] / "data"
data_dir.mkdir(exist_ok=True)
engine = make_engine(os.environ.get(
    "RMS_DATABASE_URL", "sqlite:///" + (data_dir / "v2.db").as_posix()
))
