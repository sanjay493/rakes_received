"""The app opens its database when it is imported, so point it at a temporary folder before any test
module imports it."""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["API_TOKEN"] = "test-token"
os.environ.pop("APP_PASSWORD", None)
