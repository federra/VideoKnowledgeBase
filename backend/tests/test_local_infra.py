import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from dotenv import dotenv_values
from scripts.local_infra import initialize, read_settings, validate_proof


def test_initialize_creates_private_matching_local_configuration(tmp_path):
    initialize(tmp_path)
    env = dotenv_values(tmp_path / '.env')
    url = urlparse(env['DATABASE_URL'])
    assert unquote(url.password) == env['POSTGRES_PASSWORD']
    assert len(env['POSTGRES_PASSWORD']) >= 32
    assert env['POSTGRES_PORT'] == str(url.port) == '15432'
    assert url.hostname == '127.0.0.1'
    assert env['REDIS_URL'] == 'redis://127.0.0.1:16379/0'
    assert os.stat(tmp_path / '.env').st_mode & 0o777 == 0o600


def test_initialize_never_overwrites_existing_configuration(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('POSTGRES_PASSWORD=keep-existing\n', encoding='utf-8')
    before = env_file.read_bytes()
    assert initialize(tmp_path) is False
    assert env_file.read_bytes() == before


def test_settings_refuse_nonlocal_connection_targets(tmp_path):
    initialize(tmp_path)
    env_file = tmp_path / '.env'
    contents = env_file.read_text().replace('127.0.0.1', 'example.com')
    env_file.write_text(contents)
    with pytest.raises(ValueError, match='local'):
        read_settings(tmp_path)


def test_proof_cannot_target_an_arbitrary_schema_or_redis_key():
    with pytest.raises(ValueError, match='probe'):
        validate_proof({'schema': 'public', 'redis_key': '*', 'marker': 'x'})


def test_missing_configuration_has_actionable_error(tmp_path: Path):
    with pytest.raises(ValueError, match='init'):
        read_settings(tmp_path)
