"""
One-off script: create/update the two team login accounts in Supabase Auth.
Not part of the app's runtime -- run by hand whenever team membership
changes. Idempotent: re-running updates password/role rather than erroring
on an existing user (see auth.create_or_update_user).

Usage:
    python scripts/provision_users.py
(reads the plaintext passwords from environment variables so they never
appear in shell history or this file -- see the prompts below)
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(override=True)

from app.auth import create_or_update_user

USERS = [
    ("john@agencysocial.com", "admin"),
    ("cathy@agencysocial.com", "member"),
]


def main():
    for email, role in USERS:
        password = getpass.getpass(f"Password for {email} ({role}): ")
        if not password:
            print(f"  skipped {email} (no password entered)")
            continue
        result = create_or_update_user(email, password, role)
        print(f"  {email} -> id={result['id']} role={role}")
    print("Done.")


if __name__ == "__main__":
    main()
