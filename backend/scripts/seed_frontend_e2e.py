"""Create the deterministic browser-test principal and print an access token.

This script is deliberately not an HTTP endpoint: CI invokes it directly after
applying migrations, so no test-only authentication surface can accidentally be
enabled in a deployed API process.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, select

from database import AsyncSessionLocal
from models.user import User
from models.workspace import Workspace
from services.auth_service import auth_service

E2E_EMAIL = "browser-e2e@specforge.test"
E2E_GOOGLE_ID = "browser-e2e-google-id"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == E2E_EMAIL))
        if user is None:
            user = User(
                email=E2E_EMAIL,
                google_id=E2E_GOOGLE_ID,
                name="Browser E2E",
                avatar_url=None,
                credit_balance=1_000,
            )
            session.add(user)
        else:
            user.name = "Browser E2E"
            user.credit_balance = 1_000
            await session.execute(delete(Workspace).where(Workspace.user_id == user.id))
        await session.commit()
        await session.refresh(user)
        print(auth_service._create_token(user.id, "access", 60))  # noqa: SLF001


if __name__ == "__main__":
    asyncio.run(main())
