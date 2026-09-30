"""Vercel build step (runs after dependencies are installed).

Vercel already runs collectstatic. This only prepares the database, and only for Production
deployments, so a preview branch can never change your real data.
"""
import os
import subprocess
import sys


def run(*args):
    print("->", "manage.py", *args, flush=True)
    subprocess.run([sys.executable, "manage.py", *args], check=True)


def main():
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set: skipping database setup.")
        return
    if os.environ.get("VERCEL_ENV", "production") != "production":
        print("Not a production build: skipping migrations.")
        return
    run("migrate", "--noinput")
    run("createcachetable")


if __name__ == "__main__":
    main()
