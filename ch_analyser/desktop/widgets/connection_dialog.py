import tkinter as tk
from tkinter import ttk, messagebox

from ch_analyser.config import ConnectionConfig


class ConnectionDialog(tk.Toplevel):
    """Modal dialog for creating or editing a connection."""

    def __init__(self, parent, title="Connection", config: ConnectionConfig | None = None):
        super().__init__(parent)

        self.title(title)
        self.geometry("400x320")
        self.resizable(False, False)
        self.result: ConnectionConfig | None = None

        # Make modal
        self.transient(parent)
        self.grab_set()

        # --- Form fields ---
        form = ttk.Frame(self, padding=16)
        form.pack(fill=tk.BOTH, expand=True)

        labels = ["Name:", "Host:", "Port:", "User:", "Password:", "Database:"]
        self._entries: dict[str, tk.Entry] = {}

        for row, label_text in enumerate(labels):
            ttk.Label(form, text=label_text).grid(
                row=row, column=0, sticky=tk.W, padx=(0, 8), pady=4
            )

        field_keys = ["name", "host", "port", "user", "password", "database"]
        defaults = {
            "name": "",
            "host": "localhost",
            "port": "9000",
            "user": "default",
            "password": "",
            "database": "default",
        }

        for row, key in enumerate(field_keys):
            show = "*" if key == "password" else ""
            entry = ttk.Entry(form, width=36, show=show)
            entry.grid(row=row, column=1, sticky=tk.EW, pady=4)
            self._entries[key] = entry

            # Pre-fill values
            if config is not None:
                value = str(getattr(config, key, defaults[key]))
            else:
                value = defaults[key]
            entry.insert(0, value)

        form.columnconfigure(1, weight=1)

        # --- Buttons ---
        btn_frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(
            side=tk.RIGHT, padx=(8, 0)
        )
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.RIGHT)

        # Focus on first entry
        self._entries["name"].focus_set()

        # Bind Enter/Escape keys
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())

        # Wait for the dialog to close
        self.wait_window()

    def _on_ok(self):
        name = self._entries["name"].get().strip()
        host = self._entries["host"].get().strip()
        port_str = self._entries["port"].get().strip()
        user = self._entries["user"].get().strip()
        password = self._entries["password"].get()
        database = self._entries["database"].get().strip()

        if not name:
            messagebox.showerror("Validation Error", "Name is required.", parent=self)
            return
        if not host:
            messagebox.showerror("Validation Error", "Host is required.", parent=self)
            return
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Validation Error", "Port must be an integer.", parent=self)
            return

        self.result = ConnectionConfig(
            name=name,
            host=host,
            port=port,
            user=user or "default",
            password=password,
            database=database or "default",
        )
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()
