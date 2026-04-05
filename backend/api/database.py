"""
SQLAlchemy async database setup — PostgreSQL.

Two databases on the same PostgreSQL server:
  - ramboq       (production — deploy_branch == 'main')
  - ramboq_dev   (development — any other branch)

Credentials from secrets.yaml: db_user, db_password.
The deploy_branch in backend_config.yaml determines which DB to use.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.shared.helpers.utils import config, secrets
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


def _build_url() -> str:
    """Build the PostgreSQL URL from secrets.yaml + deploy_branch."""
    user     = secrets.get("db_user", "rambo_admin")
    password = secrets.get("db_password", "")
    host     = secrets.get("db_host", "localhost")
    port     = secrets.get("db_port", 5432)

    branch  = config.get("deploy_branch", "dev")
    db_name = "ramboq" if branch == "main" else "ramboq_dev"

    url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"
    logger.info(f"Database: PostgreSQL → {db_name} on {host}:{port}")
    return url


DATABASE_URL = _build_url()

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create all tables (idempotent)."""
    async with engine.begin() as conn:
        from backend.api.models import User, Agent, AgentEvent  # noqa: F401 �� ensure model registered
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database: tables verified")

    # Seed built-in agents
    from backend.api.algo.agent_engine import seed_agents
    await seed_agents()


async def get_session() -> AsyncSession:
    """Yield an async session (for use in route handlers)."""
    async with async_session() as session:
        yield session
