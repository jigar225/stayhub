from sqlalchemy import create_engine, pool

from alembic import context
from app import message_models, notification_models, review_models  # noqa: F401
from app.config import get_settings
from app.models import Base

config = context.config
target_metadata = Base.metadata
if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
