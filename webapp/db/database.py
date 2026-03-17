import psycopg2
import os
from dotenv import load_dotenv

load_dotenv(".env.web")


def get_db_cursor():
    # Yielding opened connection 
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "finops"),
        password=os.getenv("DB_PASSWORD", "finops_password"),
        database=os.getenv("DB_NAME", "finops_db")
    )
    cursor = conn.cursor()
    
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()