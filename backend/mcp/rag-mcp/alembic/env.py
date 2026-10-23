from alembic import context
from sqlalchemy import create_engine, pool
from app.config import Settings
from app.database import Base
from app import news_store  # noqa: F401


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "rag"
    return True


options = dict(target_metadata=Base.metadata, include_schemas=True,
    include_name=include_name, version_table_schema="rag")
url = Settings().database_url
if context.is_offline_mode():
    context.configure(url=url, literal_binds=True, **options)
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS rag")
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS rag")
        connection.commit()
        context.configure(connection=connection, **options)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
