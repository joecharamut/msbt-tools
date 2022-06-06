import io
import os
from pathlib import Path
from typing import Dict
import struct
from base64 import b64encode, b64decode
import argparse
import enum

import lxml.etree
import lxml.builder
from lxml.etree import _Element as XMLElement

import nlzss11

from lib.lms import LMSProjectFile
from lib.msbt import Msbt
from lib.darc import Darc, DarcEntry
from lib.buffer import ByteBuffer


class AutoFileType(enum.Enum):
    UNKNOWN_FILE = enum.auto()
    MSBT_FILE = enum.auto()
    MSBP_FILE = enum.auto()
    MSBF_FILE = enum.auto()
    DARC_FILE = enum.auto()
    LZ11_FILE = enum.auto()


def guess_file_type(data: bytes) -> AutoFileType:
    if data[0] == 0x11:
        return AutoFileType.LZ11_FILE
    if data[0:4] == b"darc":
        return AutoFileType.DARC_FILE
    if data[0:8] == b"MsgStdBn":
        return AutoFileType.MSBT_FILE
    if data[0:8] == b"MsgPrjBn":
        return AutoFileType.MSBP_FILE
    if data[0:8] == b"MsgFlwBn":
        return AutoFileType.MSBF_FILE
    return AutoFileType.UNKNOWN_FILE


def replace_extension(file: str, ext: str) -> str:
    return ".".join(file.split(".")[:-1]) + "." + ext


def handle_control_seq(buf: ByteBuffer) -> str:
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
            return "�"
    elif ctrl_type == 0x0008:# and ctrl_subtype == 0x0000:
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
            return "�"
    else:
        print(" (unknown (unknown))")
        return "�"


def msbt_to_xml(msbt: Msbt, path: str) -> XMLElement:
    from lxml.etree import Element as E, SubElement as SE
    msbt_node = E("MsbtFile", path=path)

    lbl1_node = SE(msbt_node, "Lbl1")
    for group, group_items in msbt.lbl1.items():
        for index, label in group_items.items():
            lbl1_entry_node = SE(lbl1_node, "Label", index=str(index), group=str(group))
            lbl1_entry_node.text = label.decode()

    txt2_node = SE(msbt_node, "Txt2")

    for str_idx, raw_bytes in enumerate(msbt.txt2):
        raw_buf = ByteBuffer(raw_bytes)
        txt2_entry = SE(txt2_node, "Entry", label=msbt.lbl1_indexed[str_idx])

        current_node = txt2_entry
        current_node.text = ""

        def make_append(node):
            def append(s):
                node.text += s

            return append
        append = make_append(current_node)

        while raw_buf.tell() < len(raw_bytes) - 1:
            char = raw_buf.read_wchar16le()

            if char == "\x00":
                break
            elif char == "\x0E":
                append(handle_control_seq(raw_buf))
            elif char == "\n":
                current_node = SE(current_node, "br")
                current_node.tail = ""

                def make_append(node):
                    def append(s):
                        node.tail += s

                    return append
                append = make_append(current_node)
            else:
                append(char)

        print(f"string {str_idx} is {txt2_entry.text}")

    return msbt_node


def darc_to_xml(arc: Darc, compressed: bool = False) -> lxml.etree.ElementBase:
    files = {}
    for entry in arc.entries():
        if not entry.is_dir:
            files[entry.filepath] = entry.data

    from lxml.etree import Element as E, SubElement as SE
    if compressed:
        root = E("LZ11")
        container = SE(root, "DarcContainer")
    else:
        root = container = E("DarcContainer")

    for file, data in files.items():
        if file.endswith(".msbt") and 1 == 2:
            print(f"processing msbt file !{file}")
            m = Msbt.from_bytes(data)
            node = msbt_to_xml(m, file)
            container.append(node)
        elif file.endswith(".msbp"):
            print(f"processing msbp file !{file}")
            p = LMSProjectFile.from_bytes(data)
            exit(1)
        else:
            print(f"including file !{file} as raw data")
            raw_data = SE(container, "RawDataFile", path=file)
            raw_data.text = b64encode(data).decode()

    return root


