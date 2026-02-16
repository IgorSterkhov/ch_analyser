import tkinter as tk
from tkinter import ttk, messagebox

from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


class ColumnsFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._table_name = ""

        # --- Header ---
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=12, pady=(12, 4))

        self._title_label = ttk.Label(header, text="Columns", font=("", 14, "bold"))
        self._title_label.pack(side=tk.LEFT)

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        columns = ("name", "type", "codec", "size")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        self.tree.heading("name", text="Column")
        self.tree.heading("type", text="Type")
        self.tree.heading("codec", text="Codec")
        self.tree.heading("size", text="Size")

        self.tree.column("name", width=200, minwidth=100)
        self.tree.column("type", width=220, minwidth=100)
        self.tree.column("codec", width=180, minwidth=80)
        self.tree.column("size", width=120, minwidth=80)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Buttons ---
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 12))

        ttk.Button(btn_frame, text="Back", command=self._on_back).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Refresh", command=self._load_columns).pack(
            side=tk.LEFT, padx=8
        )

    def on_show(self, table_name: str = "", **kwargs):
        if table_name:
            self._table_name = table_name
        self._title_label.config(text=f"Columns  --  {self._table_name}")
        self._load_columns()

    def _load_columns(self):
        """Fetch columns for the current table and populate the treeview."""
        self.tree.delete(*self.tree.get_children())
        if self.app.service is None:
            messagebox.showerror("Error", "Not connected to any database.")
            return
        if not self._table_name:
            return

        try:
            cols = self.app.service.get_columns(self._table_name)
            for c in cols:
                self.tree.insert(
                    "", tk.END,
                    values=(c["name"], c["type"], c.get("codec", ""), c.get("size", "")),
                )
        except Exception as exc:
            logger.error("Failed to load columns for %s: %s", self._table_name, exc)
            messagebox.showerror("Error", f"Failed to load columns:\n{exc}")

    def _on_back(self):
        self.app.show_frame("tables")
