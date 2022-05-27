# -*- coding: utf-8 -*-
# modified from https://github.com/LITTOMA/darctool.git
import typing
from argparse import ArgumentError
import codecs
from fnmatch import fnmatch
from io import BytesIO
import os
import struct
from typing import List, Generator, Union


class DarcEntry:
    def __init__(self, byte_order: str) -> None:
        self.byte_order = byte_order

        # Create a root entry by default.
        self.__parameters__ = [
            0x01000000,
            0,
            1  # At least 1 entry (the root entry) in the archive.
        ]
        self.name = ""
        self.parent = None
        self.children = []
        self.__data__ = None
        self.__darc_file__ = None

    def add_child(self, child: "DarcEntry") -> None:
        if not isinstance(child, DarcEntry):
            raise TypeError

        child.parent = self
        self.children.append(child)

    def is_child_of(self, entry) -> bool:
        e = self
        while e.parent:
            if e.parent is entry:
                return True
            e = e.parent
        return False

    def load(self, f: typing.IO) -> None:
        self.__darc_file__ = f
        s = f.read(0xC)
        self.__parameters__ = list(
            struct.unpack_from(self.byte_order+'iii', s))

    def to_bin(self) -> bytes:
        return struct.pack(self.byte_order+'iii', *self.__parameters__)

    def __repr__(self) -> str:
        return '"{name}" <isdir: {isdir}, length: {l}>'.format(name=self.name, isdir=self.is_dir, l=self.length)

    @property
    def data(self) -> bytes:
        if self.__data__:
            return self.__data__

        if self.__darc_file__:
            self.__darc_file__.seek(self.data_offset, 0)
            self.__data__ = self.__darc_file__.read(self.length)

        return self.__data__

    @data.setter
    def data(self, value: bytes) -> None:
        self.__data__ = value

    @property
    def is_dir(self) -> bool:
        return (self.__parameters__[0] & 0x01000000) == 0x01000000

    @is_dir.setter
    def is_dir(self, value: bool) -> None:
        if value:
            self.__parameters__[0] |= 0x01000000
        else:
            self.__parameters__[0] &= 0xFEFFFFFF

    @property
    def data_offset(self) -> int:
        return self.__parameters__[1]

    @data_offset.setter
    def data_offset(self, value: int) -> None:
        self.__parameters__[1] = value

    @property
    def name_offset(self) -> int:
        return self.__parameters__[0] & 0x00FFFFFF

    @name_offset.setter
    def name_offset(self, value: int) -> None:
        if value > 0x00FFFFFF:
            raise ValueError("Name offset must not lager than %d" % 0x00FFFFFF)

        self.__parameters__[0] &= 0xFF000000
        self.__parameters__[0] |= (0x00FFFFFF & value)

    @property
    def length(self) -> int:
        return self.__parameters__[2]

    @length.setter
    def length(self, value: int) -> None:
        self.__parameters__[2] = value

    @property
    def full_path(self) -> str:
        e = self
        path = e.name
        while e.parent:
            path = e.parent.name + os.path.sep + path
            e = e.parent
        return path