def xml_to_darc(root: XMLElement, output: io.BytesIO) -> Darc:
    arc = Darc()
    for node in root:
        node: XMLElement
        if node.tag == "RawDataFile":
            file_path = node.get("path")
            file_data = b64decode(node.text)
            arc.add_file(file_path, file_data)
        else:
            print(f"tag {node.tag} not handled")

    return arc


def decompile_main(args: argparse.Namespace) -> int:
    in_file = args.input
    out_file = args.output
    if not out_file:
        out_file = replace_extension(in_file, "xml")

    with open(in_file, "rb") as f:
        in_data = f.read()

    file_type = guess_file_type(in_data)

    was_compressed = False
    if file_type == AutoFileType.LZ11_FILE:
        was_compressed = True
        in_data = bytes(nlzss11.decompress(in_data))
        file_type = guess_file_type(in_data)

    if file_type == AutoFileType.DARC_FILE:
        print("darc file")
        arc = Darc.from_bytes(in_data)
        root = darc_to_xml(arc, was_compressed)

        print(f"writing {out_file}")
        with open(out_file, "wb") as f:
            f.write(lxml.etree.tostring(root, pretty_print=True, encoding="utf-8"))
        return 0

    if file_type == AutoFileType.MSBT_FILE:
        print("msbt file")
        msbt = Msbt.from_bytes(in_data, True)
        root = msbt_to_xml(msbt, in_file.split("/")[-1])

        with open(out_file, "wb") as f:
            f.write(lxml.etree.tostring(root, pretty_print=True, encoding="utf-8"))
        return 0

    print("Unsupported file format")
    return 1


def recompile_main(args: argparse.Namespace) -> int:
    in_file = args.input
    out_file = args.output

    output_buffer = io.BytesIO()

    with open(in_file, "rb") as f:
        root: XMLElement = lxml.etree.parse(f).getroot()

    is_compressed = False
    if root.tag == "LZ11":
        is_compressed = True
        root = root[0]  # pop off the outer layer and flag for compression later

    if root.tag == "DarcContainer":
        arc = xml_to_darc(root, output_buffer)
        output_buffer.write(arc.to_bytes())

    # print(lxml.etree.tostring(root))

    if is_compressed:
        compressed_out = io.BytesIO()
        compressed_out.write(nlzss11.compress(output_buffer.getvalue(), 6))
        output_buffer = compressed_out

    if not out_file:
        out_file = replace_extension(in_file, "new.bin")

    with open(out_file, "wb") as f:
        f.write(output_buffer.getvalue())

    return 0


def main() -> None:
    message_files = []
    messages_path = Path("/home/joseph/Documents/tomodachi_life/romfs/message")
    for mdir in messages_path.iterdir():
        for mfile in mdir.iterdir():
            message_files.append(mfile)

    unpacked_files = {}
    total = 0
    for i, f in enumerate(message_files):
        print(f"\rLoading archive {i+1}/{len(message_files)}", end="", flush=True)

        with open(f, "rb") as file:
            data = nlzss11.decompress(file.read())
        arc = Darc.from_bytes(data)
        files = {e.filepath: e.data for e in [e for e in arc.entries() if not e.is_dir]}

        unpacked_files[f] = files
        total += len(unpacked_files[f])
    print(f"\nTotal files: {total}")

    exts = {}
    for container_file, entries in unpacked_files.items():
        for file, data in entries.items():
            ext = file.split(".")[-1]
            if ext not in exts:
                exts[ext] = 0
            exts[ext] += 1

    print(exts)


def main_args() -> int:
    parser = argparse.ArgumentParser(
        description="Decompile, edit, and recompile MSBT files.",
    )

    parser.add_argument("-v", "--verbose", action="count", default=0, help="More logging output")

    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--decompile", action="store_true", help="Decompile a binary message file")
    action_group.add_argument("--compile", action="store_true", help="Compile an XML file to its binary representation")
    action_group.add_argument("--dump", action="store_true", help="Not sure about this yet")

    parser.add_argument("-i", "--input", metavar="FILE", help="The input file", required=True)
    parser.add_argument("-o", "--output", metavar="FILE", help="The destination file")

    args = parser.parse_args()

    if args.decompile:
        return decompile_main(args)

    if args.compile:
        return recompile_main(args)

    return 1


if __name__ == "__main__":
    exit(main_args())
