import struct
from typing import NamedTuple, Any, Optional


class ByteOrderType:
    struct: str
    wchar: str
    bom: bytes
    suffix: str

    def __init__(self, struct_fmt: str, wchar: str, bom: bytes, suffix: str) -> None:
        self.struct = struct_fmt
        self.wchar = wchar
        self.bom = bom
        self.suffix = suffix

    def pack(self, fmt: str, *args: Any) -> bytes:
        return struct.pack(self.struct + fmt, *args)

    def unpack(self, fmt: str, buffer: bytes) -> tuple:
        return struct.unpack(self.struct + fmt, buffer)

    def encode(self, string: str) -> bytes:
        return string.encode(self.wchar)

    def decode(self, data: bytes) -> str:
        return data.decode(self.wchar)


class ByteOrder:
    LITTLE_ENDIAN = ByteOrderType("<", "utf-16-le", b"\xFF\xFE", "le")
    BIG_ENDIAN = ByteOrderType(">", "utf-16-be", b"\xFE\xFF", "be")

    @staticmethod
    def from_bom(bom: bytes, default: Optional[ByteOrderType] = None) -> ByteOrderType:
        if bom == b"\xFF\xFE":
            return ByteOrder.LITTLE_ENDIAN
        if bom == b"\xFE\xFF":
            return ByteOrder.BIG_ENDIAN
        if default:
            return default
        raise ValueError("Invalid BOM, or no default specified")
