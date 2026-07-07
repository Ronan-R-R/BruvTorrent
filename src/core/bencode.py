"""Bencode encoding and decoding.

Self-contained replacement for the unmaintained bencode.py package.
decode_from() exposes the end index so callers can extract the raw byte
slice of a value (needed for info-hash computation and ut_metadata
messages, where a bencoded dict is followed by raw payload bytes).
"""
from typing import Dict, List, Tuple, Union

BValue = Union[int, bytes, List['BValue'], Dict[bytes, 'BValue']]


class BencodeError(ValueError):
    pass


def encode(value: BValue) -> bytes:
    parts: List[bytes] = []
    _encode(value, parts)
    return b''.join(parts)


def _encode(value: BValue, parts: List[bytes]) -> None:
    if isinstance(value, bool):
        raise BencodeError("booleans are not bencodable")
    if isinstance(value, int):
        parts.append(b'i%de' % value)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        parts.append(b'%d:' % len(raw))
        parts.append(raw)
    elif isinstance(value, str):
        raw = value.encode('utf-8')
        parts.append(b'%d:' % len(raw))
        parts.append(raw)
    elif isinstance(value, list):
        parts.append(b'l')
        for item in value:
            _encode(item, parts)
        parts.append(b'e')
    elif isinstance(value, dict):
        parts.append(b'd')
        keys = []
        for key in value:
            if isinstance(key, str):
                keys.append(key.encode('utf-8'))
            elif isinstance(key, bytes):
                keys.append(key)
            else:
                raise BencodeError(f"invalid dict key type: {type(key)}")
        for raw_key in sorted(keys):
            _encode(raw_key, parts)
            try:
                _encode(value[raw_key], parts)
            except KeyError:
                _encode(value[raw_key.decode('utf-8')], parts)
        parts.append(b'e')
    else:
        raise BencodeError(f"cannot bencode type: {type(value)}")


def decode(data: bytes) -> BValue:
    value, end = decode_from(data, 0)
    if end != len(data):
        raise BencodeError(f"trailing data after position {end}")
    return value


def decode_from(data: bytes, index: int) -> Tuple[BValue, int]:
    """Decode one value starting at index. Returns (value, end_index)."""
    if index >= len(data):
        raise BencodeError("unexpected end of data")
    char = data[index:index + 1]
    if char == b'i':
        end = data.index(b'e', index)
        return int(data[index + 1:end]), end + 1
    if char == b'l':
        index += 1
        items: List[BValue] = []
        while data[index:index + 1] != b'e':
            item, index = decode_from(data, index)
            items.append(item)
        return items, index + 1
    if char == b'd':
        index += 1
        result: Dict[bytes, BValue] = {}
        while data[index:index + 1] != b'e':
            key, index = decode_from(data, index)
            if not isinstance(key, bytes):
                raise BencodeError("dict key is not a byte string")
            value, index = decode_from(data, index)
            result[key] = value
        return result, index + 1
    if char.isdigit():
        colon = data.index(b':', index)
        length = int(data[index:colon])
        start = colon + 1
        end = start + length
        if end > len(data):
            raise BencodeError("string length exceeds data")
        return data[start:end], end
    raise BencodeError(f"invalid bencode at position {index}: {char!r}")
