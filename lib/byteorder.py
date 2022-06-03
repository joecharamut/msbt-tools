import struct
from typing import NamedTuple, Any


class _ByteOrder:
    struct: str
    wchar: str
    bom: bytes

    def __init__(self, struct_fmt: str, wchar: str, bom: bytes) -> None:
        self.struct = struct_fmt
        self.wchar = wchar
        self.bom = bom

    def pack(self, fmt: str, *args: Any) -> bytes:
        return struct.pack(self.struct + fmt, *args)

    def unpack(self, fmt: str, buffer: bytes) -> tuple:
        return struct.unpack(self.struct + fmt, buffer)

    def encode(self, string: str) -> bytes:
        return string.encode(self.wchar)

    def decode(self, data: bytes) -> str:
        return data.decode(self.wchar)


class ByteOrder:
    LITTLE_ENDIAN = _ByteOrder("<", "utf-16-le", b"\xFF\xFE")
    BIG_ENDIAN = _ByteOrder(">", "utf-16-be", b"\xFE\xFF")

