from abc import ABC, abstractmethod
import os
import struct
import io
import typing
from typing import Dict, Type

from lib.byteorder import ByteOrder, ByteOrderType


# module for LibMessageStudio files
# ref: https://github.com/kinnay/Nintendo-File-Formats/wiki/LMS-File-Format
# ￼


def read_char(f: typing.BinaryIO, encoding: str) -> str:
    width = len("A".encode(encoding))
    return f.read(width).decode(encoding)


def write_char(f: typing.BinaryIO, encoding: str, ch: str) -> int:
    return f.write(ch.encode(encoding))


class LMSBlock(ABC):
    @staticmethod
    @abstractmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "LMSBlock":
        raise NotImplementedError

    @abstractmethod
    def to_bytes(self) -> bytes:
        raise NotImplementedError


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
    def __init__(self, num_slots: int, byte_order: ByteOrderType, encoding: str) -> None:
        self.num_slots = num_slots
        self.labels = {}
        self.byte_order = byte_order
        self.encoding = encoding

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
        encoding = lms_file.encoding

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
                        label += read_char(f, encoding)
                    item, = byte_order.unpack("I", f.read(4))
                    labels[label] = item
                f.seek(pos, os.SEEK_SET)

        tab = HashTableBlock(num_slots, byte_order, encoding)
        tab.labels = labels
        return tab

    def to_bytes(self) -> bytes:
        ...

    def __repr__(self) -> str:
        return f"<HashTableBlock slots={self.num_slots} labels={self.labels!r}>"


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
        blk.attrs = attrs
        blk.byte_order = lms_file.byte_order
        return blk

    def to_bytes(self) -> bytes:
        f = io.BytesIO()

        f.write(self.byte_order.pack("I", len(self.attributes)))
        for a in self.attributes:
            f.write(self.byte_order.pack(ATI2Block.ATTR_STRUCT, *a))

        return f.getvalue()


class SYL3Block(LMSBlock):
    STYLE_STRUCT = "IIIi"

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


class LMSFile:
    LMS_IDENT = "8s 2s"
    LMS_HEADER = "2x B B H 2x I 10x"
    BLK_HEADER = "4s I 8x"

    LMS_VERSION = 0x00000003

    def __init__(self) -> None:
        self.magic = b""
        self.byte_order = ByteOrder.LITTLE_ENDIAN
        self.encoding = "utf-8"
        self.blocks = {}

    @staticmethod
    def from_bytes(data: bytes) -> "LMSFile":
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

        lms = LMSFile()
        lms.magic = magic
        lms.byte_order = byte_order
        lms.encoding = encoding
        lms.blocks = blocks
        return lms

    def to_bytes(self) -> bytes:
        raise NotImplementedError


class LMSProjectFile:
    MSBP_MAGIC = b"MsgPrjBn"

    IDENT_STRUCT = "8s 2s"

    def __init__(self) -> None:
        ...

    def to_bytes(self) -> bytes:
        ...

    @staticmethod
    def from_bytes(data: bytes) -> "LMSProjectFile":
        lms = LMSFile.from_bytes(data)

        if lms.magic != LMSProjectFile.MSBP_MAGIC:
            raise TypeError(f"Invalid magic: expected {LMSProjectFile.MSBP_MAGIC!r} got {lms.magic!r}")

        section_types: Dict[str, Type[LMSBlock]] = {
            "CLR1": CLR1Block,
            "CLB1": HashTableBlock,
            "ATI2": ATI2Block,
            "ALB1": HashTableBlock,
            "ALI2": UnknownBlock,
            "TGG2": UnknownBlock,
            "TAG2": UnknownBlock,
            "TGP2": UnknownBlock,
            "TGL2": UnknownBlock,
            "SYL3": SYL3Block,
            "SLB1": HashTableBlock,
            "CTI1": CTI1Block,
        }

        unpacked_sections: Dict[str, LMSBlock] = {}
        for block_type, data in lms.blocks.items():
            if block_type not in section_types:
                raise RuntimeError(f"Unhandled block type: {block_type}")
            unpacked_sections[block_type] = section_types[block_type].from_bytes(data, lms)

        for k, v in unpacked_sections.items():
            print(f"{k}: {v!r}")

        assert unpacked_sections["CLR1"].to_bytes() == lms.blocks["CLR1"]
        assert unpacked_sections["SYL3"].to_bytes() == lms.blocks["SYL3"]
        assert unpacked_sections["CTI1"].to_bytes() == lms.blocks["CTI1"]
