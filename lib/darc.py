import io
import os
import struct
from typing import NamedTuple, List, Optional, Generator, Any
from collections import namedtuple

from lib.byteorder import ByteOrder

# darc format reference:
#   http://web.archive.org/web/20211123124701/http://problemkaputt.de/gbatek-3ds-files-archive-darc.htm


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
        return f"<DarcEntry '{self.name}' {'directory' if self._is_dir else 'file'} length={self.length}>"

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
        child._parent = self
        self._children.append(child)

    def remove_child(self, child: "DarcEntry") -> None:
        if not self._is_dir:
            raise TypeError("Cannot remove children of a file")
        child._parent = None
        self._children.remove(child)

    @property
    def filepath(self) -> str:
        stack = []
        node: Optional[DarcEntry] = self
        while node is not None:
            stack.append(node.name)
            node = node._parent
        stack.reverse()
        return "/".join(stack)

    def flat_tree(self) -> Generator["DarcEntry", None, None]:
        yield self
        if self._is_dir:
            for node in self._children:
                yield from node.flat_tree()

    def breadth_tree(self) -> Generator["DarcEntry", None, None]:
        if self._is_dir:
            for node in self._children:
                if node._is_dir:
                    yield from node.breadth_tree()
            for node in self._children:
                if not node._is_dir:
                    yield from node.breadth_tree()
        yield self

    def dir_entry_size(self) -> int:
        i = 1
        if self._is_dir:
            for node in self._children:
                i += node.dir_entry_size()
        return i

    @property
    def is_dir(self) -> bool:
        return self._is_dir

    @property
    def parent(self) -> Optional["DarcEntry"]:
        return self._parent

    @property
    def children(self) -> List["DarcEntry"]:
        if not self._is_dir:
            raise TypeError("Files cannot have children")
        return self._children

    def __eq__(self, other) -> bool:
        if self is other:
            return True

        if not isinstance(other, DarcEntry):
            return False

        return \
            self._is_dir == other._is_dir and \
            self.name == other.name and \
            self._data == other._data and \
            self._parent == other._parent and \
            self._children == other._children


