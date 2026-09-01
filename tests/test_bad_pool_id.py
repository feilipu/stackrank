import pytest
from .conftest import client


def test_pool_add_invalid_ids():
    # Test invalid pool ID -1
    response = client.post("/pool/add/-1")
    assert response.status != "500"

    # Test invalid pool ID 999999
    response = client.post("/pool/add/999999")
    assert response.status != "500"