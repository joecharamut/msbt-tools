from abc import ABC, abstractmethod
import os
import struct
import io
import typing
from typing import Dict

from lib.byteorder import ByteOrder, ByteOrderType


# module for LibMessageStudio files
# ref: https://github.com/kinnay/Nintendo-File-Formats/wiki/LMS-File-Format


def read_char(f: typing.BinaryIO, encoding: str) -> str:
    width = len("A".encode(encoding))
    return f.read(width).decode(encoding)


class LMSBlock(ABC):
    @staticmethod
    @abstractmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "LMSBlock":
        raise AssertionError

    @abstractmethod
    def to_bytes(self) -> bytes:
        raise AssertionError


class LMSUnknownBlock(LMSBlock):
    def __init__(self) -> None:
        self.data = bytes()

    @staticmethod
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "LMSUnknownBlock":
        block = LMSUnknownBlock()
        block.data = data
        return block

    def to_bytes(self) -> bytes:
        pass


class LMSHashTable(LMSBlock):
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
    def from_bytes(data: bytes, lms_file: "LMSFile") -> "LMSHashTable":
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

        tab = LMSHashTable(num_slots, byte_order, encoding)
        tab.labels = labels
        return tab

    def to_bytes(self) -> bytes:
        ...

    def __repr__(self) -> str:
        return f"<LMSHashTable slots={self.num_slots} labels={self.labels!r}>"


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


class Msbp:
    MSBP_MAGIC = b"MsgPrjBn"

    IDENT_STRUCT = "8s 2s"

    def __init__(self) -> None:
        ...

    def to_bytes(self) -> bytes:
        ...

    @staticmethod
    def from_bytes(data: bytes) -> "Msbp":
        lms = LMSFile.from_bytes(data)

        if lms.magic != Msbp.MSBP_MAGIC:
            raise TypeError(f"Invalid magic: expected {Msbp.MSBP_MAGIC!r} got {lms.magic!r}")

        section_types = {
            "CLR1": LMSUnknownBlock,
            "CLB1": LMSHashTable,
            "ATI2": LMSUnknownBlock,
            "ALB1": LMSHashTable,
            "ALI2": LMSUnknownBlock,
            "TGG2": LMSUnknownBlock,
            "TAG2": LMSUnknownBlock,
            "TGP2": LMSUnknownBlock,
            "TGL2": LMSUnknownBlock,
            "SYL3": LMSUnknownBlock,
            "SLB1": LMSHashTable,
            "CTI1": LMSUnknownBlock,
        }

        unpacked_sections = {}
        for block_type, data in lms.blocks.items():
            if block_type not in section_types:
                raise RuntimeError(f"Unhandled block type: {block_type}")
            unpacked_sections[block_type] = section_types[block_type].from_bytes(data, lms)

        # clb1 = LMSHashTable.from_bytes(lms.blocks["CLB1"], lms)
        # print(clb1)
        print(unpacked_sections)
