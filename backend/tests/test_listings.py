from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.errors import ApiError
from app.main import app
from app.models import ListingPhoto, now
from app.storage_cleanup import cleanup

PASSWORD = "listing-test-password!"


def identity(client: TestClient, host: bool = True) -> dict[str, str]:
    email = f"listing-{uuid4()}@example.com"
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"name": "Host", "email": email, "password": PASSWORD},
        ).status_code
        == 201
    )
    auth = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    if host:
        assert client.post("/api/v1/me/host-role", headers=headers).status_code == 200
    return headers


def create(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post("/api/v1/host/listings", headers=headers, json={})
    assert response.status_code == 201, response.text
    return dict(response.json()["listing"])


def details(
    client: TestClient, headers: dict[str, str], listing: dict[str, Any]
) -> dict[str, Any]:
    policy = client.get("/api/v1/host/cancellation-policies", headers=headers).json()[
        "items"
    ][0]
    fields = {
        "property_type": "apartment",
        "address": "12 Test Lane",
        "destination": "Lisbon",
        "timezone": "Europe/Lisbon",
        "capacity": 4,
        "bedrooms": 2,
        "beds": 2,
        "baths": 1,
        "title": "Bright courtyard apartment",
        "description": "A comfortable apartment with a quiet courtyard.",
        "amenities": ["Wi-Fi", "Kitchen"],
        "house_rules": ["No smoking"],
        "nightly_minor": 12000,
        "cleaning_minor": 2500,
        "policy_id": policy["id"],
        "booking_mode": "request",
        "check_in_time": "15:00",
        "check_out_time": "11:00",
    }
    response = client.patch(
        f"/api/v1/host/listings/{listing['id']}",
        headers=headers,
        json={"version": listing["version"], **fields},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["listing"])


def image_bytes(kind: str = "PNG", dimensions: tuple[int, int] = (96, 64)) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", dimensions, "teal")
    info = PngImagePlugin.PngInfo()
    info.add_text("Secret", "strip-this-metadata")
    image.save(output, format=kind, pnginfo=info)
    return output.getvalue()


def intent(
    client: TestClient,
    headers: dict[str, str],
    listing_id: str,
    content: bytes,
    content_type: str = "image/png",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/host/listings/{listing_id}/photos/upload-intents",
        headers=headers,
        json={"content_type": content_type, "bytes": len(content)},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def complete(
    client: TestClient, headers: dict[str, str], listing_id: str, photo_id: str
) -> httpx.Response:
    return cast(
        httpx.Response,
        client.post(
            f"/api/v1/host/listings/{listing_id}/photos/{photo_id}/complete",
            headers=headers,
            json={},
        ),
    )


def upload(
    client: TestClient,
    headers: dict[str, str],
    listing_id: str,
    content: bytes | None = None,
) -> dict[str, Any]:
    data = image_bytes() if content is None else content
    authorization = intent(client, headers, listing_id, data)
    result = httpx.put(
        authorization["upload"]["url"],
        content=data,
        headers=authorization["upload"]["headers"],
        timeout=10,
    )
    assert result.status_code == 200, result.text
    response = complete(client, headers, listing_id, authorization["photo_id"])
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_saved_draft_pagination_versions_validation(client: TestClient) -> None:
    headers = identity(client)
    listing = create(client, headers)
    assert listing["status"] == "draft" and listing["version"] == 1
    assert listing["title"] is None and listing["photos"] == []
    assert listing["check_in_time"] == "15:00"
    path = f"/api/v1/host/listings/{listing['id']}"
    response = client.patch(
        path,
        headers=headers,
        json={"version": 1, "title": "  Saved title  ", "address": " "},
    )
    assert response.status_code == 200
    saved = response.json()["listing"]
    assert saved["title"] == "Saved title" and saved["address"] is None
    assert client.get(path, headers=headers).json()["listing"] == saved
    assert (
        client.patch(
            path, headers=headers, json={"version": 1, "title": "stale"}
        ).status_code
        == 409
    )
    for extra in (
        {"owner_id": str(uuid4())},
        {"status": "published"},
        {"nightly_minor": 125.5},
        {"capacity": True},
        {"timezone": "invalid/timezone"},
        {"check_in_time": "25:00"},
        {"amenities": ["Wi-Fi", "Wi-Fi"]},
    ):
        assert (
            client.patch(
                path, headers=headers, json={"version": 2, **extra}
            ).status_code
            == 422
        )
    assert client.get(path, headers=headers).json()["listing"] == saved
    create(client, headers)
    page = client.get("/api/v1/host/listings?limit=1", headers=headers).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = client.get(
        f"/api/v1/host/listings?limit=1&cursor={page['next_cursor']}", headers=headers
    ).json()
    assert next_page["items"][0]["id"] != page["items"][0]["id"]
    assert (
        len(
            client.get("/api/v1/host/cancellation-policies", headers=headers).json()[
                "items"
            ]
        )
        == 4
    )


def test_private_listing_photo_ownership_and_role_isolation(client: TestClient) -> None:
    owner = identity(client)
    listing = create(client, owner)
    data = image_bytes()
    authorization = intent(client, owner, listing["id"], data)
    photo_id = authorization["photo_id"]
    paths = [
        ("get", "", None),
        ("patch", "", {"version": 2, "title": "stolen"}),
        ("post", "/publish", {"version": 2}),
        ("post", "/unlist", {"version": 2}),
        ("post", "/photos/upload-intents", {"content_type": "image/png", "bytes": 100}),
        ("post", f"/photos/{photo_id}/complete", {}),
        ("delete", f"/photos/{photo_id}", None),
        ("get", f"/photos/{photo_id}/read", None),
        ("patch", "/photos/order", {"version": 2, "photo_ids": []}),
    ]
    other = identity(client)
    guest = identity(client, host=False)
    for headers, expected in [
        (other, 404),
        (guest, 403),
        ({"Authorization": "Bearer invalid"}, 401),
    ]:
        for method, suffix, body in paths:
            response = client.request(
                method,
                f"/api/v1/host/listings/{listing['id']}{suffix}",
                headers=headers,
                json=body,
            )
            assert response.status_code == expected, (method, suffix, response.text)
    assert client.get("/api/v1/host/listings", headers=other).json()["items"] == []
    assert (
        client.get(
            f"/api/v1/host/listings/{listing['id']}/photos/{photo_id}/read",
            headers=owner,
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/host/listings",
            headers={**owner, "Origin": "https://evil.example"},
            json={},
        ).status_code
        == 403
    )


def test_real_upload_publication_edit_rollback_order_unlist(client: TestClient) -> None:
    headers = identity(client)
    listing = details(client, headers, create(client, headers))
    path = f"/api/v1/host/listings/{listing['id']}"
    for _ in range(4):
        result = upload(client, headers, listing["id"])
        listing = result["listing"]
    rejected = client.post(
        path + "/publish", headers=headers, json={"version": listing["version"]}
    )
    assert (
        rejected.status_code == 422
        and "photos" in rejected.json()["error"]["field_errors"]
    )
    listing = upload(client, headers, listing["id"])["listing"]
    published = client.post(
        path + "/publish", headers=headers, json={"version": listing["version"]}
    )
    assert published.status_code == 200, published.text
    listing = published.json()["listing"]
    assert listing["status"] == "published"
    assert "owner_id" not in listing and "final_key" not in str(listing)
    invalid_edits: list[dict[str, Any]] = [
        {"title": " "},
        {"nightly_minor": None},
        {"house_rules": ["NO CHILDREN allowed"]},
    ]
    for invalid in invalid_edits:
        response = client.patch(
            path, headers=headers, json={"version": listing["version"], **invalid}
        )
        assert response.status_code == 422
        assert client.get(path, headers=headers).json()["listing"] == listing
    ids = [photo["id"] for photo in listing["photos"]]
    assert client.delete(path + f"/photos/{ids[0]}", headers=headers).status_code == 409
    assert (
        client.patch(
            path + "/photos/order",
            headers=headers,
            json={"version": listing["version"], "photo_ids": ids[:-1]},
        ).status_code
        == 422
    )
    response = client.patch(
        path + "/photos/order",
        headers=headers,
        json={"version": listing["version"], "photo_ids": ids[::-1]},
    )
    assert response.status_code == 200
    listing = response.json()["listing"]
    assert [photo["id"] for photo in listing["photos"]] == ids[::-1]
    response = client.post(
        path + "/unlist", headers=headers, json={"version": listing["version"]}
    )
    assert (
        response.status_code == 200
        and response.json()["listing"]["status"] == "unlisted"
    )
    assert len(response.json()["listing"]["photos"]) == 5
    deleted = client.delete(path + f"/photos/{ids[0]}", headers=headers)
    assert deleted.status_code == 200 and len(deleted.json()["listing"]["photos"]) == 4


def test_completion_idempotence_metadata_strip_staging_replay_private_read(
    client: TestClient,
) -> None:
    headers = identity(client)
    listing = create(client, headers)
    raw = image_bytes()
    authorization = intent(client, headers, listing["id"], raw)
    put = httpx.put(
        authorization["upload"]["url"],
        headers=authorization["upload"]["headers"],
        content=raw,
    )
    assert put.status_code == 200
    first = complete(client, headers, listing["id"], authorization["photo_id"])
    assert first.status_code == 200
    second = complete(client, headers, listing["id"], authorization["photo_id"])
    assert second.json() == first.json()
    read = client.get(
        f"/api/v1/host/listings/{listing['id']}/photos/{authorization['photo_id']}/read",
        headers=headers,
    ).json()
    downloaded = httpx.get(read["url"])
    assert (
        downloaded.status_code == 200
        and b"strip-this-metadata" not in downloaded.content
    )
    unsigned = read["url"].split("?")[0]
    assert httpx.get(unsigned).status_code in (403, 401)
    before = downloaded.content
    # The old authorization can rewrite only staging; the final object is a new key.
    changed = raw[:-1] + bytes([raw[-1] ^ 1])
    assert changed != raw and len(changed) == len(raw)
    assert (
        httpx.put(
            authorization["upload"]["url"],
            headers=authorization["upload"]["headers"],
            content=changed,
        ).status_code
        == 200
    )
    assert httpx.get(read["url"]).content == before
    assert (
        client.get(f"/api/v1/host/listings/{listing['id']}", headers=headers).json()[
            "listing"
        ]["photos"][0]["id"]
        == authorization["photo_id"]
    )


def test_upload_rejects_disguised_mismatch_oversize_missing_expired_dimensions(
    client: TestClient,
) -> None:
    headers = identity(client)
    listing = create(client, headers)
    path = f"/api/v1/host/listings/{listing['id']}"
    for content, content_type in [
        (b"not-a-real-image", "image/png"),
        (image_bytes(), "image/jpeg"),
        (image_bytes(dimensions=(8193, 1)), "image/png"),
        (image_bytes(dimensions=(5000, 4001)), "image/png"),
    ]:
        authorization = intent(client, headers, listing["id"], content, content_type)
        assert (
            httpx.put(
                authorization["upload"]["url"],
                headers=authorization["upload"]["headers"],
                content=content,
            ).status_code
            == 200
        )
        assert (
            complete(
                client, headers, listing["id"], authorization["photo_id"]
            ).status_code
            == 422
        )
    assert (
        client.post(
            path + "/photos/upload-intents",
            headers=headers,
            json={"content_type": "image/png", "bytes": 10485761},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path + "/photos/upload-intents",
            headers=headers,
            json={"content_type": "image/svg+xml", "bytes": 100},
        ).status_code
        == 422
    )
    pending = intent(client, headers, listing["id"], image_bytes())
    assert (
        complete(client, headers, listing["id"], pending["photo_id"]).status_code == 422
    )
    with Session(storage_db()) as db:
        photo = db.get(ListingPhoto, UUID(pending["photo_id"]))
        assert photo
        photo.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert (
        complete(client, headers, listing["id"], pending["photo_id"]).json()["error"][
            "code"
        ]
        == "upload_expired"
    )
    assert client.get(path, headers=headers).json()["listing"]["photos"] == []


def storage_db() -> Any:
    from app.db import get_engine

    return get_engine()


def test_concurrent_intents_and_completion_are_serialized(client: TestClient) -> None:
    headers = identity(client)
    listing = create(client, headers)
    for _ in range(19):
        intent(client, headers, listing["id"], image_bytes())

    def create_parallel() -> int:
        with TestClient(
            app,
            base_url="http://localhost:5173",
            headers={"Origin": "http://localhost:5173", **headers},
        ) as parallel:
            return int(
                parallel.post(
                    f"/api/v1/host/listings/{listing['id']}/photos/upload-intents",
                    json={"content_type": "image/png", "bytes": 100},
                ).status_code
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: create_parallel(), range(2))) == [201, 409]
    listing2 = create(client, headers)
    raw = image_bytes()
    authorization = intent(client, headers, listing2["id"], raw)
    assert (
        httpx.put(
            authorization["upload"]["url"],
            content=raw,
            headers=authorization["upload"]["headers"],
        ).status_code
        == 200
    )

    def complete_parallel() -> dict[str, Any]:
        with TestClient(
            app,
            base_url="http://localhost:5173",
            headers={"Origin": "http://localhost:5173", **headers},
        ) as parallel:
            result = complete(
                parallel, headers, listing2["id"], authorization["photo_id"]
            )
            assert result.status_code == 200
            return dict(result.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: complete_parallel(), range(2)))
    assert results[0] == results[1]
    assert len(results[0]["listing"]["photos"]) == 1


