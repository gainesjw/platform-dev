"""Executed explicitly in the staged app root by the build-only pipeline."""
import azure.functions as func
import function_app


def test_health_response():
    request = func.HttpRequest(method="GET", url="http://localhost/api/health", body=b"")
    response = function_app.health(request)
    assert response.status_code == 200
    assert response.get_body() == b"platform template smoke test"


def test_http_function_indexes():
    functions = function_app.app.get_functions()
    assert len(functions) == 1
    assert functions[0].get_function_name() == "health"
