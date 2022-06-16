from abc import ABC, abstractmethod
import os
import struct
import io
import typing
from typing import Dict, Type, List, Any, Tuple

import hexdump

from lib.byteorder import ByteOrder, ByteOrderType


# module for LibMessageStudio files
# ref: https://github.com/kinnay/Nintendo-File-Formats/wiki/LMS-File-Format
# ￼


def read_char(f: typing.BinaryIO, encoding: str) -> str:
    width = len("A".encode(encoding))
    return f.read(width).decode(encoding)


def read_str(f: typing.BinaryIO, encoding: str, length: int = -1) -> str:
    if length == -1:
        s = ""
        while (c := read_char(f, encoding)) != "\0":
            s += c
        return s
    else:
        width = len("A".encode(encoding))
        return f.read(length * width).decode(encoding)


def align_buf(f: typing.BinaryIO, n: int, fill: bytes = b"\x00") -> int:
    remain = f.tell() % n
    if remain > 0:
        return f.write(fill * (n - remain))
    return 0


class LMSBlock(ABC):
    @staticmethod
    @abstractmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "LMSBlock":
        raise NotImplementedError

    @abstractmethod
    def to_bytes(self) -> bytes:
        raise NotImplementedError


# Start of common raw_blocks
class UnknownBlock(LMSBlock):
    def __init__(self) -> None:
        self.data = bytes()

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "UnknownBlock":
        block = UnknownBlock()
        block.data = data
        return block

    def to_bytes(self) -> bytes:
        return self.data


class HashTableBlock(LMSBlock):
    labels: dict[str, int]

    def __init__(self, num_slots: int, byte_order: ByteOrderType) -> None:
        self.num_slots = num_slots
        self.labels = {}
        self.byte_order = byte_order

    @staticmethod
    def hash(label: str, num_slots: int) -> int:
        val = 0
        for c in label:
            val = val * 0x492 + ord(c)
        return (val & 0xFFFFFFFF) % num_slots

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "HashTableBlock":
        f = io.BytesIO(data)
        byte_order = lms_file.byte_order

        num_slots, = byte_order.unpack("I", f.read(4))

        labels = {}
        for _ in range(num_slots):
            num_labels, labels_offset = byte_order.unpack("I I", f.read(8))

            pos = f.tell()
            if num_labels:
                f.seek(labels_offset, os.SEEK_SET)
                for _ in range(num_labels):
                    label_len, = byte_order.unpack("B", f.read(1))
                    label = ""
                    for _ in range(label_len):
                        label += read_char(f, "utf-8")
                    item, = byte_order.unpack("I", f.read(4))
                    labels[label] = item
                f.seek(pos, os.SEEK_SET)

        tab = HashTableBlock(num_slots, byte_order)
        tab.labels = labels
        return tab

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", self.num_slots))

        slots = {x: [] for x in range(self.num_slots)}
        for lbl, value in self.labels.items():
            slots[HashTableBlock.hash(lbl, self.num_slots)].append((lbl, value))

        slots_start = f.tell()
        f.write(b"\x00" * self.num_slots * 8)

        for hash_val, labels in slots.items():
            pos = f.tell()
            for lbl, val in labels:
                f.write(self.byte_order.pack("B", len(lbl)))
                f.write(lbl.encode("utf-8"))
                f.write(self.byte_order.pack("I", val))
            end = f.tell()

            f.seek(slots_start + (hash_val * 8), os.SEEK_SET)
            f.write(self.byte_order.pack("I I", len(labels), pos))
            f.seek(end, os.SEEK_SET)

        return f.getvalue()

    def __repr__(self) -> str:
        return f"<HashTableBlock slots={self.num_slots} labels={self.labels!r}>"
# End of common raw_blocks


