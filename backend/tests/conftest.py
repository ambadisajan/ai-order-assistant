import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.config import Settings
from app.data_store import OrderDataStore
from app.agent import OrderAssistantAgent
from app.main import app
import app.main as main_module


@pytest.fixture
def test_data_path() -> str:
    """Path to the test orders dataset."""
    return str(backend_root / "data" / "orders.csv")


@pytest.fixture
def data_store(test_data_path: str) -> OrderDataStore:
    """Create fresh OrderDataStore instance for tests."""
    return OrderDataStore(data_path=test_data_path)


@pytest.fixture
def test_settings(test_data_path: str) -> Settings:
    """Settings configured for testing."""
    return Settings(
        openai_api_key="test-api-key",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        cors_origins="http://localhost:5173,http://testserver",
        data_path=test_data_path
    )


@pytest.fixture
def client(data_store: OrderDataStore, test_settings: Settings):
    """FastAPI TestClient with initialized globals."""
    main_module.data_store = data_store
    main_module.agent = OrderAssistantAgent(settings=test_settings, data_store=data_store)
    with TestClient(app) as test_client:
        yield test_client
