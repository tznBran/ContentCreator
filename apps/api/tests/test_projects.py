"""Project CRUD tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_list_get_update_delete_project(client: TestClient) -> None:
    # Empty initially
    assert client.get("/projects").json() == []

    # Create
    create_response = client.post(
        "/projects",
        json={"title": "My first AI video", "prompt": "A cinematic shot of mountains."},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "My first AI video"
    assert created["prompt"] == "A cinematic shot of mountains."
    assert created["status"] == "draft"
    project_id = created["id"]

    # List
    list_response = client.get("/projects")
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert items[0]["id"] == project_id

    # Get
    get_response = client.get(f"/projects/{project_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == project_id

    # Update
    update_response = client.patch(
        f"/projects/{project_id}",
        json={"title": "Updated title", "status": "generating"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["title"] == "Updated title"
    assert updated["status"] == "generating"

    # Delete
    delete_response = client.delete(f"/projects/{project_id}")
    assert delete_response.status_code == 204
    assert client.get(f"/projects/{project_id}").status_code == 404


def test_create_project_validates_title(client: TestClient) -> None:
    response = client.post("/projects", json={"title": "", "prompt": ""})
    assert response.status_code == 422
