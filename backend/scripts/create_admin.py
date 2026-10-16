"""
Controlled administrative provisioning script for Noetrix.
Creates the initial platform administrator outside unauthenticated web endpoints.
Usage:
    python -m scripts.create_admin --email admin@example.com --password "SecretPass123!" --full-name "Admin User"
"""
import argparse
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.services.bootstrap import create_initial_admin


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision initial Noetrix platform administrator.")
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument("--password", required=False, default=None, help="Administrator password (min 8 characters). Prompted securely if omitted.")
    parser.add_argument("--full-name", default="System Administrator", help="Administrator full name")

    args = parser.parse_args()

    password = args.password
    if not password:
        if sys.stdin.isatty():
            import getpass
            password = getpass.getpass("Enter administrator password (min 8 chars): ")
            confirm = getpass.getpass("Confirm administrator password: ")
            if password != confirm:
                print("[REJECTED] Passwords do not match.", file=sys.stderr)
                return 1
        else:
            print("[REJECTED] Password was not provided. Use --password or run in an interactive terminal.", file=sys.stderr)
            return 1

    try:
        with SessionLocal() as db:
            admin_user = create_initial_admin(
                db=db,
                email=args.email,
                password=password,
                full_name=args.full_name,
            )
            print(f"[SUCCESS] Initial administrator successfully provisioned: {admin_user.email} (ID: {admin_user.id})")
            return 0

    except ValueError as val_err:
        print(f"[REJECTED] {val_err}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Failed to provision administrator: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
