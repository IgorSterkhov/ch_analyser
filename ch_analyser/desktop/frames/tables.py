import tkinter as tk
from tkinter import ttk, messagebox

from ch_analyser.logging_config import get_logger

logger = get_logger(__name__)


class TablesFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        # --- Header ---
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=12, pady=(12, 4))
        ttk.Label(header, text="Tables", font=("", 14, "bold")).pack(side=tk.LEFT)

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        columns = ("name", "size", "last_select", "last_insert")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        self.tree.heading("name", text="Table")
        self.tree.heading("size", text="Size")
        self.tree.heading("last_select", text="Last SELECT")
        self.tree.heading("last_insert", text="Last INSERT")

        self.tree.column("name", width=220, minwidth=120)
        self.tree.column("size", width=120, minwidth=80)
        self.tree.column("last_select", width=200, minwidth=120)
        self.tree.column("last_insert", width=200, minwidth=120)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Double-click to open columns
        self.tree.bind("<Double-1>", lambda e: self._on_details())

        # --- Buttons ---
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 12))

        ttk.Button(btn_frame, text="Disconnect", command=self._on_disconnect).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(btn_frame, text="Refresh", command=self._load_tables).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Details", command=self._on_details).pack(side=tk.RIGHT)

    def on_show(self, **kwargs):
        self._load_tables()

    def _load_tables(self):
        """Fetch tables from the analysis service and populate the treeview."""
        self.tree.delete(*self.tree.get_children())
        if self.app.service is None:
            messagebox.showerror("Error", "Not connected to any database.")
            return

        try:
            tables = self.app.service.get_tables()
            for t in tables:
                self.tree.insert(
                    "", tk.END, iid=t["name"],
                    values=(t["name"], t["size"], t["last_select"], t["last_insert"]),
                )
        except Exception as exc:
            logger.error("Failed to load tables: %s", exc)
            messagebox.showerror("Error", f"Failed to load tables:\n{exc}")

    def _on_details(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showerror("Error", "Please select a table first.")
            return
        table_name = selection[0]
        self.app.show_frame("columns", table_name=table_name)

    def _on_disconnect(self):
        if self.app.client is not None and self.app.client.connected:
            self.app.client.disconnect()
        self.app.client = None
        self.app.service = None
        self.app.show_frame("connections")
