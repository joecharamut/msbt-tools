import enum


class FileType(enum.Enum):
    UNKNOWN_FILE = enum.auto()
    MSBT_FILE = enum.auto()
    MSBP_FILE = enum.auto()
    MSBF_FILE = enum.auto()
    DARC_FILE = enum.auto()
    LZ11_FILE = enum.auto()

    @staticmethod
    def guess(data: bytes) -> "FileType":
        if data[0] == 0x11:
            return FileType.LZ11_FILE
        if data[0:4] == b"darc":
            return FileType.DARC_FILE
        if data[0:8] == b"MsgStdBn":
            return FileType.MSBT_FILE
        if data[0:8] == b"MsgPrjBn":
            return FileType.MSBP_FILE
        if data[0:8] == b"MsgFlwBn":
            return FileType.MSBF_FILE
        return FileType.UNKNOWN_FILE
