import io
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygubu

from lib.msbt import Msbt

from external.nlzss import lzss3
from external.darctool.darc import Darc

PROJECT_PATH = Path(__file__).parent
PROJECT_UI = PROJECT_PATH / "editor.ui"


class EditorApp:
    builder: pygubu.Builder
    main_window: tk.Toplevel
    file_tree: ttk.Treeview
    text_pane: tk.Text
    text_tab: ttk.Notebook

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
                filebytes = lzss3.decompress_bytes(filebytes)
            except Exception as e:
                messagebox.showerror("Error opening file", str(e))
                exit(1)

        if bytes(filebytes[0:4]) != b"darc":
            print("darc file")
            messagebox.showerror("Error opening file", "Invalid DARC file magic")
            exit(1)

        self.open_arc = arc = Darc.load(io.BytesIO(filebytes))

        print(arc)

        container_id = "/"
        self.file_tree.insert("", "end", iid=container_id, text=name)

        files = {}
        dirs = []
        for entry in arc.flatentries:
            if entry.isdir:
                dirs.append(entry.fullpath)
            if "." in entry.fullpath:
                files[entry.fullpath] = entry.data

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
                self.files[file] = Msbt.from_bytes(data)

        for file, msbt in self.files.items():
            for i, entry in enumerate(msbt.txt2):
                self.file_tree.insert(file, "end", iid=f"{file}!str_{i}", text=msbt.lbl1_indexed[i])

    def callback_tree_select(self, event) -> None:
        sel = self.file_tree.selection()[0]
        if "!str" in sel:
            file, str_part = sel.split("!")
            str_num = int(str_part.split("_")[1])

            if len(self.text_pane.get("1.0", tk.END)) > 0:
                self.text_pane.delete("1.0", tk.END)

            self.text_pane.insert("1.0", Msbt.decode_txt2_entry(self.files[file].txt2[str_num]))


if __name__ == "__main__":
    app = EditorApp()
    app.run()
