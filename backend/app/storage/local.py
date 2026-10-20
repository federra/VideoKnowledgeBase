"""Private POSIX storage: UUID keys, descriptor-relative no-follow paths, durable journals."""

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from app.security.errors import Denied

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class Staged:
    def __init__(self, file, name, maximum):
        self.file, self.name, self.maximum = file, name, maximum
        self.size, self.hasher = 0, hashlib.sha256()

    @property
    def sha256(self):
        return self.hasher.hexdigest()

    def write(self, chunk):
        if self.size + len(chunk) > self.maximum:
            raise Denied("FILE_TOO_LARGE")
        self.file.write(chunk)
        self.hasher.update(chunk)
        self.size += len(chunk)


class LocalStore:
    def __init__(self, root, max_bytes=50 * 1024 * 1024):
        if not 1 <= max_bytes <= 256 * 1024 * 1024:
            raise ValueError("Invalid file size policy")
        self.root = Path(os.path.abspath(root))
        self.maximum = max_bytes
        fd = os.open(self.root.anchor, FLAGS)
        try:
            for part in self.root.parts[1:]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                new = os.open(part, FLAGS, dir_fd=fd)
                os.close(fd)
                fd = new
            self.check_private(fd)
            self.fd = os.dup(fd)
        finally:
            os.close(fd)
        for name in ("objects", "staging", "journals"):
            with self.directory(name):
                pass

    @staticmethod
    def check_private(fd):
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise Denied("SERVICE_NOT_READY")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @contextmanager
    def directory(self, *parts):
        self.check_private(self.fd)
        fd = os.dup(self.fd)
        try:
            for part in parts:
                if not re.fullmatch(r"[a-z0-9-]+", part):
                    raise ValueError("Invalid internal directory")
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                new = os.open(part, FLAGS, dir_fd=fd)
                os.close(fd)
                fd = new
                self.check_private(fd)
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def stage(self):
        name = uuid4().hex + ".part"
        with self.directory("staging") as fd:
            handle = os.open(
                name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            with os.fdopen(handle, "w+b") as file:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    yield Staged(file, name, self.maximum)
                finally:
                    try:
                        os.unlink(name, dir_fd=fd)
                    except FileNotFoundError:
                        pass

    def object_path(self, org, file_id):
        return self.root / "objects" / str(UUID(str(org))) / str(UUID(str(file_id)))

    def publish(self, staged, org, file_id):
        staged.file.flush()
        os.fsync(staged.file.fileno())
        with (
            self.directory("staging") as source,
            self.directory("objects", str(UUID(str(org)))) as target,
        ):
            os.link(
                staged.name,
                str(UUID(str(file_id))),
                src_dir_fd=source,
                dst_dir_fd=target,
                follow_symlinks=False,
            )
            os.fsync(target)

    def open(self, org, file_id):
        with self.directory("objects", str(UUID(str(org)))) as fd:
            handle = os.open(
                str(UUID(str(file_id))), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
            )
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            os.close(handle)
            raise Denied("FILE_NOT_ACCEPTED")
        return os.fdopen(handle, "rb")

    def remove(self, org, file_id):
        with self.directory("objects", str(UUID(str(org)))) as fd:
            try:
                os.unlink(str(UUID(str(file_id))), dir_fd=fd)
            except FileNotFoundError:
                pass
            os.fsync(fd)

    def journal(self, staged, org, file_id):
        body = json.dumps(
            {"version": 1, "org_id": str(org), "file_id": str(file_id), "stage": staged.name},
            sort_keys=True,
        ).encode()
        with self.directory("journals") as fd:
            name = str(UUID(str(file_id))) + ".json"
            handle = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            with os.fdopen(handle, "wb") as out:
                out.write(body)
                out.flush()
                os.fsync(out.fileno())
            os.fsync(fd)

    def forget(self, file_id):
        with self.directory("journals") as fd:
            try:
                os.unlink(str(UUID(str(file_id))) + ".json", dir_fd=fd)
            except FileNotFoundError:
                pass
            os.fsync(fd)

    def journals(self):
        with self.directory("journals") as fd:
            for name in os.listdir(fd):
                if not re.fullmatch(r"[0-9a-f-]{36}\.json", name):
                    continue
                try:
                    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(handle, "rb") as file:
                        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                            continue
                        body = json.loads(file.read(1025))
                    assert body["version"] == 1 and name == str(UUID(body["file_id"])) + ".json"
                    UUID(body["org_id"])
                    assert re.fullmatch(r"[a-f0-9]{32}\.part", body["stage"])
                except (OSError, ValueError, KeyError, AssertionError):
                    continue
                yield body

    def clean_stage(self, name, *, min_age=0):
        if not re.fullmatch(r"[a-f0-9]{32}\.part", name):
            return False
        with self.directory("staging") as fd:
            try:
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except FileNotFoundError:
                return True
            with os.fdopen(handle, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or time.time() - info.st_mtime < min_age:
                    return False
                try:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
                os.unlink(name, dir_fd=fd)
                os.fsync(fd)
        return True

    def cleanup_staging(self, *, exclude=()):
        removed = 0
        with self.directory("staging") as fd:
            for name in os.listdir(fd):
                if name in exclude:
                    continue
                try:
                    removed += int(self.clean_stage(name, min_age=3600))
                except OSError:
                    continue
        return removed
