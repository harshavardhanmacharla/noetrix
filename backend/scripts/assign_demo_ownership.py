"""
Safe, repeatable, and idempotent ownership assignment script for the existing demo organization.
Requires an explicitly selected administrator; does NOT auto-assign to first registered user.

Dry-run mode is enabled by default to prevent accidental live database mutations.
Usage:
    # Preview (dry run):
    python -m scripts.assign_demo_ownership --admin-email admin@example.com

    # Apply changes (explicit commit):
    python -m scripts.assign_demo_ownership --admin-email admin@example.com --commit
"""
import argparse
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User


def assign_demo_ownership(admin_email: str, org_slug: str = "testpilot-demo", role: str = "owner", commit: bool = False) -> int:
    """Assign organization ownership to an explicitly designated administrator."""
    clean_email = admin_email.strip().lower()

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == clean_email).first()
        if not user:
            print(f"[ERROR] User with email '{clean_email}' not found in database.", file=sys.stderr)
            print("Please provision the administrator account first using create_admin.py.", file=sys.stderr)
            return 1

        org = db.query(Organization).filter(Organization.slug == org_slug).first()
        if not org:
            # Fall back to first organization if slug does not match exactly
            org = db.query(Organization).first()

        if not org:
            print(f"[ERROR] No organization found with slug '{org_slug}' or in database.", file=sys.stderr)
            return 1

        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.org_id == org.id,
                OrganizationMembership.user_id == user.id,
            )
            .first()
        )

        if membership:
            if membership.role == role:
                print(f"[IDEMPOTENT] User '{user.email}' already holds role '{role}' in organization '{org.name}' ({org.id}).")
                return 0
            else:
                if not commit:
                    print(f"[DRY-RUN] Would update role of user '{user.email}' in organization '{org.name}' from '{membership.role}' to '{role}'.")
                    print("[DRY-RUN] Dry run active: Database was NOT modified. Pass --commit to apply.")
                    return 0
                membership.role = role
                db.commit()
                print(f"[SUCCESS] Updated role of user '{user.email}' in organization '{org.name}' to '{role}'.")
                return 0

        # Membership does not exist
        if not commit:
            print(f"[DRY-RUN] Target Organization : {org.name} (ID: {org.id}, Slug: {org.slug})")
            print(f"[DRY-RUN] Target Administrator: {user.email} (ID: {user.id})")
            print(f"[DRY-RUN] Assigned Role      : {role}")
            print("[DRY-RUN] Dry run active: Database was NOT modified. Pass --commit to apply.")
            return 0

        new_membership = OrganizationMembership(
            org_id=org.id,
            user_id=user.id,
            role=role,
        )
        db.add(new_membership)
        db.commit()
        print(f"[SUCCESS] Assigned user '{user.email}' as '{role}' of organization '{org.name}' ({org.id}).")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign ownership of demo organization to an administrator.")
    parser.add_argument("--admin-email", required=True, help="Designated administrator email address")
    parser.add_argument("--org-slug", default="testpilot-demo", help="Target organization slug (default: testpilot-demo)")
    parser.add_argument("--role", default="owner", choices=["owner", "admin", "member"], help="Role to assign (default: owner)")
    parser.add_argument("--commit", action="store_true", help="Apply changes to the database (default: dry-run mode)")

    args = parser.parse_args()
    return assign_demo_ownership(
        admin_email=args.admin_email,
        org_slug=args.org_slug,
        role=args.role,
        commit=args.commit,
    )


if __name__ == "__main__":
    sys.exit(main())
