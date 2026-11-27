"""Server side commands for running the pilot.

With SMS login switched off, the only way in is a link, and links are made by
an admin. The first admin therefore needs a link made somewhere only the
operator can reach: the server itself.

    python -m khazana.manage create-admin --phone 03001234567 --name "Your name"
    python -m khazana.manage login-link --phone 03001234567
    python -m khazana.manage load-categories

In production, run them inside the API container:

    docker compose -f docker-compose.prod.yml --env-file .env.production \\
        exec api python -m khazana.manage login-link --phone 03001234567

Each prints a single use link that expires after INVITE_TTL_HOURS. Open it in
your own browser; do not paste it anywhere it would be stored.
"""

from __future__ import annotations

import argparse

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .db import build_engine
from .models import User
from .models.base import utcnow
from .models.enums import UserRole
from .services import invite_service
from .services.auth_service import normalise_phone


def _create_admin(db: Session, phone: str, name: str) -> User:
    number = normalise_phone(phone)
    user = db.scalars(select(User).where(User.phone == number)).first()
    if user is None:
        user = User(
            phone=number,
            full_name=" ".join(name.split())[:120] or "Admin",
            role=UserRole.ADMIN,
            phone_verified_at=utcnow(),
        )
        db.add(user)
    elif user.role != UserRole.ADMIN:
        raise SystemExit(f"{number} already belongs to a {user.role.value} account.")
    db.flush()
    return user


def _load_categories(engine: Engine) -> int:
    """The category tree from the seed, without any of its sample data."""
    from .models import Category
    from .seed import _seed_categories

    with Session(engine) as db:
        existing = db.scalars(select(Category.id).limit(1)).first()
        if existing is not None:
            print("Categories are already loaded; nothing was changed.")
            return 0
        created = _seed_categories(db)
        db.commit()
    print(f"Loaded {len(created)} categories.")
    return 0


def main(argv: list[str] | None = None, *, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m khazana.manage", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="create an admin and print a sign in link")
    create.add_argument("--phone", required=True)
    create.add_argument("--name", required=True)
    link = commands.add_parser("login-link", help="print a sign in link for an existing admin")
    link.add_argument("--phone", required=True)
    commands.add_parser(
        "load-categories", help="load the product category list, once, with no sample data"
    )
    args = parser.parse_args(argv)

    if args.command == "load-categories":
        return _load_categories(engine or build_engine())

    with Session(engine or build_engine()) as db:
        if args.command == "create-admin":
            admin = _create_admin(db, args.phone, args.name)
        else:
            number = normalise_phone(args.phone)
            found = db.scalars(select(User).where(User.phone == number)).first()
            if found is None or found.role != UserRole.ADMIN:
                raise SystemExit(f"No admin account uses {number}. Run create-admin first.")
            admin = found
        url = invite_service.create_for_admin(db, admin=admin)
        name = admin.full_name
        db.commit()

    print(f"Single use sign in link for {name}:")
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