def test_storage_failure_no_false_attachment_and_retry(
    client: TestClient, monkeypatch: Any
) -> None:
    headers = identity(client)
    listing = create(client, headers)
    raw = image_bytes()
    authorization = intent(client, headers, listing["id"], raw)
    assert (
        httpx.put(
            authorization["upload"]["url"],
            content=raw,
            headers=authorization["upload"]["headers"],
        ).status_code
        == 200
    )
    original = storage.put_final

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ApiError(503, "storage_unavailable", "Storage unavailable")

    monkeypatch.setattr(storage, "put_final", fail)
    result = complete(client, headers, listing["id"], authorization["photo_id"])
    assert result.status_code == 503
    assert (
        client.get(f"/api/v1/host/listings/{listing['id']}", headers=headers).json()[
            "listing"
        ]["photos"]
        == []
    )
    monkeypatch.setattr(storage, "put_final", original)
    assert (
        complete(client, headers, listing["id"], authorization["photo_id"]).status_code
        == 200
    )
    with pytest.raises(ApiError), storage.storage_errors():
        # Context manager must translate SDK failures, never leak endpoint/secrets.
        raise EndpointConnectionError(endpoint_url="http://unavailable")


def test_scoped_cleanup_dryrun_expiry_preserves_verified(client: TestClient) -> None:
    headers = identity(client)
    listing = create(client, headers)
    attached = upload(client, headers, listing["id"])
    pending = intent(client, headers, listing["id"], image_bytes())
    with Session(storage_db()) as db:
        photo = db.get(ListingPhoto, UUID(pending["photo_id"]))
        assert photo
        photo.expires_at = now() - timedelta(seconds=1)
        db.commit()
    before = cleanup()
    assert before["expired_slots"] == 1
    with Session(storage_db()) as db:
        photo = db.get(ListingPhoto, UUID(pending["photo_id"]))
        assert photo and photo.state == "pending"
    applied = cleanup(apply=True)
    assert applied["expired_slots"] == 1
    with Session(storage_db()) as db:
        photo = db.get(ListingPhoto, UUID(pending["photo_id"]))
        assert photo and photo.state == "expired"
    read = client.get(
        f"/api/v1/host/listings/{listing['id']}/photos/{attached['photo']['id']}/read",
        headers=headers,
    ).json()
    assert httpx.get(read["url"]).status_code == 200


