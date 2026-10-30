"""Explicit, transactional and idempotent demo provisioning; never run on startup."""

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import User, UserRole
from app.policies import seed_policies
from app.schemas import RegisterInput
from app.security import password_hasher


def main() -> None:
    specifications = [
        ("GUEST", ["guest"]),
        ("HOST", ["guest", "host"]),
        ("ADMIN", ["admin"]),
    ]
    inputs = []
    for key, roles in specifications:
        body = RegisterInput(
            name=os.environ[f"SEED_{key}_NAME"],
            email=os.environ[f"SEED_{key}_EMAIL"],
            password=os.environ[f"SEED_{key}_PASSWORD"],
        )
        inputs.append((body, roles))
    if len({str(body.email) for body, _ in inputs}) != 3:
        raise ValueError("Seed accounts must have distinct emails")
    with Session(get_engine()) as db, db.begin():
        seed_policies(db)
        for body, roles in inputs:
            existing = db.scalar(
                select(User).where(User.email == str(body.email)).with_for_update()
            )
            if existing:
                if {row.role for row in existing.memberships} != set(roles):
                    raise ValueError(
                        "Existing seed account roles differ; no accounts were changed"
                    )
                continue
            db.add(
                User(
                    email=str(body.email),
                    name=body.name,
                    password_hash=password_hasher.hash(body.password),
                    memberships=[UserRole(role=role) for role in roles],
                )
            )
    print("Demo provisioning complete; existing account credentials preserved.")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError):
        raise SystemExit(
            "Seed configuration is missing or invalid; no credentials are displayed."
        ) from None
