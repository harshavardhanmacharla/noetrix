"""
Initial administrator provisioning and bootstrap service.
Provides safe, controlled administrator creation outside unauthenticated HTTP endpoints.
"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.security import hash_password



def create_initial_admin(
    db: Session,
    email: str,
    password: str,
    full_name: Optional[str] = None,
) -> User:
    """
    Provision the initial platform administrator.
    Strictly verifies that no superuser currently exists in the system.
    Atomically creates or promotes the designated administrator.
    """
    clean_email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
        raise ValueError("Invalid email address format.")

    if not password or len(password) < 8:
        raise ValueError("Administrator password must be at least 8 characters long.")

    # Concurrency and exclusivity check: ensure no superuser already exists
    existing_superusers = (
        db.query(User)
        .filter(User.is_superuser.is_(True))
        .all()
    )
    if existing_superusers:
        raise ValueError(
            "An administrator account already exists. "
            "Additional administrators must be provisioned by existing administrators."
        )

    # Check if a user account with this email already exists
    user = db.query(User).filter(User.email == clean_email).first()
    if user:
        user.is_superuser = True
        user.is_active = True
        if full_name:
            user.full_name = full_name
        db.commit()
        db.refresh(user)
        return user

    # Create new superuser (strictly User record without organization membership)
    user = User(
        email=clean_email,
        hashed_password=hash_password(password),
        full_name=full_name or "System Administrator",
        is_active=True,
        is_superuser=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

