import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture
def client(tmp_path):
    application = create_app(tmp_path / "state.json")
    with TestClient(application) as test_client:
        yield test_client
