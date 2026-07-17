#!/usr/bin/env python3
"""
Local Celery worker runner for development.

Usage:
    python celery_worker.py

Requires Redis to be running on localhost:6379 (or set REDIS_URL env var).
"""
import os
import sys

from dotenv import load_dotenv

# Load .env for DATABASE_URL, REDIS_URL, etc.
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_file)

if __name__ == "__main__":
    try:
        from core.tasks import app as celery_app
    except ImportError:
        from ems.core.tasks import app as celery_app

    # Start worker: -l info = log level, -c 4 = 4 concurrent processes
    celery_app.worker_main(
        argv=[
            "worker",
            "--loglevel=info",
            "--concurrency=1",
        ]
    )