# Start of MSBP file raw_blocks
class CLR1Block(LMSBlock):
    COLOR_STRUCT = "BBBB"

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN) -> None:
        self.colors = []
        self.byte_order = byte_order

    def __repr__(self) -> str:
        return f"<CLR1Block colors={self.colors!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "CLR1Block":
        f = io.BytesIO(data)

        colors = []
        num_colors, = lms_file.byte_order.unpack("I", f.read(4))
        for _ in range(num_colors):
            colors.append(lms_file.byte_order.unpack(CLR1Block.COLOR_STRUCT, f.read(4)))

        blk = CLR1Block()
        blk.colors = colors
        blk.byte_order = lms_file.byte_order
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", len(self.colors)))
        for c in self.colors:
            f.write(self.byte_order.pack(CLR1Block.COLOR_STRUCT, *c))

        return f.getvalue()


class ATI2Block(LMSBlock):
    ATTR_STRUCT = "BBHI"

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN) -> None:
        self.attributes = []
        self.byte_order = byte_order

    def __repr__(self) -> str:
        return f"<ATI2Block attributes={self.attributes!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "ATI2Block":
        f = io.BytesIO(data)

        attrs = []
        num_attrs, = lms_file.byte_order.unpack("I", f.read(4))
        for _ in range(num_attrs):
            attrs.append(lms_file.byte_order.unpack(ATI2Block.ATTR_STRUCT, f.read(8)))

        blk = ATI2Block()
        blk.attributes = attrs
        blk.byte_order = lms_file.byte_order
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", len(self.attributes)))
        for a in self.attributes:
            f.write(self.byte_order.pack(ATI2Block.ATTR_STRUCT, *a))

        return f.getvalue()


class ALI2Block(LMSBlock):
    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8"):
        self.byte_order = byte_order
        self.encoding = encoding
        self.lists = []

    def __repr__(self) -> str:
        return f"<ALI2Block lists={self.lists!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "ALI2Block":
        f = io.BytesIO(data)

        lists = []
        num_lists, = lms_file.byte_order.unpack("I", f.read(4))
        for _ in range(num_lists):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            f.seek(offset, os.SEEK_SET)

            names = []
            list_base = f.tell()
            list_items, = lms_file.byte_order.unpack("I", f.read(4))
            for _ in range(list_items):
                name_offset, = lms_file.byte_order.unpack("I", f.read(4))
                pos2 = f.tell()

                f.seek(list_base + name_offset, os.SEEK_SET)
                name = read_str(f, lms_file.encoding)

                names.append(name)
                f.seek(pos2, os.SEEK_SET)

            lists.append(names)
            f.seek(pos, os.SEEK_SET)

        blk = ALI2Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.lists = lists
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", len(self.lists)))
        f.write(b"\x00" * 4 * len(self.lists))

        for list_idx, l in enumerate(self.lists):
            list_pos = f.tell()
            f.seek(4 * (list_idx + 1), os.SEEK_SET)
            f.write(self.byte_order.pack("I", list_pos))
            f.seek(list_pos, os.SEEK_SET)

            list_base = f.tell()
            f.write(self.byte_order.pack("I", len(l)))
            f.write(b"\x00" * 4 * len(l))

            for string_idx, string in enumerate(l):
                string_pos = f.tell()
                f.write(string.encode(self.encoding))
                f.write(b"\x00")

                after = f.tell()

                f.seek(list_base + (4 * (string_idx + 1)), os.SEEK_SET)
                f.write(self.byte_order.pack("I", string_pos - list_base))
                f.seek(after, os.SEEK_SET)

            remain = f.tell() % 4
            if remain > 0:
                f.write(b"\x00" * (4 - remain))

        return f.getvalue()


