import io
import os
import typing
import struct
from typing import NamedTuple, List, Optional


class ByteOrder:
    class Order(NamedTuple):
        struct: str
        wchar: str
        bom: bytes

    LITTLE_ENDIAN = Order("<", "utf-16-le", b"\xFF\xFE")
    BIG_ENDIAN = Order(">", "utf-16-be", b"\xFE\xFF")


class DarcEntry:
    name: str
    _is_dir: bool
    _children: List["DarcEntry"]
    _data: Optional[bytes]
    _parent: Optional["DarcEntry"]

    def __init__(self, name: str, is_dir: bool = False) -> None:
        self.name = name
        self._is_dir = is_dir

        self._children = []
        self._data = None
        self._parent = None

    def __repr__(self) -> str:
        return f"<DarcEntry {'directory' if self._is_dir else 'file'} length={self.length}>"

    def dump(self, depth=0) -> None:
        print(f"{'-'*depth}| {self.name}")
        if self._is_dir:
            for e in self._children:
                e.dump(depth + 1)

    @property
    def length(self) -> int:
        if self._is_dir:
            return len(self._children)
        else:
            if self._data:
                return len(self._data)
            return 0

    @property
    def data(self) -> bytes:
        if self._is_dir:
            raise TypeError("Cannot get data of a directory")
        return self._data or bytes()

    @data.setter
    def data(self, data: bytes) -> None:
        if self._is_dir:
            raise TypeError("Cannot set data of a directory")
        self._data = data

    def add_child(self, child: "DarcEntry") -> None:
        if not self._is_dir:
            raise TypeError("Cannot add children of a file")
        print(f"add child: {self.name}->{child.name}")
        child._parent = self
        self._children.append(child)

    def remove_child(self, child: "DarcEntry") -> None:
        if not self._is_dir:
            raise TypeError("Cannot remove children of a file")
        child._parent = None
        self._children.remove(child)

    @property
    def filename(self) -> str:
        stack = []
        node = self
        while node is not None:
            stack.append(node.name)
            node = node._parent
        stack.reverse()
        return "/".join(stack)


class Darc:
    DARC_MAGIC = b"darc"
    DARC_VERSION = 0x1000000

    IDENT_STRUCT = "4s 2s"  # b"darc" and BOM
    HEADER_STRUCT = "{} H I I I I I"  # endian dependant fields
    FILE_TABLE_ENTRY = "{} I I I"

    def __init__(self, byte_order=ByteOrder.LITTLE_ENDIAN) -> None:
        self.byte_order = byte_order
        self.root_entry = DarcEntry("")

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()

        # write ident magic
        buf.write(Darc.DARC_MAGIC)
        buf.write(self.byte_order.bom)

        # write header
        buf.write(struct.pack(
            Darc.HEADER_STRUCT.format(self.byte_order.struct),
            0x1C,               # header length
            Darc.DARC_VERSION,  # version
            0,                  # file length
            0x1C,               # file table offset
            0,                  # file table length
            0,                  # file data offset
        ))

        return buf.getvalue()

    @staticmethod
    def from_bytes(data: bytes) -> "Darc":
        f = io.BytesIO(data)

        magic, bom = struct.unpack(Darc.IDENT_STRUCT, f.read(6))
        if magic != Darc.DARC_MAGIC:
            raise TypeError(f"Invalid magic: expected {Darc.DARC_MAGIC} got {magic}")

        byte_order = ByteOrder.LITTLE_ENDIAN
        if bom == b"\xFF\xFE":
            byte_order = ByteOrder.LITTLE_ENDIAN
        elif bom == b"\xFE\xFF":
            byte_order = ByteOrder.BIG_ENDIAN

        header_len, version, file_size, file_tab_off, file_tab_len, file_dat_off = \
            struct.unpack(Darc.HEADER_STRUCT.format(byte_order.struct), f.read(22))

        if version != Darc.DARC_VERSION:
            raise TypeError(f"Unsupported version: expected {hex(Darc.DARC_VERSION)} got {hex(version)}")

        print(hex(version))
        print(f"file table offset is {hex(file_tab_off)}")
        print(f"file table is {hex(file_tab_len)} bytes long ({file_tab_len // 12} entries)")

        # read root entry
        _, _, num_entries = struct.unpack(Darc.FILE_TABLE_ENTRY.format(byte_order.struct), f.read(12))
        root = DarcEntry("", is_dir=True)

        raw_file_table = []
        for _ in range(num_entries - 1):
            raw_file_table.append(struct.unpack(Darc.FILE_TABLE_ENTRY.format(byte_order.struct), f.read(12)))

        name_table_start = f.tell()
        print(f"name table offset is {hex(name_table_start)}")

        # dir, count
        directory_stack = [[root, num_entries]]
        for name_offset, file_offset, length in raw_file_table:
            is_dir = (name_offset & 0x01000000) != 0
            name_offset &= ~0x01000000

            name = ""
            f.seek(name_table_start + name_offset, os.SEEK_SET)
            while (ch := f.read(2)) != b"\x00\x00":
                name += ch.decode(byte_order.wchar)

            entry = DarcEntry(name, is_dir)
            directory_stack[-1][0].add_child(entry)
            directory_stack[-1][1] -= 1

            # length is num entries for directory or file size for file
            if not is_dir:
                # read file content
                f.seek(file_dat_off + file_offset, os.SEEK_SET)
                entry.data = f.read(length)
            else:
                directory_stack.append([entry, length-3])  # why -3

            if directory_stack[-1][1] == 0:
                # no more entries left
                directory_stack.pop()

            print(name)
            print(is_dir, name_offset, file_offset, length)

        print(root)
        root.dump()

        arc = Darc(byte_order)
        arc.root_entry = root

        return arc


def test() -> None:
    with open("/home/joseph/Documents/tomodachi_life/workspaces/scripts/test/Game_US_English.bin", "rb") as f:
        fb = f.read()

    arc = Darc.from_bytes(fb)
    print(flush=True)
    assert arc.to_bytes() == fb


if __name__ == "__main__":
    test()
