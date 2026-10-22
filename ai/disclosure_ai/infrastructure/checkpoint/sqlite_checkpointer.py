from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def open_checkpointer(state_path):
    return AsyncSqliteSaver.from_conn_string(str(state_path) + ".checkpoints")
