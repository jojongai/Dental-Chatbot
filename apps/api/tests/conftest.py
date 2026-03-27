import os

# Ensure tests use an in-memory DB before `database` is imported.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Force deterministic keyword/regex path — tests must not depend on live LLM calls.
os.environ.setdefault("USE_LLM", "false")