class TGG2Block(LMSBlock):
    groups: List[Tuple[str, List[int]]]

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8") -> None:
        self.byte_order = byte_order
        self.encoding = encoding
        self.groups = []

    def __repr__(self) -> str:
        return f"<TGG2Block groups={self.groups!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "TGG2Block":
        f = io.BytesIO(data)

        groups = []
        num_groups, = lms_file.byte_order.unpack("H 2x", f.read(4))
        for _ in range(num_groups):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            f.seek(offset, os.SEEK_SET)
            num_tags, = lms_file.byte_order.unpack("H", f.read(2))
            tag_indexes = []
            for _ in range(num_tags):
                i, = lms_file.byte_order.unpack("H", f.read(2))
                tag_indexes.append(i)
            name = read_str(f, lms_file.encoding)
            groups.append((name, tag_indexes))
            f.seek(pos, os.SEEK_SET)

        blk = TGG2Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.groups = groups
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("H 2x", len(self.groups)))
        f.write(b"\x00" * 4 * len(self.groups))

        for i, (group, tags) in enumerate(self.groups):
            group_pos = f.tell()
            f.seek(4 * (i + 1), os.SEEK_SET)
            f.write(self.byte_order.pack("I", group_pos))
            f.seek(group_pos, os.SEEK_SET)

            f.write(self.byte_order.pack("H", len(tags)))
            for x in tags:
                f.write(self.byte_order.pack("H", x))
            f.write(group.encode(self.encoding))
            f.write(b"\x00")
            align_buf(f, 4)

        return f.getvalue()


class TAG2Block(LMSBlock):
    tags: List[Tuple[str, List[int]]]

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8") -> None:
        self.byte_order = byte_order
        self.encoding = encoding
        self.tags = []

    def __repr__(self) -> str:
        return f"<TAG2Block tags={self.tags!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "TAG2Block":
        f = io.BytesIO(data)

        tags = []
        num_tags, = lms_file.byte_order.unpack("H 2x", f.read(4))
        for _ in range(num_tags):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            f.seek(offset, os.SEEK_SET)
            num_params, = lms_file.byte_order.unpack("H", f.read(2))
            param_indexes = []
            for _ in range(num_params):
                i, = lms_file.byte_order.unpack("H", f.read(2))
                param_indexes.append(i)
            name = read_str(f, lms_file.encoding)
            tags.append((name, param_indexes))
            f.seek(pos, os.SEEK_SET)

        blk = TAG2Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.tags = tags
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("H 2x", len(self.tags)))
        f.write(b"\x00" * 4 * len(self.tags))

        for i, (tag, params) in enumerate(self.tags):
            group_pos = f.tell()
            f.seek(4 * (i + 1), os.SEEK_SET)
            f.write(self.byte_order.pack("I", group_pos))
            f.seek(group_pos, os.SEEK_SET)

            f.write(self.byte_order.pack("H", len(params)))
            for x in params:
                f.write(self.byte_order.pack("H", x))
            f.write(tag.encode(self.encoding))
            f.write(b"\x00")
            align_buf(f, 4)

        return f.getvalue()


class TGP2Block(LMSBlock):
    parameters: List[Tuple[str, int, List[int]]]

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8") -> None:
        self.byte_order = byte_order
        self.encoding = encoding
        self.parameters = []

    def __repr__(self) -> str:
        return f"<TGP2Block parameters={self.parameters!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "TGP2Block":
        f = io.BytesIO(data)

        params = []
        num_params, = lms_file.byte_order.unpack("H 2x", f.read(4))
        for _ in range(num_params):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            f.seek(offset, os.SEEK_SET)

            param_type, = lms_file.byte_order.unpack("B", f.read(1))

            if param_type != 9:
                name = read_str(f, lms_file.encoding)
                params.append((name, param_type, []))
            else:
                num_items, = lms_file.byte_order.unpack("1x H", f.read(3))
                items = []
                for _ in range(num_items):
                    i, = lms_file.byte_order.unpack("H", f.read(2))
                    items.append(i)
                name = read_str(f, lms_file.encoding)
                params.append((name, param_type, items))

            f.seek(pos, os.SEEK_SET)

        blk = TGP2Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.parameters = params
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("H 2x", len(self.parameters)))
        f.write(b"\x00" * 4 * len(self.parameters))

        for i, (name, param_type, items) in enumerate(self.parameters):
            group_pos = f.tell()
            f.seek(4 * (i + 1), os.SEEK_SET)
            f.write(self.byte_order.pack("I", group_pos))
            f.seek(group_pos, os.SEEK_SET)

            f.write(self.byte_order.pack("B", param_type))
            if param_type != 9:
                f.write(name.encode(self.encoding))
                f.write(b"\x00")
            else:
                f.write(self.byte_order.pack("1x H", len(items)))
                for x in items:
                    f.write(self.byte_order.pack("H", x))
                f.write(name.encode(self.encoding))
                f.write(b"\x00")
            align_buf(f, 4)

        return f.getvalue()


