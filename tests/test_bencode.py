import pytest

from src.core import bencode


@pytest.mark.parametrize("value", [
    0, 42, -7,
    b"", b"hello", b"x" * 300,
    [], [1, 2, 3], [b"a", [b"b", 1]],
    {b"a": 1, b"b": [1, 2]},
    {b"info": {b"name": b"file", b"length": 100}},
])
def test_roundtrip(value):
    assert bencode.decode(bencode.encode(value)) == value


def test_dict_keys_are_sorted():
    encoded = bencode.encode({b"b": 1, b"a": 2})
    assert encoded == b"d1:ai2e1:bi1ee"


def test_decode_from_returns_end_index():
    data = b"i42eTRAILER"
    value, end = bencode.decode_from(data, 0)
    assert value == 42
    assert data[end:] == b"TRAILER"


def test_string_keys_encode_as_bytes():
    assert bencode.encode({"a": 1}) == b"d1:ai1ee"


def test_trailing_data_rejected():
    with pytest.raises(bencode.BencodeError):
        bencode.decode(b"i1ejunk")


def test_truncated_string_rejected():
    with pytest.raises(bencode.BencodeError):
        bencode.decode(b"5:abc")
