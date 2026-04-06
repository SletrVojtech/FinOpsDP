import psycopg2
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from fastapi import HTTPException

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(str(BASE_DIR / ".env.web"), override=True)

_REQUIRED = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
_missing = [v for v in _REQUIRED if not os.getenv(v)]
if _missing:
    print(f"[database] Missing required env-vars: {', '.join(_missing)}")



def get_db_cursor():
    try:
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=os.getenv("DB_PORT", "5432"),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"]
        )
    except psycopg2.Error as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {e}")

    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()
