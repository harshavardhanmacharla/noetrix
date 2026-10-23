"""
Retrieve active development reset URL for local testing.
Usage:
    python -m scripts.get_dev_reset_link --email admin@example.com
"""
import argparse
from pathlib import Path
import sys

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from app.services.email import get_latest_dev_reset_url


def main() -> int:
    settings = get_settings()
    if settings.ENVIRONMENT.lower() == "production":
        print("[ERROR] Development helper is disabled in production.", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description="Get latest development password reset link.")
    parser.add_argument("--email", required=True, help="User email address")
    args = parser.parse_args()

    clean_email = args.email.strip().lower()
    url = get_latest_dev_reset_url(clean_email)
    if not url:
        print(f"[NOT FOUND] No pending development reset link found for {clean_email}.", file=sys.stderr)
        print("Make sure you submitted the forgot-password form for this email first.", file=sys.stderr)
        return 1

    print(f"\n[FOUND] Latest reset URL for {clean_email}:\n  {url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

