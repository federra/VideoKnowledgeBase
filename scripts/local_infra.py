"""S02 local-only environment commands. Never drops volumes or touches business tables."""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import psycopg
import redis
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'cip-local'


def initialize(root: Path) -> bool:
    """Create private local settings once; existing configuration is never rewritten."""
    filename = root / '.env'
    password = secrets.token_urlsafe(32)
    contents = (
        '# Local development only. Do not commit or paste these credentials.\n'
        'APP_NAME=content-intelligence-api\n'
        'CIP_DOCKER_CONTEXT=colima-cip-local\n'
        'POSTGRES_DB=content_intelligence\nPOSTGRES_USER=content_intelligence\n'
        f'POSTGRES_PASSWORD={password}\nPOSTGRES_PORT=15432\nREDIS_PORT=16379\n'
        'DATABASE_URL=postgresql+psycopg://content_intelligence:'
        f'{quote(password, safe="")}@127.0.0.1:15432/content_intelligence\n'
        'REDIS_URL=redis://127.0.0.1:16379/0\nSTORAGE_ROOT=../data\n'
    )
    try:
        descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(contents)
    return True


def read_settings(root: Path) -> dict[str, str]:
    filename = root / '.env'
    if not filename.is_file():
        raise ValueError('Run infra init first; .env is missing.')
    settings = {key: value for key, value in dotenv_values(filename).items() if value is not None}
    for key in ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'DATABASE_URL', 'REDIS_URL'):
        if not settings.get(key):
            raise ValueError(f'Missing {key}; preserve existing settings and fill this field locally.')
    pg = urlparse(settings['DATABASE_URL'])
    cache = urlparse(settings['REDIS_URL'])
    for target in (pg, cache):
        if target.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('S02 checks require local targets only.')
    if pg.scheme not in ('postgresql', 'postgresql+psycopg') or cache.scheme != 'redis':
        raise ValueError('Unsupported local database protocol.')
    if (unquote(pg.username or '') != settings['POSTGRES_USER']
            or unquote(pg.password or '') != settings['POSTGRES_PASSWORD']
            or unquote(pg.path.lstrip('/')) != settings['POSTGRES_DB']):
        raise ValueError('DATABASE_URL must match POSTGRES settings; credentials were not printed.')
    settings.setdefault('POSTGRES_PORT', '15432')
    settings.setdefault('REDIS_PORT', '16379')
    if pg.port != int(settings['POSTGRES_PORT']) or cache.port != int(settings['REDIS_PORT']):
        raise ValueError('Connection URL ports must match the Compose published ports.')
    return settings


def docker_environment(settings: dict[str, str]) -> dict[str, str]:
    environment = {**os.environ, **settings}
    context = settings.get('CIP_DOCKER_CONTEXT', '')
    if context:
        environment['DOCKER_CONTEXT'] = context
        environment.pop('DOCKER_HOST', None)
    docker = shutil.which('docker')
    if not docker:
        raise ValueError('Docker CLI is missing; install the local runtime first.')
    result = subprocess.run(
        [docker, 'context', 'inspect', *([context] if context else [])],
        env=environment, capture_output=True, text=True, check=True, timeout=15,
    )
    endpoint = json.loads(result.stdout)[0]['Endpoints']['docker']['Host']
    if not endpoint.startswith('unix://') or environment.get('DOCKER_HOST', '').startswith('tcp:'):
        raise ValueError('S02 automation accepts a local Unix Docker socket only.')
    return environment


def compose(root: Path, settings: dict[str, str], *arguments: str) -> str:
    environment = docker_environment(settings)
    standalone = shutil.which('docker-compose')
    command = [standalone] if standalone else ['docker', 'compose']
    result = subprocess.run(
        [*command, '--project-name', PROJECT, '--env-file', str(root / '.env'),
         '-f', str(root / 'infra/compose.yaml'), *arguments],
        env=environment, capture_output=True, text=True, check=True, timeout=240,
    )
    return result.stdout.strip()


def pg_connect(settings: dict[str, str]):
    target = urlparse(settings['DATABASE_URL'])
    return psycopg.connect(
        host=target.hostname, port=target.port, dbname=unquote(target.path.lstrip('/')),
        user=unquote(target.username or ''), password=unquote(target.password or ''),
        connect_timeout=3,
    )


def redis_connect(settings: dict[str, str]):
    return redis.Redis.from_url(
        settings['REDIS_URL'], decode_responses=True, socket_connect_timeout=3, socket_timeout=8,
    )


def check_connections(settings: dict[str, str], enable_vector: bool = False) -> dict:
    with pg_connect(settings) as connection:
        if enable_vector:
            connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
        version = connection.execute('SHOW server_version').fetchone()[0]
        extension = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        if not extension:
            raise ValueError('pgvector is not enabled; use infra up in the dedicated project database.')
        distance = connection.execute("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector").fetchone()[0]
        if distance != 0:
            raise ValueError('pgvector distance check failed.')
    with redis_connect(settings) as cache:
        if not cache.ping():
            raise ValueError('Redis PING failed.')
        info = cache.info()
        if info.get('aof_enabled') != 1:
            raise ValueError('Redis AOF persistence is not enabled.')
    return {'postgres': {'connected': True, 'version': version, 'pgvector': extension[0]},
            'redis': {'ping': True, 'version': info['redis_version'], 'aof_enabled': True}}


