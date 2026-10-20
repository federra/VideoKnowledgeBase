"""Real PostgreSQL plus private filesystem; synthetic material never seeds project data."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.security.errors import Denied
from tests.integration.test_schema import execute, material
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)

pytestmark = pytest.mark.database


def work(c, org, member):
    ident = uuid4()
    execute(
        c,
        "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'file work',%s)",
        (ident, org, str(ident), member),
    )
    return ident


def test_upload_download_replay_and_revocation(engine, setup, tmp_path):
    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for
    from app.storage.http import get_store
    from app.storage.local import LocalStore

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        gid = grant(
            c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid
        )
    store = LocalStore(tmp_path / "files", max_bytes=16)
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app, base_url="http://localhost:8000")
        client.cookies.set("cip_session", token, path="/api/v1")
        params = {
            "work_id": str(wid),
            "expected_work_lock_version": "1",
            "original_name": "中文.txt",
            "media_type": "text/plain",
        }
        headers = {
            "X-CSRF-Token": csrf_for(token),
            "Idempotency-Key": str(uuid4()),
            "Content-Type": "application/octet-stream",
            "Origin": "http://localhost:5173",
        }
        invalid = client.post(
            "/api/v1/files",
            params={**params, "original_name": "x.exe"},
            content=b"invalid",
            headers=headers,
        )
        assert invalid.status_code == 422
        oversized = client.post("/api/v1/files", params=params, content=b"x" * 17, headers=headers)
        assert oversized.status_code == 413
        assert not list((store.root / "staging").iterdir())
        first = client.post(
            "/api/v1/files", params=params, content=b"real file body", headers=headers
        )
        assert first.status_code == 201, first.text
        file_id = first.json()["data"]["id"]
        assert "storage_key" not in first.text
        again = client.post(
            "/api/v1/files", params=params, content=b"real file body", headers=headers
        )
        assert again.json()["data"]["id"] == file_id
        conflict = client.post("/api/v1/files", params=params, content=b"changed", headers=headers)
        assert conflict.status_code == 409
        url = f"/api/v1/files/{file_id}/content"
        assert client.get(url).status_code == 404
        download = client.get(url, params={"parent_kind": "works", "parent_id": str(wid)})
        assert download.status_code == 200 and download.content == b"real file body"
        assert "attachment" in download.headers["content-disposition"]
        assert download.headers["x-content-type-options"] == "nosniff"
        assert len(list((tmp_path / "files" / "objects" / str(org)).iterdir())) == 1
        with engine.begin() as c:
            execute(
                c,
                "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
                (gid,),
            )
        assert (
            client.get(url, params={"parent_kind": "works", "parent_id": str(wid)}).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/files", params=params, content=b"real file body", headers=headers
            ).status_code
            == 404
        )
    finally:
        app.dependency_overrides.clear()
        store.close()


def test_failed_version_and_rollback_leave_no_file_or_metadata(engine, setup, tmp_path):
    from app.contracts.models import FileUploadQuery
    from app.storage.local import LocalStore
    from app.storage.service import save

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid)
    store = LocalStore(tmp_path / "files")
    try:
        meta = FileUploadQuery(
            work_id=wid,
            expected_work_lock_version="99",
            original_name="x.txt",
            media_type="text/plain",
        )
        with store.stage() as staged:
            staged.write(b"hello")
            with pytest.raises(Denied, match="VERSION_CONFLICT"):
                save(engine, store, token, uuid4(), meta, staged)
        assert list((tmp_path / "files" / "journals").iterdir()) == []
        assert not list((tmp_path / "files" / "objects").rglob("*"))
        with engine.connect() as c:
            assert (
                execute(c, "SELECT count(*) FROM file_objects WHERE org_id=%s", (org,)).scalar_one()
                == 0
            )
    finally:
        store.close()


def test_recovery_keeps_committed_file_removes_uncommitted_and_never_active_stage(
    engine, setup, tmp_path
):
    from app.contracts.models import FileUploadQuery
    from app.storage.local import LocalStore
    from app.storage.service import recover, save

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid)
    store = LocalStore(tmp_path / "files")
    try:
        meta = FileUploadQuery(
            work_id=wid,
            expected_work_lock_version="1",
            original_name="x.txt",
            media_type="text/plain",
        )
        with store.stage() as staged:
            staged.write(b"hello")
            info = save(engine, store, token, uuid4(), meta, staged)
        # Crash after successful commit before journal acknowledgement.
        with store.stage() as staged:
            staged.write(b"unused")
            store.journal(staged, org, info["id"])
        orphan = uuid4()
        with store.stage() as staged:
            staged.write(b"orphan")
            store.journal(staged, org, orphan)
            store.publish(staged, org, orphan)
        recover(engine, store)
        assert store.object_path(org, info["id"]).exists()
        assert not store.object_path(org, orphan).exists()
        assert not list((tmp_path / "files" / "journals").iterdir())
    finally:
        store.close()


def test_database_rejects_file_intake_from_other_work_version(engine, setup, tmp_path):
    from app.contracts.models import FileUploadQuery
    from app.storage.local import LocalStore
    from app.storage.service import save

    org, member, token, *_ = setup
    with engine.begin() as c:
        first, second = work(c, org, member), work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"])
        artifact, _ = material(c, org, member, second)
    store = LocalStore(tmp_path / "files")
    try:
        with store.stage() as staged:
            staged.write(b"first work")
            info = save(
                engine,
                store,
                token,
                uuid4(),
                FileUploadQuery(
                    work_id=first,
                    expected_work_lock_version="1",
                    original_name="x.txt",
                    media_type="text/plain",
                ),
                staged,
            )
        with pytest.raises(Exception, match="file intake work mismatch"), engine.begin() as c:
            version = uuid4()
            execute(
                c,
                "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,file_id,material_kind,content_sha256,created_by) VALUES (%s,%s,%s,%s,2,%s,'script',%s,%s)",
                (version, org, artifact, second, info["id"], "e" * 64, member),
            )
            execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
            execute(
                c,
                "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
                (version, artifact),
            )
    finally:
        store.close()


def test_external_replay_returns_original_before_any_network_and_rechecks_grant(
    engine, setup, tmp_path
):
    from app.contracts.models import FileFromUrl
    from app.storage.local import LocalStore
    from app.storage.service import replay_external, save

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        gid = grant(
            c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid
        )
    store = LocalStore(tmp_path / "files")
    key = uuid4()
    meta = FileFromUrl(
        work_id=wid,
        expected_work_lock_version="1",
        original_name="x.txt",
        media_type="text/plain",
        url="https://media.example/x",
    )
    try:
        with store.stage() as staged:
            staged.write(b"external body")
            first = save(engine, store, token, key, meta, staged, source_url=meta.url)
        assert replay_external(engine, token, key, meta)["id"] == first["id"]
        changed = meta.model_copy(update={"url": "https://media.example/other"})
        with pytest.raises(Denied, match="IDEMPOTENCY_CONFLICT"):
            replay_external(engine, token, key, changed)
        with engine.begin() as c:
            execute(
                c,
                "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
                (gid,),
            )
        with pytest.raises(Denied, match="NOT_FOUND"):
            replay_external(engine, token, key, meta)
    finally:
        store.close()


def test_database_failure_after_publish_rolls_back_and_cleans_owned_blob(engine, setup, tmp_path):
    from app.contracts.models import FileUploadQuery
    from app.storage.local import LocalStore
    from app.storage.service import save

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid)

    class FailedPublish(LocalStore):
        def publish(self, *args):
            super().publish(*args)
            raise OSError("synthetic crash after publish")

    store = FailedPublish(tmp_path / "files")
    try:
        with store.stage() as staged:
            staged.write(b"hello")
            with pytest.raises(OSError, match="synthetic crash"):
                save(
                    engine,
                    store,
                    token,
                    uuid4(),
                    FileUploadQuery(
                        work_id=wid,
                        expected_work_lock_version="1",
                        original_name="x.txt",
                        media_type="text/plain",
                    ),
                    staged,
                )
        assert not list((tmp_path / "files" / "objects").rglob("*/*"))
        # live stage prevented immediate journal removal; maintenance finalizes it.
        from app.storage.service import recover

        recover(engine, store)
        assert not list((tmp_path / "files" / "journals").iterdir())
        with engine.connect() as c:
            assert (
                execute(c, "SELECT count(*) FROM file_objects WHERE org_id=%s", (org,)).scalar_one()
                == 0
            )
    finally:
        store.close()


def test_historical_version_download_uses_exact_file_and_stops_after_revocation(
    engine, setup, tmp_path
):
    from app.contracts.models import FileUploadQuery
    from app.storage.local import LocalStore
    from app.storage.service import open_download, read_chunk, save

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        gid = grant(
            c,
            org,
            member,
            member,
            ["content.read", "content.write", "file.read", "evidence.read"],
            "work",
            wid,
        )
    store = LocalStore(tmp_path / "files")
    files = []
    try:
        for body in [b"first version", b"second version"]:
            with store.stage() as staged:
                staged.write(body)
                files.append(
                    save(
                        engine,
                        store,
                        token,
                        uuid4(),
                        FileUploadQuery(
                            work_id=wid,
                            expected_work_lock_version="1",
                            original_name="x.txt",
                            media_type="text/plain",
                        ),
                        staged,
                    )["id"]
                )
        with engine.begin() as c:
            artifact = uuid4()
            versions = [uuid4(), uuid4()]
            execute(
                c,
                "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES (%s,%s,%s,%s,'script',%s)",
                (artifact, org, wid, str(artifact), member),
            )
            for number, (version, fid) in enumerate(zip(versions, files), 1):
                execute(
                    c,
                    "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,file_id,material_kind,content_sha256,created_by) VALUES (%s,%s,%s,%s,%s,%s,'script',%s,%s)",
                    (version, org, artifact, wid, number, fid, str(number) * 64, member),
                )
                execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
            execute(
                c,
                "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
                (versions[1], artifact),
            )
        file, _ = open_download(engine, store, token, files[0], ("artifact_versions", versions[0]))
        try:
            assert (
                read_chunk(engine, token, files[0], ("artifact_versions", versions[0]), file)
                == b"first version"
            )
            with pytest.raises(Denied, match="NOT_FOUND"):
                open_download(engine, store, token, files[0], ("artifact_versions", versions[1]))
            with engine.begin() as c:
                execute(
                    c,
                    "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
                    (gid,),
                )
            with pytest.raises(Denied, match="NOT_FOUND"):
                read_chunk(engine, token, files[0], ("artifact_versions", versions[0]), file)
        finally:
            file.close()
    finally:
        store.close()


def test_private_file_upload_auth_precedes_origin_or_csrf(engine, setup, tmp_path):
    from app.main import app
    from app.security.http import get_engine
    from app.storage.http import get_store
    from app.storage.local import LocalStore

    store = LocalStore(tmp_path / "files")
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app, base_url="http://localhost:8000")
        response = client.post(
            "/api/v1/files",
            params={
                "work_id": str(uuid4()),
                "expected_work_lock_version": "1",
                "original_name": "x.txt",
                "media_type": "text/plain",
            },
            content=b"hello",
        )
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()
        store.close()


def test_real_restricted_database_role_can_save_and_download_nonempty_file(engine, setup, tmp_path):
    import secrets

    from psycopg import sql

    from app.contracts.models import FileUploadQuery
    from app.core.database import build_engine
    from app.core.database_roles import grant_application
    from app.storage.local import LocalStore
    from app.storage.service import open_download, save

    org, member, token, *_ = setup
    role = "cip_s053_role_" + uuid4().hex
    secret = secrets.token_urlsafe(32)
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid)
        cursor = c.connection.driver_connection.cursor()
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(secret))
        )
        grant_application(cursor, role)
    limited = build_engine(engine.url.set(username=role, password=secret))
    store = LocalStore(tmp_path / "files")
    try:
        with store.stage() as staged:
            staged.write(b"limited role file")
            info = save(
                limited,
                store,
                token,
                uuid4(),
                FileUploadQuery(
                    work_id=wid,
                    expected_work_lock_version="1",
                    original_name="x.txt",
                    media_type="text/plain",
                ),
                staged,
            )
        file, _ = open_download(limited, store, token, info["id"], ("works", wid))
        with file:
            assert file.read() == b"limited role file"
    finally:
        store.close()
        limited.dispose()
        with engine.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_disk_failure_returns_safe_error_and_cleans_uncommitted_bytes(engine, setup, tmp_path):
    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for
    from app.storage.http import get_store
    from app.storage.local import LocalStore

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid)

    class BrokenStore(LocalStore):
        def publish(self, *args):
            super().publish(*args)
            raise OSError("private-storage-path-do-not-echo")

    store = BrokenStore(tmp_path / "files")
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app, base_url="http://localhost:8000")
        client.cookies.set("cip_session", token, path="/api/v1")
        response = client.post(
            "/api/v1/files",
            params={
                "work_id": str(wid),
                "expected_work_lock_version": "1",
                "original_name": "x.txt",
                "media_type": "text/plain",
            },
            content=b"hello",
            headers={
                "Content-Type": "application/octet-stream",
                "Origin": "http://localhost:5173",
                "X-CSRF-Token": csrf_for(token),
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
        assert "private-storage-path" not in response.text
        assert not list((store.root / "objects").rglob("*/*"))
        assert not list((store.root / "staging").iterdir())
    finally:
        app.dependency_overrides.clear()
        store.close()
