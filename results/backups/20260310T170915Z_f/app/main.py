import os
from contextlib import closing

import pymysql
from fastapi import FastAPI, HTTPException


def get_db_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "appuser"),
        password=os.getenv("DB_PASSWORD", "apppassword"),
        database=os.getenv("DB_NAME", "appdb"),
        cursorclass=pymysql.cursors.DictCursor,
    )


app = FastAPI(title="Target API")


@app.get("/healthz")
def healthz():
    try:
        with closing(get_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                row = cursor.fetchone()
        return {"status": "ok", "db": row}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"database error: {exc}") from exc


@app.get("/api/items")
def list_items():
    try:
        with closing(get_db_connection()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, details FROM items ORDER BY id")
                items = cursor.fetchall()
        return {"items": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"database error: {exc}") from exc