class TGL2Block(LMSBlock):
    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8"):
        self.byte_order = byte_order
        self.encoding = encoding
        self.names = []

    def __repr__(self) -> str:
        return f"<TGL2Block names={self.names!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "TGL2Block":
        f = io.BytesIO(data)

        names = []
        items, = lms_file.byte_order.unpack("H 2x", f.read(4))
        for _ in range(items):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            f.seek(offset, os.SEEK_SET)
            name = read_str(f, lms_file.encoding)
            names.append(name)
            f.seek(pos, os.SEEK_SET)

        blk = TGL2Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.names = names
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("H 2x", len(self.names)))

        # reserve space for offsets
        f.write(b"\x00" * 4 * len(self.names))

        for i, name in enumerate(self.names):
            pos = f.tell()
            f.seek(4 + (4 * i), os.SEEK_SET)
            f.write(self.byte_order.pack("I", pos))
            f.seek(pos, os.SEEK_SET)
            f.write(name.encode(self.encoding))
            f.write(b"\x00")

        return f.getvalue()


class SYL3Block(LMSBlock):
    STYLE_STRUCT = "IIii"

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN) -> None:
        self.byte_order = byte_order
        self.styles = []

    def __repr__(self) -> str:
        return f"<SYL3Block styles={self.styles!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "SYL3Block":
        f = io.BytesIO(data)

        styles = []
        num, = lms_file.byte_order.unpack("I", f.read(4))
        for _ in range(num):
            styles.append(lms_file.byte_order.unpack(SYL3Block.STYLE_STRUCT, f.read(16)))

        blk = SYL3Block()
        blk.byte_order = lms_file.byte_order
        blk.styles = styles
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", len(self.styles)))
        for a in self.styles:
            f.write(self.byte_order.pack(SYL3Block.STYLE_STRUCT, *a))

        return f.getvalue()


class CTI1Block(LMSBlock):
    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8"):
        self.byte_order = byte_order
        self.encoding = encoding
        self.filenames = []

    def __repr__(self) -> str:
        return f"<CTI1Block filenames={self.filenames!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "CTI1Block":
        f = io.BytesIO(data)

        filenames = []
        num_filenames, = lms_file.byte_order.unpack("I", f.read(4))
        for _ in range(num_filenames):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            name = ""
            f.seek(offset, os.SEEK_SET)

            while (ch := read_char(f, lms_file.encoding)) != "\0":
                name += ch

            filenames.append(name)
            f.seek(pos, os.SEEK_SET)

        blk = CTI1Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.filenames = filenames
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", len(self.filenames)))

        # reserve space for offsets
        f.write(b"\x00"*4*len(self.filenames))

        for i, name in enumerate(self.filenames):
            pos = f.tell()
            f.seek(4 + (4 * i), os.SEEK_SET)
            f.write(self.byte_order.pack("I", pos))
            f.seek(pos, os.SEEK_SET)
            f.write(name.encode(self.encoding))
            f.write(b"\x00")

        return f.getvalue()
# End of MSBP file raw_blocks


