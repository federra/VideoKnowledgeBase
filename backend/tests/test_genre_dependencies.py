from types import SimpleNamespace
from uuid import uuid4

from app.security.read_authorizer import ReadAuthorizer


def test_shared_model_file_preserves_union_of_all_targets():
    a, b, ra, rb, source, output_a, output_b, shared = [uuid4() for _ in range(8)]
    replies = iter(
        [
            [(a, source, ra), (b, source, rb)],
            [(output_a, a), (output_b, b)],
            [(a, shared, None), (b, shared, None)],
        ]
    )
    az = object.__new__(ReadAuthorizer)
    az.c = SimpleNamespace(exec_driver_sql=lambda *_: next(replies))
    az.p = SimpleNamespace(org_id=uuid4())
    az.memo = lambda _key, load: load()
    links = az._genre_links()
    assert links["file", shared] == {ra, rb}
    assert links["raw", source] == {ra, rb}
