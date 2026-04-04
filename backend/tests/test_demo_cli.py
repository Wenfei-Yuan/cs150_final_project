from urllib import error

from demo_cli import (
    build_mode_choices,
    ensure_backend_available,
    http_request,
    normalize_mode_choice,
    print_result,
)


def test_http_request_returns_structured_connection_error(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise error.URLError("[WinError 10061] No connection could be made")

    monkeypatch.setattr("demo_cli.request.urlopen", fake_urlopen)

    status, payload = http_request("GET", "/health")

    assert status is None
    assert payload == {
        "error_type": "connection_error",
        "message": "Cannot reach the backend at http://localhost:8000.",
        "details": "URLError: <urlopen error [WinError 10061] No connection could be made>",
    }


def test_print_result_shows_connection_guidance(capsys):
    print_result(None, {
        "error_type": "connection_error",
        "message": "Cannot reach the backend at http://localhost:8000.",
        "details": "URLError: <urlopen error [WinError 10061] No connection could be made>",
    })

    captured = capsys.readouterr().out

    assert "Connection Error" in captured
    assert "python -m uvicorn app.main:app" in captured
    assert "docker compose up --build" in captured
    assert "DEMO_API_BASE" in captured
    assert "HTTP Status" not in captured


def test_ensure_backend_available_returns_false_when_health_unreachable(monkeypatch, capsys):
    def fake_http_request(method, path, json_body=None, data=None, headers=None):
        assert method == "GET"
        assert path == "/health"
        return None, {
            "error_type": "connection_error",
            "message": "Cannot reach the backend at http://localhost:8000.",
            "details": "URLError: <urlopen error [WinError 10061] No connection could be made>",
        }

    monkeypatch.setattr("demo_cli.http_request", fake_http_request)

    assert ensure_backend_available() is False

    captured = capsys.readouterr().out
    assert "Backend is not ready" in captured


def test_build_mode_choices_handles_legacy_nested_description_payload():
    response = {
        "recommended_mode": "goal_directed",
        "mode_explanation": "Pick the most relevant sections for a goal.",
        "alternative_modes": [
            {
                "mode": "skim",
                "description": {
                    "mode": "skim",
                    "name": "Skim / Overview Mode",
                    "description": "Quick overview of the paper.",
                },
            },
            {
                "mode": "deep_comprehension",
                "description": {
                    "mode": "deep_comprehension",
                    "name": "Deep Comprehension Mode",
                    "description": "Read every chunk in order with a quiz gate.",
                },
            },
        ],
    }

    result = build_mode_choices(response)

    assert [choice["mode"] for choice in result] == [
        "goal_directed",
        "skim",
        "deep_comprehension",
    ]
    assert all(isinstance(choice["description"], str) for choice in result)
    assert result[1]["name"] == "Skim / Overview Mode"


def test_normalize_mode_choice_keeps_current_payload_shape():
    result = normalize_mode_choice({
        "mode": "skim",
        "name": "Skim / Overview Mode",
        "description": "Quick overview of the paper.",
    })

    assert result == {
        "mode": "skim",
        "name": "Skim / Overview Mode",
        "description": "Quick overview of the paper.",
    }