class Darc:
    DARC_MAGIC = b"darc"
    DARC_VERSION = 0x1000000

    IDENT_STRUCT = "4s 2s"  # b"darc" and BOM
    HEADER_STRUCT = "H I I I I I"  # endian dependant fields
    FILE_TABLE_ENTRY = "I I I"

    def __init__(self, byte_order=ByteOrder.LITTLE_ENDIAN) -> None:
        self.byte_order = byte_order
        self._root_entry = DarcEntry("", is_dir=True)

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()

        # write ident magic
        buf.write(Darc.DARC_MAGIC)
        buf.write(self.byte_order.bom)

        # write header
        buf.write(self.byte_order.pack(
            Darc.HEADER_STRUCT,
            0x1C,               # header length
            Darc.DARC_VERSION,  # version
            0xFFFFFFFF,         # file length
            0x1C,               # file table offset
            0xFFFFFFFF,         # file table length
            0xFFFFFFFF,         # file data offset
        ))

        name_table = io.BytesIO()
        filename_to_index = {None: 0, self._root_entry.filepath: 0}
        i = 0
        for e in self._root_entry.flat_tree():
            name_offset = name_table.tell()
            name_table.write(e.name.encode(self.byte_order.wchar))
            name_table.write(b"\x00\x00")

            buf.write(self.byte_order.pack(
                Darc.FILE_TABLE_ENTRY,
                name_offset | (0x01000000 if e.is_dir else 0),
                filename_to_index[e.parent.filepath if e.parent else None] if e.is_dir else 0,
                i + e.dir_entry_size() if e.is_dir else e.length,
            ))

            filename_to_index[e.filepath] = i

            i += 1

        # write out name table at end of file headers
        buf.write(name_table.getvalue())

        name_table_end = buf.tell()
        file_table_length = name_table_end - 0x1C
        buf.seek(0x14, os.SEEK_SET)
        buf.write(self.byte_order.pack("I", file_table_length))
        buf.seek(name_table_end, os.SEEK_SET)

        def align(b: io.BytesIO):
            pos = b.tell()
            extra = pos % 0x20
            if extra > 0:
                b.write(b"\x00"*(0x20 - extra))

        align(buf)
        file_data_start = buf.tell()
        buf.seek(0x18, os.SEEK_SET)
        buf.write(self.byte_order.pack("I", file_data_start))
        buf.seek(file_data_start, os.SEEK_SET)

        for e in self._root_entry.breadth_tree():
            if e.is_dir:
                continue

            align(buf)
            file_pos = buf.tell()
            buf.write(e.data)
            file_end = buf.tell()

            # seek to file table
            buf.seek(0x1C, os.SEEK_SET)
            # entry of this file
            buf.seek(0xC * filename_to_index[e.filepath], os.SEEK_CUR)
            # first u32 is name offset
            buf.seek(0x4, os.SEEK_CUR)
            # write entry data
            buf.write(self.byte_order.pack("I", file_pos))
            buf.write(self.byte_order.pack("I", e.length))

            # seek back
            buf.seek(file_end, os.SEEK_SET)

            i += 1

        buf.seek(0, os.SEEK_END)
        file_size = buf.tell()
        buf.seek(0xC, os.SEEK_SET)
        buf.write(self.byte_order.pack("I", file_size))

        return buf.getvalue()

    @staticmethod
    def from_bytes(data: bytes) -> "Darc":
        f = io.BytesIO(data)

        magic, bom = struct.unpack(Darc.IDENT_STRUCT, f.read(6))
        if magic != Darc.DARC_MAGIC:
            raise TypeError(f"Invalid magic: expected {Darc.DARC_MAGIC!r} got {magic!r}")

        byte_order = ByteOrder.LITTLE_ENDIAN
        if bom == b"\xFF\xFE":
            byte_order = ByteOrder.LITTLE_ENDIAN
        elif bom == b"\xFE\xFF":
            byte_order = ByteOrder.BIG_ENDIAN
        else:
            print("Warning: Darc file has invalid endian marker (defaulting to little endian)")

        header_len, version, file_size, file_tab_off, file_tab_len, file_dat_off = \
            byte_order.unpack(Darc.HEADER_STRUCT, f.read(22))

        if version != Darc.DARC_VERSION:
            raise TypeError(f"Unsupported version: expected {hex(Darc.DARC_VERSION)} got {hex(version)}")

        # read root entry
        _, _, end_index = byte_order.unpack(Darc.FILE_TABLE_ENTRY, f.read(12))
        root = DarcEntry("", is_dir=True)

        raw_file_table = []
        for _ in range(end_index - 1):
            raw_file_table.append(byte_order.unpack(Darc.FILE_TABLE_ENTRY, f.read(12)))

        name_table_start = f.tell()

        # dir, end
        StackItem = namedtuple("StackItem", "node end")
        directory_stack = [StackItem(root, end_index)]
        for i, (name_offset, file_offset, length) in enumerate(raw_file_table):
            if directory_stack[-1].end == i:
                # at end index
                directory_stack.pop()

            is_dir = (name_offset & 0x01000000) != 0
            name_offset &= ~0x01000000

            name = ""
            f.seek(name_table_start + name_offset, os.SEEK_SET)
            while (ch := f.read(2)) != b"\x00\x00":
                name += ch.decode(byte_order.wchar)

            entry = DarcEntry(name, is_dir)
            directory_stack[-1].node.add_child(entry)

            # length is end index for directory or file size for file
            if not is_dir:
                # read file content
                f.seek(file_offset, os.SEEK_SET)
                entry.data = f.read(length)
            else:
                directory_stack.append(StackItem(entry, length - 1))

        arc = Darc(byte_order)
        arc._root_entry = root

        return arc

    def entries(self) -> Generator[DarcEntry, None, None]:
        yield from self._root_entry.flat_tree()

    def add_file(self, path: str, data: bytes) -> DarcEntry:
        split = path.split("/")

        file_entry = DarcEntry(split.pop(), is_dir=False)
        file_entry.data = data

        node = None
        if split[0] == "":
            split.pop(0)
            node = self._root_entry

        while split and node:
            dir_name = split.pop(0)
            for c in node.children:
                if c.is_dir and c.name == dir_name:
                    node = c
                    break
            else:
                new_dir = DarcEntry(dir_name, is_dir=True)
                node.add_child(new_dir)
                node = new_dir

        if not node:
            raise RuntimeError("Error finding parent node for file (this should never happen)")

        node.add_child(file_entry)
        return file_entry
