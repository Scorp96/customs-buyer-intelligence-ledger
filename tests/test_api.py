from fastapi.testclient import TestClient

from main import app


def test_health_and_openapi_contract():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "2.1.0"

    schema = client.get("/openapi.json").json()
    operation_ids = {
        operation["operationId"]
        for methods in schema["paths"].values()
        for method, operation in methods.items()
        if method in {"get", "post"}
    }
    assert {
        "getHealth",
        "lookupBuyerLedger",
        "mergeBuyerLedger",
        "recordOutreachEvent",
        "validateOutreachDraft",
    }.issubset(operation_ids)

    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method not in {"get", "post"}:
                continue
            response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in response_schema or response_schema.get("properties"), (
                f"{method.upper()} {path} must expose a response model with named properties"
            )


def test_api_key_is_enforced_when_configured(monkeypatch):
    monkeypatch.setenv("ACTION_API_KEY", "test-secret")
    monkeypatch.setenv("STORE_MODE", "local")
    client = TestClient(app)
    payload = {"legal_or_customs_name": "Example Buyer", "country": "Uganda", "aliases": []}
    assert client.post("/ledger/lookup", json=payload).status_code == 401
    assert client.post("/ledger/lookup", json=payload, headers={"X-Action-Key": "wrong"}).status_code == 401
    assert client.post("/ledger/lookup", json=payload, headers={"X-Action-Key": "test-secret"}).status_code == 200
