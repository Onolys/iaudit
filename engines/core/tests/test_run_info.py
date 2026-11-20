import hashlib

from onolys_core.run_info import hash_files


def test_hash_files_concatenates_in_order(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert hash_files([a, b]) == hashlib.sha256(b"onetwo").hexdigest()[:16]
    assert hash_files([b, a]) != hash_files([a, b])
    assert hash_files([a], length=8) == hashlib.sha256(b"one").hexdigest()[:8]
