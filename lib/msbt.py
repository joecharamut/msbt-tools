import struct
import io
import typing

from hexdump import hexdump

from lib.buffer import ByteBuffer


class MsbtFormatException(Exception):
    pass


class Msbt:
    def __init__(self, buf: typing.BinaryIO, debug=False) -> None:
        self.debug = debug
        self.data = buf

        self.lbl1 = {}
        self.lbl1_indexed = {}
        self.atr1 = None
        self.txt2 = []

        # seek to end
        buf.seek(0, 2)
        self.buf_len = buf.tell()
        buf.seek(0)

        header = self.data.read(0x20)
        magic, bom, encoding, self.sections, file_size = struct.unpack("8s 2s 2x B x H 2x I 8x", header)

        if magic != b"MsgStdBn":
            raise MsbtFormatException("Invalid magic")

        if bom != b"\xFF\xFE" and bom != b"\xFE\xFF":
            raise MsbtFormatException("Invalid endianness")

        fpos = self.data.tell()
        while fpos < self.buf_len:
            section_start = self.data.tell()
            section_id = self.data.read(4)
            # print(f"section id: {section_id}")

            self.dbg(f"[MSBT]: Found section: {section_id.decode()}")
            if section_id == b"LBL1":
                self._read_lbl1(section_start)
            elif section_id == b"ATR1":
                self._read_atr1(section_start)
            elif section_id == b"TXT2":
                self._read_txt2(section_start)
            else:
                print(f"unk section: {section_id} at {self.data.tell()}")
                self.data.seek(0)
                print(hexdump(self.data))
                exit()
                break

            fpos = self.data.tell()
    
    def dbg(self, message):
        if self.debug:
            print(message)

    def __repr__(self) -> str:
        return f"<Msbt filesize={self.buf_len} sections={self.sections}>"

    def _read_lbl1(self, section_start) -> None:
        size, = struct.unpack("I", self.data.read(4))
        self.data.seek(8, 1)  # padding

        start_of_labels = self.data.tell()
        num_groups, = struct.unpack("I", self.data.read(4))

        self.dbg(f"[LBL1]: section has {num_groups} groups")

        groups = []
        num_strings = 0
        for i in range(num_groups):
            num_labels, offset = struct.unpack("I I", self.data.read(8))
            num_strings += num_labels
            groups.append((i, num_labels, offset))
            self.lbl1[i] = {}
        
        self.dbg(f"[LBL1]: section has {num_strings} labels")

        for group_num, num_labels, offset in groups:
            self.data.seek(start_of_labels + offset)
            for i in range(num_labels):
                length, = struct.unpack("B", self.data.read(1))
                name = self.data.read(length)
                index, = struct.unpack("I", self.data.read(4))
                self.lbl1[group_num][index] = name
                self.lbl1_indexed[index] = name
                self.dbg(f"[LBL1]: string {index} (group {group_num}) = {name}")

        # correct alignment
        remainder = self.data.tell() % 16
        if remainder > 0:
            self.data.seek(16 - remainder, 1)

    def _read_atr1(self, section_start) -> None:
        size, = struct.unpack("I 8x", self.data.read(12))
        num_attributes, attribute_size = struct.unpack("I I", self.data.read(8))
        self.atr1 = self.data.read(size)
        # print(f"size: {size}, num_attributes: {num_attributes}, attribute_size: {attribute_size}")
        self.data.seek(-8, 1)  # size - 4 bytes, but why?

        # correct alignment
        remainder = self.data.tell() % 16
        if remainder > 0:
            self.data.seek(16 - remainder, 1)

    def _read_txt2(self, section_start) -> None:
        size, num_entries = struct.unpack("I 8x I", self.data.read(0x10))
        end_of_header = self.data.tell()
        end_of_section = section_start + 0x1E + size

        self.dbg(f"[TXT2] section has {num_entries} text entries")

        entry_offsets = []
        for i in range(num_entries):
            off, = struct.unpack("I", self.data.read(4))
            entry_offsets.append(off)
        
        entry = bytearray()
        for i, off in enumerate(entry_offsets):
            self.data.seek(end_of_header + off - 4)
            start = self.data.tell()

            end = end_of_section
            if i < len(entry_offsets)-1:
                end = end_of_header + entry_offsets[i+1] - 4
            
            self.dbg(f"[TXT2]: entry {i} should be {end - start} bytes long?")
            
            # entry = self.data.read(end - start).replace(b"\xAB\xAB", b"")
            b = None
            idx = 0
            while b != b"\xAB\xAB" and idx < (end - start):
               b = self.data.read(2)
               idx += 2
               entry.extend(b)
            # entry = entry[:-2]
            self.txt2.append(entry)
            # self.dbg(f"[TXT2]: string {i} = {dump(entry)}")
            entry = bytearray()
        
        # print(f"size: {size}, num_entries: {num_entries}")
        self.data.seek(section_start + 0x1E + size)
        
        # correct alignment
        remainder = self.data.tell() % 16
        if remainder > 0:
            self.data.seek(16 - remainder, 1)

    @staticmethod
    def from_bytes(data: bytes, debug=False) -> "Msbt":
        return Msbt(io.BytesIO(data), debug)

    @staticmethod
    def _txt2_handle_control_seq(buf: ByteBuffer) -> str:
        # account for shifting out control char
        buf.seek(buf.tell() - 2)
        header = buf.read(8)
        ctrl_chr, ctrl_type, ctrl_subtype, extra_len = struct.unpack("HHHH", header)

        extra = bytes()
        if extra_len:
            extra = buf.read(extra_len)

        print(f"header: [{header.hex(' ')}] +{extra_len} extra => [{extra.hex(' ')}]", end="")

        if ctrl_type == 0x0000 and ctrl_subtype == 0x0003:
            if extra == b"\x00\x00\x00\xFF":
                print(" (end text block)")
                return "{END_TEXT}"
            else:
                print(" (begin text block)")
                return f"{{BEGIN_TEXT attrs=[{extra.hex(' ')}]}}"
        elif ctrl_type == 0x0004 and ctrl_subtype == 0x000b:
            if extra == b"\x00\x00":
                print(" (island name)")
                return "{ISLAND_NAME}"
            else:
                print(" (unknown (island related?))")
        elif ctrl_type == 0x0008:  # and ctrl_subtype == 0x0000:
            extra_buf = ByteBuffer(extra)

            cond = bytes()
            if ctrl_subtype != 0x0001:
                cond = extra_buf.read(2)

            first_len = extra_buf.read_u16()
            first_str = extra_buf.read(first_len).decode("utf-16le")

            second_len = extra_buf.read_u16()
            second_str = extra_buf.read(second_len).decode("utf-16le")

            print(f" (if cond={cond.hex(' ')!r} T={first_str!r} F={second_str!r})")
            return f"{{IF cond=[{cond.hex(' ')}] true=[{first_str}] false=[{second_str}]}}"
        elif ctrl_type == 0x0001 and ctrl_subtype == 0x0000:
            if extra == b"\x01\x00\x00\xcd":
                print(" (mii name)")
                return "{MII_NAME}"
            else:
                print(" (unknown (mii related?))")
        else:
            print(" (unknown (unknown))")

        return f"{{? [{header.hex(' ')} {extra.hex(' ')}]}}"

    @staticmethod
    def decode_txt2_entry(entry: bytes, debug=False) -> str:
        def dbg(msg) -> None:
            if debug:
                print(msg)

        raw_buf = ByteBuffer(entry)
        output_str = ""
        while raw_buf.tell() < len(entry) - 1:
            char = raw_buf.read_wchar16le()

            if char == "\x00":
                break
            elif char == "\x0E":
                output_str += Msbt._txt2_handle_control_seq(raw_buf)
            else:
                output_str += char

        return output_str
