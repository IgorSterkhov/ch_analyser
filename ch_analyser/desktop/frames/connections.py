import tkinter as tk
from tkinter import ttk, messagebox

from ch_analyser.client import CHClient
from ch_analyser.services import AnalysisService
from ch_analyser.logging_config import get_logger
from ch_analyser.desktop.widgets.connection_dialog import ConnectionDialog

logger = get_logger(__name__)


class ConnectionsFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        # --- Header ---
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=12, pady=(12, 4))
        ttk.Label(header, text="Connections", font=("", 14, "bold")).pack(side=tk.LEFT)

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        columns = ("name", "host", "port", "database")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        self.tree.heading("name", text="Name")
        self.tree.heading("host", text="Host")
        self.tree.heading("port", text="Port")
        self.tree.heading("database", text="Database")

        self.tree.column("name", width=200, minwidth=100)
        self.tree.column("host", width=200, minwidth=100)
        self.tree.column("port", width=80, minwidth=60)
        self.tree.column("database", width=160, minwidth=80)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Buttons ---
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 12))

        ttk.Button(btn_frame, text="Add", command=self._on_add).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_frame, text="Edit", command=self._on_edit).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Delete", command=self._on_delete).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Connect", command=self._on_connect).pack(side=tk.RIGHT)

        self.refresh()

    def on_show(self, **kwargs):
        self.refresh()

    def refresh(self):
        """Reload the connections list from the manager."""
        self.tree.delete(*self.tree.get_children())
        try:
            connections = self.app.conn_manager.list_connections()
            for cfg in connections:
                self.tree.insert(
                    "", tk.END, iid=cfg.name,
                    values=(cfg.name, cfg.host, cfg.port, cfg.database),
                )
        except Exception as exc:
            logger.error("Failed to load connections: %s", exc)
            messagebox.showerror("Error", f"Failed to load connections:\n{exc}")

    def _get_selected_name(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showerror("Error", "Please select a connection first.")
            return None
        return selection[0]

    def _on_add(self):
        dialog = ConnectionDialog(self.app, title="Add Connection")
        if dialog.result is not None:
            try:
                self.app.conn_manager.add_connection(dialog.result)
                self.refresh()
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to add connection:\n{exc}")

    def _on_edit(self):
        name = self._get_selected_name()
        if name is None:
            return
        cfg = self.app.conn_manager.get_connection(name)
        if cfg is None:
            messagebox.showerror("Error", f"Connection '{name}' not found.")
            return

        dialog = ConnectionDialog(self.app, title="Edit Connection", config=cfg)
        if dialog.result is not None:
            try:
                self.app.conn_manager.update_connection(name, dialog.result)
                self.refresh()
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to update connection:\n{exc}")

    def _on_delete(self):
        name = self._get_selected_name()
        if name is None:
            return
        confirm = messagebox.askyesno(
            "Confirm Delete", f"Delete connection '{name}'?"
        )
        if confirm:
            try:
                self.app.conn_manager.delete_connection(name)
                self.refresh()
            except Exception as exc:
                messagebox.showerror("Error", f"Failed to delete connection:\n{exc}")

    def _on_connect(self):
        name = self._get_selected_name()
        if name is None:
            return
        cfg = self.app.conn_manager.get_connection(name)
        if cfg is None:
            messagebox.showerror("Error", f"Connection '{name}' not found.")
            return

        try:
            # Disconnect previous client if any
            if self.app.client is not None and self.app.client.connected:
                self.app.client.disconnect()

            # Inject global CA cert
            cfg.ca_cert = self.app.conn_manager.ca_cert

            client = CHClient(cfg)
            client.connect()
            self.app.client = client
            self.app.service = AnalysisService(client)
            logger.info("Connected to '%s'", name)
            self.app.show_frame("tables")
        except Exception as exc:
            logger.error("Connection failed: %s", exc)
            messagebox.showerror("Connection Error", f"Failed to connect:\n{exc}")
