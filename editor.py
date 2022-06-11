import io
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

import pygubu
import nlzss11

from lib.darc import Darc
from lib.lms import LMSProjectFile, LMSStandardFile, LMSFlowFile, TXT2Block, HashTableBlock

PROJECT_PATH = Path(__file__).parent
PROJECT_UI = PROJECT_PATH / "editor.ui"


class EditorApp:
    builder: pygubu.Builder
    main_window: tk.Toplevel
    file_tree: ttk.Treeview
    text_pane: tk.Text
    text_tab: ttk.Notebook
    msbp_menu: tk.Menu

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

        self.msbp_menu = builder.get_object("msbp_action_menu")
        self.msbp_tree = builder.get_object("project_tree")

    def run(self) -> None:
        self.main_window.mainloop()

    def callback_menu_open(self) -> None:
        print("open!")

        f = filedialog.askopenfile(mode="rb", filetypes=[("DARC Containers", "*.bin")])
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

    def callback_tree_select(self, event) -> None:
        sel = self.file_tree.selection()[0]
        if "!str" in sel:
            file, str_part = sel.split("!")
            str_num = int(str_part.split("_")[1])

            if len(self.text_pane.get("1.0", tk.END)) > 0:
                self.text_pane.delete("1.0", tk.END)

            txt2: TXT2Block = self.files[file].blocks["TXT2"]
            self.text_pane.insert("1.0", txt2.messages[str_num][0])


if __name__ == "__main__":
    app = EditorApp()
    app.run()