def validate_proof(proof: dict) -> None:
    marker = proof.get('marker', '')
    if (not re.fullmatch(r'[0-9a-f]{32}', marker)
            or proof.get('schema') != 'cip_s02_probe_' + marker
            or proof.get('redis_key') != 'cip:s02:probe:' + marker):
        raise ValueError('Invalid isolated probe identifier; refusing to touch any data.')


def probe(root: Path, settings: dict[str, str]) -> dict:
    receipt = root / 'data/s02-proof.json'
    if receipt.exists() and not json.loads(receipt.read_text()).get('cleaned', False):
        raise ValueError('A pending probe exists; run restart-proof before creating another.')
    marker = uuid.uuid4().hex
    proof = {'marker': marker, 'schema': 'cip_s02_probe_' + marker,
             'redis_key': 'cip:s02:probe:' + marker, 'database': settings['POSTGRES_DB'],
             'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'cleaned': False}
    validate_proof(proof)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(proof, indent=2) + '\n')
    with pg_connect(settings) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(proof['schema'])))
        connection.execute(sql.SQL('CREATE TABLE {}.probe (id text PRIMARY KEY, value text NOT NULL)')
                           .format(sql.Identifier(proof['schema'])))
        connection.execute(sql.SQL('INSERT INTO {}.probe VALUES (%s, %s)')
                           .format(sql.Identifier(proof['schema'])), ('persist', marker))
    with pg_connect(settings) as connection:
        connection.execute(sql.SQL('INSERT INTO {}.probe VALUES (%s, %s)')
                           .format(sql.Identifier(proof['schema'])), ('rollback', marker))
        connection.rollback()
        row = connection.execute(sql.SQL('SELECT count(*) FROM {}.probe WHERE id=%s')
                                 .format(sql.Identifier(proof['schema'])), ('rollback',)).fetchone()
        if row[0] != 0:
            raise ValueError('PostgreSQL rollback verification failed.')
    with redis_connect(settings) as cache:
        cache.set(proof['redis_key'], marker)
        if cache.get(proof['redis_key']) != marker:
            raise ValueError('Redis read/write verification failed.')
        if cache.execute_command('WAITAOF', 1, 0, 5000)[0] != 1:
            raise ValueError('Redis AOF flush verification timed out.')
    proof.update({'postgres_read_write': True, 'transaction_rollback': True, 'redis_read_write': True,
                  'redis_aof_flushed': True})
    receipt.write_text(json.dumps(proof, indent=2) + '\n')
    return proof


def restart_proof(root: Path, settings: dict[str, str]) -> dict:
    receipt = root / 'data/s02-proof.json'
    proof = json.loads(receipt.read_text())
    validate_proof(proof)
    if proof.get('cleaned') or proof.get('database') != settings['POSTGRES_DB']:
        raise ValueError('No pending probe for this database; run probe first.')
    compose(root, settings, 'restart', 'postgres', 'redis')
    for attempt in range(40):
        try:
            check_connections(settings)
            break
        except (psycopg.OperationalError, redis.RedisError):
            if attempt == 39:
                raise
            time.sleep(1)
    with pg_connect(settings) as connection:
        row = connection.execute(sql.SQL('SELECT value FROM {}.probe WHERE id=%s')
                                 .format(sql.Identifier(proof['schema'])), ('persist',)).fetchone()
        if not row or row[0] != proof['marker']:
            raise ValueError('PostgreSQL restart persistence failed; probe retained.')
    with redis_connect(settings) as cache:
        if cache.get(proof['redis_key']) != proof['marker']:
            raise ValueError('Redis restart persistence failed; probe retained.')
    # Only this run's explicitly named disposable table/schema/key may be cleaned.
    with pg_connect(settings) as connection:
        connection.execute(sql.SQL('DROP TABLE {}.probe').format(sql.Identifier(proof['schema'])))
        connection.execute(sql.SQL('DROP SCHEMA {}').format(sql.Identifier(proof['schema'])))
    with redis_connect(settings) as cache:
        cache.delete(proof['redis_key'])
    proof.update({'postgres_restart_persistent': True, 'redis_restart_persistent': True,
                  'cleaned': True, 'completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    receipt.write_text(json.dumps(proof, indent=2) + '\n')
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'up', 'status', 'check', 'probe', 'restart-proof', 'stop'))
    arguments = parser.parse_args()
    try:
        if arguments.command == 'init':
            print('Created private .env.' if initialize(ROOT) else 'Existing .env preserved.')
            return 0
        settings = read_settings(ROOT)
        command = arguments.command
        if command == 'up':
            compose(ROOT, settings, 'config', '--quiet')
            compose(ROOT, settings, 'up', '-d', '--wait', '--wait-timeout', '120')
            result = check_connections(settings, enable_vector=True)
        elif command == 'status':
            print(compose(ROOT, settings, 'ps', '--format', 'json'))
            return 0
        elif command == 'check':
            result = check_connections(settings)
        elif command == 'probe':
            result = probe(ROOT, settings)
        elif command == 'restart-proof':
            result = restart_proof(ROOT, settings)
        else:
            compose(ROOT, settings, 'stop')
            result = {'stopped': True, 'volumes_preserved': True}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, psycopg.Error, redis.RedisError) as error:
        # Dependency exceptions can include DSNs; never echo their potentially secret message.
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print(f'Local infrastructure check failed ({type(error).__name__}); no credentials printed.',
                  file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