class Darc(object):
    DARC_HEADER_MAGIC = b"darc"
    DARC_HEADER_STRUCT = "hiiiii"
    DARC_SUPPORTED_VERSION = 0x01000000

    def __init__(self, byte_order='<', alignment=4, typealign=None) -> None:
        if not typealign:
            typealign = []
        (self.header_size, self.version, self.file_size, self.file_table_offset,
         self.file_table_size, self.file_data_offset) = (
            0x1C, self.DARC_SUPPORTED_VERSION, 0, 0x1C, 0, 0
        )
        self.byte_order = byte_order
        self.root_entry = DarcEntry(self.byte_order)
        self.defaultalignment = alignment
        self.typealignment = typealign

        self.darc_file = None

    def _build_index(self) -> None:
        entry_stack = [self.root_entry]
        dir_stack = []
        i = 0
        while len(entry_stack) > 0:
            i += 1
            entry = entry_stack[-1]
            while len(dir_stack) > 0 and not entry.is_child_of(dir_stack[-1]):
                dir_stack.remove(dir_stack[-1])
            if entry.is_dir:
                dir_stack.append(entry)
            entry_stack.remove(entry_stack[-1])
            for e in entry.children[::-1]:
                entry_stack.append(e)
            for d in dir_stack:
                d.length = i

    def close(self) -> None:
        if self.darc_file and not self.darc_file.closed:
            self.darc_file.close()

    def save(self, path_out) -> None:
        self._build_index()
        entries = self.flat_entries

        file_name_table = BytesIO()
        file_name_writer = codecs.getwriter('utf-16le')(file_name_table)
        for e in entries:
            e.name_offset = file_name_table.tell()
            file_name_writer.write(e.name)
            file_name_writer.write(u'\0')

        file_name_data = file_name_table.getvalue()
        self.file_table_size = (len(entries) * 0x0C) + len(file_name_data)

        print('Save: '+path_out)
        with open(path_out, 'wb') as darc:
            darc.write(self.DARC_HEADER_MAGIC)

            if self.byte_order == "<":
                bom = b"\xFF\xFE"
            elif self.byte_order == ">":
                bom = b"\xFE\xFF"
            else:
                bom = b"\x00\x00"
            darc.write(bom)

            darc.write(struct.pack(self.byte_order+self.DARC_HEADER_STRUCT, self.header_size,
                                   self.DARC_SUPPORTED_VERSION, self.file_size, self.file_table_offset,
                                   self.file_table_size, self.file_data_offset))
            darc.write(b"\x00"*(0xC*len(entries)))
            darc.write(file_name_data)

            first_entry = True
            for e in entries:
                if e.is_dir:
                    continue

                alignto = align(darc.tell(), self.getalignment(e.name))
                darc.seek(alignto, 0)

                if first_entry:
                    self.file_data_offset = darc.tell()
                    first_entry = False

                e.data_offset = darc.tell()
                data = e.data
                e.length = len(data)
                darc.write(data)

            self.file_size = darc.tell()
            darc.seek(6, 0)
            darc.write(struct.pack(self.byte_order+self.DARC_HEADER_STRUCT, self.header_size,
                                   self.DARC_SUPPORTED_VERSION, self.file_size, self.file_table_offset,
                                   self.file_table_size, self.file_data_offset))
            for e in entries:
                darc.write(e.to_bin())

    def getalignment(self, name) -> int:
        for p in self.typealignment:
            if fnmatch(name, p[0]):
                return p[1]
        return self.defaultalignment

    def addentry(self, path, exclude=None) -> None:
        if not exclude:
            exclude = []
        if os.path.isfile(path):
            self.addfile(path)
        elif os.path.isdir(path):
            self.adddir(path, exclude)
        else:
            raise ArgumentError('Unknown path type: '+path)

    def adddir(self, path, exclude=None) -> None:
        if not exclude:
            exclude = []
        fsentry_stack = [path]
        dir_map = {parentdir(path): self.root_entry}
        while len(fsentry_stack) > 0:
            curfsentry = os.path.normpath(fsentry_stack[-1])
            fsentry_stack.remove(fsentry_stack[-1])

            if should_exclude(curfsentry, exclude):
                continue

            entry = DarcEntry(self.byte_order)
            entry.name = os.path.split(curfsentry)[-1]
            parent = parentdir(curfsentry)
            dir_map[parent].add_child(entry)

            if os.path.isdir(curfsentry):
                dir_map[os.path.abspath(curfsentry)] = entry
                for d in os.listdir(curfsentry)[::-1]:
                    fsentry_stack.append(os.path.join(curfsentry, d))
            elif os.path.isfile(curfsentry):
                entry.isdir = False
                with open(curfsentry, 'rb') as f:
                    print('load: '+curfsentry)
                    entry.data = f.read()

    def addfile(self, path) -> None:
        entry = DarcEntry(self.byte_order)
        entry.name = os.path.split(path)[1]
        entry.isdir = False
        with open(path, 'rb') as fs:
            entry.data = fs.read()
        self.root_entry.add_child(entry)

    def add_file(self, data: bytes, path: str) -> None:
        entry = DarcEntry(self.byte_order)
        entry.name = path
        entry.is_dir = False
        entry.data = data
        self.root_entry.add_child(entry)

    @staticmethod
    def from_dir(workdir, byte_order='<', entries=None, exclude=None) -> "Darc":
        if entries is None:
            entries = ["."]
        if exclude is None:
            exclude = []

        darc = Darc(byte_order)

        origndir = os.getcwd()
        os.chdir(workdir)
        for n in entries:
            darc.addentry(n, exclude)
        os.chdir(origndir)

        return darc

    @staticmethod
    def load(f: typing.BinaryIO) -> "Darc":
        darc = Darc()
        darc.darc_file = f
        magic = darc.darc_file.read(4)
        if magic != darc.DARC_HEADER_MAGIC:
            raise ValueError("Invalid file magic.")

        byte_order_mark = darc.darc_file.read(2)
        if byte_order_mark == b'\xFF\xFE':
            darc.byte_order = '<'
        elif byte_order_mark == b'\xFE\xFF':
            darc.byte_order = '>'
        else:
            raise ValueError("Invalid byte order mark.")

        (darc.header_size, darc.version, darc.file_size, darc.file_table_offset,
         darc.file_table_size, darc.file_data_offset) = \
            struct.unpack(darc.byte_order+darc.DARC_HEADER_STRUCT,
                          darc.darc_file.read(struct.calcsize(darc.byte_order+darc.DARC_HEADER_STRUCT)))

        if darc.version != darc.DARC_SUPPORTED_VERSION:
            raise ValueError("Unsupported file version.")

        darc.root_entry = DarcEntry(darc.byte_order)
        darc.root_entry.load(darc.darc_file)

        current_offset = darc.darc_file.tell()
        file_name_table_offset = darc.total_entries * 0xC + current_offset
        file_name_table_size = darc.file_table_size - (darc.total_entries * 0xC)
        darc.darc_file.seek(file_name_table_offset, 0)
        file_name_table = darc.darc_file.read(file_name_table_size)
        darc.darc_file.seek(current_offset, 0)

        dir_list = [darc.root_entry]
        for i in range(1, darc.total_entries+1):
            e = DarcEntry(darc.byte_order)
            e.load(darc.darc_file)
            e.name = get_unicode_str(file_name_table, e.name_offset)

            dir_list[-1].add_child(e)

            if i >= dir_list[-1].length-1:
                dir_list.remove(dir_list[-1])

            if e.is_dir:
                dir_list.append(e)

        return darc

    def extract(self, path_out, exclude=None) -> None:
        if exclude is None:
            exclude = []
        for e in self.flat_entries:
            fullpath = e.full_path
            if should_exclude(fullpath, exclude):
                continue

            if e.is_dir:
                mkdirs(path_out+fullpath)
            else:
                fp = path_out+fullpath
                if not os.path.exists(os.path.split(fp)[0]):
                    continue

                data = e.data
                with open(fp, 'wb') as of:
                    print('Extract: '+fp)
                    of.write(data)

    def list(self, exclude: List[str] = None) -> None:
        if not exclude:
            exclude = []

        for e in self.flat_entries:
            if should_exclude(e.full_path, exclude):
                continue
            print(e.full_path)

    @property
    def total_entries(self) -> int:
        return self.root_entry.length - 1

    @total_entries.setter
    def total_entries(self, value: int) -> None:
        self.root_entry.length = value + 1

    @property
    def flat_entries(self) -> List[DarcEntry]:
        entry_stack = [self.root_entry]
        entry_list = []
        while len(entry_stack) > 0:
            entry = entry_stack.pop()
            entry_list.append(entry)
            for e in entry.children[::-1]:
                entry_stack.append(e)
        return entry_list


