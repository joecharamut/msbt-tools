import io
import struct


class ByteBuffer(io.BytesIO):
    def __init__(self, buf=None):
        super().__init__(buf)

    def __getitem__(self, val):
        if isinstance(val, slice):
            raise NotImplementedError

        if isinstance(val, int):
            lastpos = self.tell()
            self.seek(val)
            b = self.read(1)
            self.seek(lastpos)
            return b

        raise TypeError(f"{type(self).__name__} indices must be int or slice, got {type(val).__name__}")

    def write(self, val, at=None) -> int:
        lastpos = self.tell()
        if at is not None:
            self.seek(at)

        ret = super().write(val)

        if at is not None:
            self.seek(lastpos)

        return ret

    def read(self, size=None, at=None) -> bytes:
        lastpos = self.tell()
        if at is not None:
            self.seek(at)

        ret = super().read(size if size else 1)

        if at is not None:
            self.seek(lastpos)

        return ret

    def end(self) -> int:
        self.seek(0, io.SEEK_END)
        return self.tell()

    def write_struct(self, val, fmt, at=None) -> int:
        return self.write(struct.pack(fmt, val), at)

    def write_u8(self, val, at=None) -> int:
        return self.write_struct(val, "<B", at)

    def write_u16(self, val, at=None) -> int:
        return self.write_struct(val, "<H", at)

    def write_u32(self, val, at=None) -> int:
        return self.write_struct(val, "<I", at)

    def write_asciiz(self, val, at=None) -> int:
        if not isinstance(val, str):
            raise TypeError(f"{type(val)} is not str")

        return self.write(val.encode("ascii") + b"\0", at)

    def write_uleb128(self, val) -> int:
        bits = [c for c in bin(val)[2:]]
        pad = len(bits) % 7
        if pad != 0:
            padding = ['0' for i in range(7-pad)]
            padding.extend(bits)
            bits = padding
        chunks = [bits[i:i+7] for i in range(0, len(bits), 7)]
        output = []
        for i, chunk in enumerate(chunks):
            prefix = "0b1"
            if i == 0:
                prefix = "0b0"
            output.append(int(prefix + "".join(chunk), 2))

        count = 0
        for byte in output:
            count += self.write_u8(byte)
        return count

    def read_struct(self, fmt, at=None):
        n = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(n, at))

    def read_wchar16le(self, at=None):
        return self.read(2, at).decode("utf-16le")

    def read_u16(self, at=None):
        return self.read_struct("<H", at)[0]

    def read_u32(self, at=None):
        return self.read_struct("<I", at)[0]

