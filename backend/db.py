"""
Database connection pooling for the FastAPI backend.

A web server handles many concurrent requests, so we can't open a fresh
MySQL connection per request the way the sync script does (that's fine for
a script that runs once and exits, but wasteful for a server handling many
requests). mysql-connector's built-in pool hands out a small set of reusable
connections instead.
"""

import os
import mysql.connector.pooling
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "3306")),
    database=os.environ.get("DB_NAME", "bus_factor_tracker"),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASSWORD", ""),
)

pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="bus_factor_pool",
    pool_size=5,
    **DB_CONFIG,
)


def get_connection():
    """
    FastAPI dependency — yields a pooled connection and always returns it
    to the pool afterward, even if the request raised an exception.
    """
    conn = pool.get_connection()
    try:
        yield conn
    finally:
        conn.close()  # returns the connection to the pool, doesn't actually close it