# Start of MSBT file raw_blocks
class TXT2Block(LMSBlock):
    messages: List[Tuple[str, List[Tuple[int, int, bytes]]]]

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN, encoding: str = "utf-8") -> None:
        self.byte_order = byte_order
        self.encoding = encoding
        self.messages = []

    def __repr__(self) -> str:
        return f"<TXT2Block messages={self.messages!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "TXT2Block":
        f = io.BytesIO(data)

        messages = []
        num_messages, = lms_file.byte_order.unpack("I", f.read(4))
        for i in range(num_messages):
            offset, = lms_file.byte_order.unpack("I", f.read(4))
            pos = f.tell()
            f.seek(offset, os.SEEK_SET)

            msg = ""
            tags = []

            width = len("A".encode(lms_file.encoding))
            ch = None
            while ch != "\0":
                char_bytes = f.read(width)
                ch = char_bytes.decode(lms_file.encoding)

                if ch == "\0":
                    break

                if ch == "\x0E":
                    tag_group, tag_type, param_size = lms_file.byte_order.unpack("HHH", f.read(6))
                    param_data = f.read(param_size)
                    tags.append((tag_group, tag_type, param_data))
                    msg += "￼"
                elif b"\xE0" in char_bytes:
                    # seems to be xx E0 for a button label (shorthand?)
                    button = char_bytes.replace(b"\xE0", b"")
                    tags.append((-1, -1, button))
                    msg += "￼"
                else:
                    msg += ch
            messages.append((msg, tags))
            f.seek(pos, os.SEEK_SET)

        blk = TXT2Block()
        blk.byte_order = lms_file.byte_order
        blk.encoding = lms_file.encoding
        blk.messages = messages
        return blk

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class ATR1Block(LMSBlock):
    # TODO: research this further
    # TODO: DONT USE THIS just use the unknown one so no editing

    # ATR1 Block Format:
    # Most likely is game independent, but i need it for Tomodachi Life
    # OFFSET | SIZE | DESCRIPTION
    # 0x0    |   4  | Number of attributes
    # 0x4    |   4  | Bytes per attribute
    # ...    |   x  | Attributes
    # ...    |   x  | Strings (UTF-16?)
    #
    # Attribute format (as far as i can guess)
    # OFFSET | SIZE | DESCRIPTION
    # 0x00   |   4  | Always zero?
    # 0x04   |   4  | String offset (name?)
    # 0x08   |   4  | String offset (unknown)
    # 0x0C   |   4  | String offset (unknown)
    # 0x10   |   4  | String offset (unknown)
    # 0x14   |   4  | String offset (unknown)
    # 0x18   |  36  | Rest of attribute

    def __init__(self, byte_order: ByteOrderType = ByteOrder.LITTLE_ENDIAN) -> None:
        self.byte_order = byte_order
        self.data = bytes()
        self.attributes = []
        self.strings = []

    def __repr__(self) -> str:
        return f"<ATR1Block attributes={[a[0] for a in self.attributes]!r}>"

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "ATR1Block":
        f = io.BytesIO(data)

        attrs = []
        strings = []
        num_attrs, bytes_per_attr = lms_file.byte_order.unpack("I I", f.read(8))
        if bytes_per_attr != 0:
            for _ in range(num_attrs):
                a = f.read(bytes_per_attr)

                str_off, = lms_file.byte_order.unpack("I", a[4:8])
                pos = f.tell()
                f.seek(str_off, os.SEEK_SET)
                name = read_str(f, lms_file.encoding)
                attrs.append((name, a))
                f.seek(pos, os.SEEK_SET)

            offs = {}
            if f.tell() < len(data):
                # print("guessing a string table (prepare for danger)")
                while f.tell() < len(data):
                    # print(f"start of string: {f.tell()}")
                    off = f.tell()
                    string = read_str(f, lms_file.encoding)
                    strings.append(string)
                    offs[off] = string

            for name, attr in attrs:
                buf = io.BytesIO(attr)
                # check every int why not
                for i in range(0, len(attr), 4):
                    val, = lms_file.byte_order.unpack("I", buf.read(4))
                    if val in offs:
                        print(f"possible string: attr offset {hex(i)}={val} => {offs[val]!r}")

        blk = ATR1Block()
        blk.byte_order = lms_file.byte_order
        blk.data = data
        blk.attributes = attrs
        blk.strings = strings
        return blk

    def to_bytes(self) -> bytes:
        return self.data
