from alembic import context
from sqlalchemy import create_engine, pool

from app.accounts import models  # noqa: F401
from app.config import settings
from app.db import Base
from app.plans import models as plan_models  # noqa: F401

if context.is_offline_mode():
    context.configure(
        url=settings().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
