import io
import struct
import typing
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

import pygubu
import nlzss11

from lib.darc import Darc
from lib.lms import LMSProjectFile, LMSStandardFile, LMSFlowFile, TXT2Block, HashTableBlock
from lib.oms import OMSProject

PROJECT_PATH = Path(__file__).parent
PROJECT_UI = PROJECT_PATH / "editor.ui"


def clear_tree(tree: ttk.Treeview) -> None:
    for i in tree.get_children():
        tree.delete(i)


def clear_text(text: tk.Text) -> None:
    if len(text.get("1.0", tk.END)) > 0:
        text.delete("1.0", tk.END)


class EditorApp:
    builder: pygubu.Builder
    main_window: tk.Toplevel
    file_tree: ttk.Treeview
    text_pane: tk.Text
    text_tab: ttk.Notebook
    msbp_menu: tk.Menu
    msg_tag_tree: ttk.Treeview

    open_prj: Optional[OMSProject]

    def __init__(self) -> None:
        self.builder = builder = pygubu.Builder()

        # setup and load ui
        builder.add_resource_path(PROJECT_PATH)
        builder.add_from_file(PROJECT_UI)

        # get the root window
        self.main_window = builder.get_object("main_window")

        # set the menu bar
        self.main_window.config(menu=builder.get_object("menubar"))

        # setup callbacks
        builder.connect_callbacks(self)

        self.file_tree = builder.get_object("file_tree")
        # self.file_tree.bind("<1>", self.callback_tree_select)
        
        self.text_pane = builder.get_object("text_editor_text")
        self.text_tab = builder.get_object("text_editor_tab")
        self.msg_tag_tree = builder.get_object("message_tag_tree")

        self.msbp_menu = builder.get_object("msbp_action_menu")
        self.msbp_tree = builder.get_object("project_tree")

        self.open_prj = None

    def run(self) -> None:
        self.main_window.mainloop()

    def callback_menu_open(self) -> None:
        f = filedialog.askopenfile(mode="rb", filetypes=[("OpenMessageStudio Project", "*.prj")])
        if not f:
            return
        self.open_file(f)

    def open_file(self, f) -> None:
        filebytes = f.read()
        name = Path(f.name).name

        if filebytes[0] == 0x11:
            try:
                print("decompressing lz11")
                filebytes = nlzss11.decompress(filebytes)
            except Exception as e:
                messagebox.showerror("Error opening file", str(e))
                exit(1)

        if bytes(filebytes[0:4]) != b"darc":
            print("darc file")
            messagebox.showerror("Error opening file", "Invalid DARC file magic")
            exit(1)

        self.open_arc = arc = Darc.from_bytes(filebytes)

        print(arc)

        container_id = "/"
        self.file_tree.insert("", "end", iid=container_id, text=name)

        files = {}
        dirs = []
        for entry in arc.entries():
            if entry.is_dir:
                dirs.append(entry.filepath)
            else:
                files[entry.filepath] = entry.data

        for d in dirs:
            if d:
                self.file_tree.insert("/", "end", iid=d, text=d)

        print(files.keys())

        for file in files.keys():
            parent = "/"
            key = file
            if len(file.split("/")) > 2:
                parent = "/" + file.split("/")[1]
                file = "/" + file.split("/")[2]
            self.file_tree.insert(parent, "end", iid=key, text=file)

        self.files = {}
        for file, data in files.items():
            if file.endswith(".msbt"):
                self.files[file] = LMSStandardFile.from_bytes(data)

        for file, msbt in self.files.items():
            txt2: TXT2Block = msbt.blocks["TXT2"]
            lbl1: HashTableBlock = msbt.blocks["LBL1"]
            lbl1_idx = {v: k for k, v in lbl1.labels.items()}
            for i, entry in enumerate(txt2.messages):
                self.file_tree.insert(file, "end", iid=f"{file}!str_{i}", text=lbl1_idx[i])

    def _load_project(self, prj: OMSProject) -> None:
        if self.open_prj is not None:
            raise RuntimeError("Project already loaded")
        self.open_prj = prj

        dirs = []
        for path, text in prj.messages.items():
            parts = path.split("/")
            parent = ""
            for i in range(1, len(parts) + 1):
                key = "/".join(parts[0:i]) or "/"
                if key not in dirs:
                    dirs.append(key)
                    self.file_tree.insert(parent, "end", iid=key, text=key.split("/")[-1] or "/")
                parent = key
            for i, (lbl, msg) in enumerate(text.messages.items()):
                self.file_tree.insert(path, "end", iid=f"{path}!str:{lbl}", text=lbl)

    def callback_tree_select(self, event) -> None:
        sel = self.file_tree.selection()[0]
        print(sel)
        if "!str" not in sel:
            return

        file, str_part = sel.split("!")
        label = str_part[4:]

        clear_text(self.text_pane)
        self.text_pane.insert("1.0", self.open_prj.messages[file].messages[label][0])

        clear_tree(self.msg_tag_tree)
        for i, (group, tag, param_data) in enumerate(self.open_prj.messages[file].messages[label][1]):
            param_str = ""
            param_data_buf = io.BytesIO(param_data)
            for j, p in enumerate(tag.parameters):
                param_val = None

                if p.type == 0:
                    param_val, = struct.unpack("B", param_data_buf.read(1))
                elif p.type == 8:
                    pass
                    # if len(len_buf := param_data_buf.read(2)) > 0:
                    #     string_len, = struct.unpack("H", len_buf)
                    #     param_val = ""
                    #     for _ in range(string_len):
                    #         param_val += param_data_buf.read(2).decode("utf-16")
                elif p.type == 9:
                    param_val = "["
                    for num, name_index in enumerate(p.items):
                        if num > 0:
                            param_val += ", "
                        param_val += f"\"{self.open_prj.tag_lists[name_index]}\""
                    param_val += "]"


                if j > 0:
                    param_str += "; "
                param_str += f"{p.name}={param_val}"


            self.msg_tag_tree.insert("", "end", iid=str(i), values=(i, f"{group.name}::{tag.name}", param_str))


    def callback_menu_import(self) -> None:
        f = filedialog.askopenfile(mode="rb", filetypes=[("Binary Projects", "*.*")])
        if not f:
            return
        self.import_file(f)

    def import_file(self, f: typing.IO) -> None:
        file_data = f.read()
        prj = OMSProject()
        try:
            prj.import_binary_project(file_data)
            self._load_project(prj)
        except TypeError as e:
            messagebox.showerror("Error opening file", str(e))
        print(prj)




if __name__ == "__main__":
    app = EditorApp()
    app.run()