# End of MSBT file raw_blocks


class LMSFile:
    LMS_IDENT = "8s 2s"
    LMS_HEADER = "2x B B H 2x I 10x"
    BLK_HEADER = "4s I 8x"

    LMS_VERSION = 0x00000003

    raw_blocks: dict[str, bytes]
    blocks: dict[str, LMSBlock]

    def __init__(self) -> None:
        self.magic = b""
        self.byte_order = ByteOrder.LITTLE_ENDIAN
        self.encoding = "utf-8"
        self.raw_blocks = {}
        self.blocks = {}

    def _read_header(self, data: bytes) -> None:
        f = io.BytesIO(data)

        magic, bom = struct.unpack(LMSFile.LMS_IDENT, f.read(10))
        byte_order = ByteOrder.from_bom(bom)

        enc_type, version, num_blocks, filesize = byte_order.unpack(LMSFile.LMS_HEADER, f.read(22))

        if version != LMSFile.LMS_VERSION:
            raise ValueError(f"Unsupported LMS file version! expected {hex(LMSFile.LMS_VERSION)} got {hex(version)}")

        if enc_type == 0:
            encoding = "utf-8"
        elif enc_type == 1:
            encoding = "utf-16-" + byte_order.suffix
        elif enc_type == 2:
            encoding = "utf-32-" + byte_order.suffix
        else:
            raise ValueError(f"Invalid encoding type! expected [0, 1, 2] got {enc_type}")

        blocks = {}
        while len(blocks) < num_blocks:
            block_type, block_size = byte_order.unpack(LMSFile.BLK_HEADER, f.read(16))
            block_type = block_type.decode("ascii")
            block_data = f.read(block_size)
            blocks[block_type] = block_data

            # align buffer to 0x10 bytes
            rem = f.tell() % 16
            if rem > 0:
                f.seek((16 - rem), os.SEEK_CUR)

        self.magic = magic
        self.byte_order = byte_order
        self.encoding = encoding
        self.raw_blocks = blocks

    def _write_header(self, f: typing.BinaryIO) -> None:
        # ident
        f.write(self.magic)
        f.write(self.byte_order.bom)

        # header data
        encoding_num = 0
        if self.encoding == "utf-8":
            encoding_num = 0
        elif self.encoding.startswith("utf-16"):
            encoding_num = 1
        elif self.encoding.startswith("utf-32"):
            encoding_num = 2

        f.write(self.byte_order.pack(
            LMSFile.LMS_HEADER,
            encoding_num,
            LMSFile.LMS_VERSION,
            len(self.blocks),
            0,  # fill in filesize later
        ))

    def _parse_blocks(self, types: Dict[str, Type[LMSBlock]], debug: bool = False):
        unpacked_sections: Dict[str, LMSBlock] = {}
        for block_type, data in self.raw_blocks.items():
            if block_type not in types:
                raise RuntimeError(f"Unhandled block type: {block_type}")

            unpacked_sections[block_type] = types[block_type].from_bytes(data, self)

            debug_raise_errors = False
            if debug:
                # todo debugging
                try:
                    new = unpacked_sections[block_type].to_bytes()
                    assert new == data
                    print(f"[{'?' if isinstance(unpacked_sections[block_type], UnknownBlock) else '✓'}] {block_type}")
                except AssertionError:
                    print(f"[✗] {block_type} (assert failed)")
                    hexdump.hexdump(new)
                    print("/\\new   old\\/")
                    hexdump.hexdump(data)
                    if debug_raise_errors:
                        raise
                except NotImplementedError:
                    print(f"[✗] {block_type} (not implemented)")
                    if debug_raise_errors:
                        raise
        self.blocks = unpacked_sections

    def _write_blocks(self, f: typing.BinaryIO) -> None:
        for block_type, block in self.blocks.items():
            block_data = block.to_bytes()
            f.write(self.byte_order.pack(
                LMSFile.BLK_HEADER,
                block_type.encode("ascii"),
                len(block_data),
            ))
            f.write(block_data)
            align_buf(f, 0x10, b"\xAB")

    def to_bytes(self) -> bytes:
        f = io.BytesIO()
        self._write_header(f)
        self._write_blocks(f)

        size = f.tell()
        f.seek(18, os.SEEK_SET)
        f.write(self.byte_order.pack("I", size))

        return f.getvalue()