def align(value: int, alignment: int) -> int:
    return int((value + alignment - 1) / alignment * alignment)


def get_unicode_str(data, start_at=0) -> str:
    ms = BytesIO(data)
    reader = codecs.getreader('utf-16le')(ms)
    ms.seek(start_at)

    s = []
    while True:
        c = reader.read(1)
        if c == u'\0':
            break
        s.append(c)

    return u''.join(s)


def mkdirs(path) -> None:
    if not os.path.exists(path):
        print('Create: '+path)
        os.makedirs(path)


def walk(dirname, pattern='*.*') -> Generator[str, None, None]:
    for root, dirs, files in os.walk(dirname):
        for filename in files:
            if not fnmatch(filename, pattern):
                continue
            fullname = os.path.join(root, filename)
            yield fullname


def walkdirs(dirname, pattern='*.*') -> Generator[str, None, None]:
    for root, dirs, files in os.walk(dirname):
        for dname in dirs:
            if not fnmatch(dname, pattern):
                continue
            fullname = os.path.join(root, dname)
            yield fullname


def should_exclude(path, exclude) -> bool:
    is_excluded = False
    for ex in exclude:
        if fnmatch(path, ex):
            is_excluded = True
            break
    return is_excluded


def parentdir(path) -> str:
    return os.path.abspath(os.path.join(path, os.pardir))


def parsetypealignments(types) -> list:
    config = []
    for t in types:
        if t.count(':') != 1:
            continue
        p = t.split(':')
        p = (p[0], int(p[1], 0))
        config.append(p)
    return config