def test_actual_oversized_source_rejected_even_if_storage_contains_it(
    client: TestClient,
) -> None:
    headers = identity(client)
    listing = create(client, headers)
    authorization = intent(client, headers, listing["id"], image_bytes())
    with Session(storage_db()) as db:
        photo = db.get(ListingPhoto, UUID(authorization["photo_id"]))
        assert photo
        key = photo.staging_key
    # Bypass the signed browser authorization using the isolated test SDK to
    # emulate a malicious/stale object; completion still verifies actual bytes.
    storage.s3_client().put_object(
        Bucket=get_settings().s3_bucket,
        Key=key,
        Body=b"x" * (storage.MAX_SOURCE_BYTES + 1),
        ContentType="image/png",
    )
    response = complete(client, headers, listing["id"], authorization["photo_id"])
    assert response.status_code == 422
    assert (
        client.get(f"/api/v1/host/listings/{listing['id']}", headers=headers).json()[
            "listing"
        ]["photos"]
        == []
    )


@pytest.mark.parametrize(
    ("kind", "content_type"), [("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_real_jpeg_webp_verified_uploads(
    client: TestClient, kind: str, content_type: str
) -> None:
    headers = identity(client)
    listing = create(client, headers)
    raw = image_bytes(kind=kind)
    authorization = intent(client, headers, listing["id"], raw, content_type)
    assert (
        httpx.put(
            authorization["upload"]["url"],
            headers=authorization["upload"]["headers"],
            content=raw,
        ).status_code
        == 200
    )
    response = complete(client, headers, listing["id"], authorization["photo_id"])
    assert response.status_code == 200
    assert response.json()["photo"]["content_type"] == content_type
    assert response.json()["photo"]["width"] == 96