class LMSProjectFile(LMSFile):
    MAGIC: bytes = b"MsgPrjBn"
    SECTIONS: Dict[str, Type[LMSBlock]] = {
        "CLR1": CLR1Block,
        "CLB1": HashTableBlock,
        "ATI2": ATI2Block,
        "ALB1": HashTableBlock,
        "ALI2": ALI2Block,
        "TGG2": TGG2Block,
        "TAG2": TAG2Block,
        "TGP2": TGP2Block,
        "TGL2": TGL2Block,
        "SYL3": SYL3Block,
        "SLB1": HashTableBlock,
        "CTI1": CTI1Block,
    }

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def from_bytes(data: bytes) -> "LMSProjectFile":
        prj = LMSProjectFile()
        prj._read_header(data)

        if prj.magic != LMSProjectFile.MAGIC:
            raise TypeError(f"Invalid magic: expected {LMSProjectFile.MAGIC!r} got {prj.magic!r}")

        prj._parse_blocks(LMSProjectFile.SECTIONS)

        return prj

    @property
    def tgg2(self) -> TGG2Block:
        return self.blocks["TGG2"]

    @property
    def tag2(self) -> TAG2Block:
        return self.blocks["TAG2"]

    @property
    def tgp2(self) -> TGP2Block:
        return self.blocks["TGP2"]

    @property
    def tgl2(self) -> TGL2Block:
        return self.blocks["TGL2"]


class LMSStandardFile(LMSFile):
    MAGIC: bytes = b"MsgStdBn"
    SECTIONS: Dict[str, Type[LMSBlock]] = {
        "LBL1": HashTableBlock,
        "ATR1": UnknownBlock,
        "TXT2": TXT2Block,
    }

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def from_bytes(data: bytes) -> "LMSStandardFile":
        msg = LMSStandardFile()
        msg._read_header(data)

        if msg.magic != LMSStandardFile.MAGIC:
            raise TypeError(f"Invalid magic: expected {LMSStandardFile.MAGIC!r} got {msg.magic!r}")

        msg._parse_blocks(LMSStandardFile.SECTIONS)

        return msg

    @property
    def lbl1(self) -> HashTableBlock:
        return self.blocks["LBL1"]

    @property
    def txt2(self) -> TXT2Block:
        return self.blocks["TXT2"]

    @property
    def atr1(self) -> UnknownBlock:
        return self.blocks["ATR1"]


class LMSFlowFile(LMSFile):
    MAGIC: bytes = b"MsgFlwBn"
    SECTIONS: Dict[str, Type[LMSBlock]] = {
        "FLW3": UnknownBlock,
        "FEN1": HashTableBlock,
    }

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def from_bytes(data: bytes) -> "LMSFlowFile":
        flw = LMSFlowFile()
        flw._read_header(data)

        if flw.magic != LMSFlowFile.MAGIC:
            raise TypeError(f"Invalid magic: expected {LMSFlowFile.MAGIC!r} got {flw.magic!r}")

        flw._parse_blocks(LMSFlowFile.SECTIONS)

        return flw
