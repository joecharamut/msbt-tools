from collections import namedtuple
from typing import List, Tuple, Any, Dict

import nlzss11

from lib.darc import Darc
from lib.filetype import FileType
from lib.lms import LMSProjectFile, LMSStandardFile


class TagParameter:
    def __init__(self, name: str, param_type: int, items: List[int]) -> None:
        self.name = name
        self.type = param_type
        self.items = items

    def __repr__(self) -> str:
        return f"<TagParameter name={self.name!r} type={self.type!r} items={self.items!r}>"


class Tag:
    parameters: List[TagParameter]

    def __init__(self, name: str, parameters: List[TagParameter]) -> None:
        self.name = name
        self.parameters = parameters

    def __repr__(self) -> str:
        return f"<Tag name={self.name!r} parameters={self.parameters!r}>"


class TagGroup:
    def __init__(self, name: str, tags: List[Tag]) -> None:
        self.name = name
        self.tags = tags

    def __repr__(self) -> str:
        return f"<TagGroup name={self.name!r} tags={self.tags!r}>"


class OMSText:
    messages: Dict[str, Tuple[str, List[Tuple[TagGroup, Tag, bytes]]]]

    def __init__(self) -> None:
        self.messages = {}

    def import_binary_text(self, project: "OMSProject", label: str, message: str, tags: List[Tuple[int, int, bytes]]):
        text = ""
        output_index = 0
        output_tags = []
        for c in message:
            if c == "￼":
                group_index, tag_index, param_data = tags.pop(0)

                group = project.tag_groups[group_index]
                tag = group.tags[tag_index]

                tag_parameter_names = ";".join([p.name for p in tag.parameters])

                output_tags.append((group, tag, param_data))
                text += "{" + str(output_index) + "}"
                output_index += 1
            else:
                text += c

        self.messages[label] = (text, output_tags)


class OMSProject:
    tag_parameters: List[TagParameter]
    tags: List[Tag]
    tag_groups: List[TagGroup]
    messages: Dict[str, OMSText]

    def __init__(self) -> None:
        self.tag_parameters = []
        self.tags = []
        self.tag_groups = []
        self.messages = {}

    def import_binary_project(self, data: bytes) -> None:
        file_type = FileType.guess(data)
        if file_type == FileType.LZ11_FILE:
            data = bytes(nlzss11.decompress(data))
            file_type = FileType.guess(data)

        if file_type == FileType.DARC_FILE:
            # load the arc
            arc = Darc.from_bytes(data)

            # scan arc for the project data
            project_bin = None
            for e in arc.entries():
                if not e.is_dir and e.filepath.endswith(".msbp"):
                    project_bin = LMSProjectFile.from_bytes(e.data)
                    break

            if not project_bin:
                raise TypeError("Darc project container not of expected format (missing msbp file)")

            self._import_msbp(project_bin)

            message_files = []
            for e in arc.entries():
                if not e.is_dir and e.filepath.endswith(".msbt"):
                    self._import_msbt(e.filepath, LMSStandardFile.from_bytes(e.data))

            print()

        else:
            raise TypeError("Invalid binary project format")

    def _import_msbp(self, msbp: LMSProjectFile) -> None:
        params = []
        for param_name, param_type, param_items in msbp.tgp2.parameters:
            params.append(TagParameter(param_name, param_type, param_items))
        self.tag_parameters = params

        tags = []
        for tag_name, tag_params in msbp.tag2.tags:
            tags.append(Tag(tag_name, [params[x] for x in tag_params]))
        self.tags = tags

        groups = []
        for group_name, group_tags in msbp.tgg2.groups:
            groups.append(TagGroup(group_name, [tags[x] for x in group_tags]))
        self.tag_groups = groups

    def _import_msbt(self, path: str, msbt: LMSStandardFile) -> None:
        txt = OMSText()

        id_to_label = {v: k for k, v in msbt.lbl1.labels.items()}
        for i, (text, tags) in enumerate(msbt.txt2.messages):
            label = id_to_label[i]
            txt.import_binary_text(self, label, text, tags)

        self.messages[path] = txt
