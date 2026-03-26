import os

# Ensure tests use an in-memory DB before `database` is imported.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
