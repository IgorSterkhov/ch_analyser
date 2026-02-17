import tkinter as tk
from tkinter import ttk, messagebox

from ch_analyser.config import ConnectionConfig

PORT_DEFAULTS = {
    ("native", False): 9000,
    ("native", True): 9440,
    ("http", False): 8123,
    ("http", True): 8443,
}


class ConnectionDialog(tk.Toplevel):
    """Modal dialog for creating or editing a connection."""

    def __init__(self, parent, title="Connection", config: ConnectionConfig | None = None):
        super().__init__(parent)

        self.title(title)
        self.geometry("400x380")
        self.resizable(False, False)
        self.result: ConnectionConfig | None = None

        # Make modal
        self.transient(parent)
        self.grab_set()

        # --- Form fields ---
        form = ttk.Frame(self, padding=16)
        form.pack(fill=tk.BOTH, expand=True)

        labels = [
            "Name:", "Host:", "Port:", "User:", "Password:",
            "Database:", "Protocol:", "SSL:",
        ]
        self._entries: dict[str, tk.Widget] = {}

        for row, label_text in enumerate(labels):
            ttk.Label(form, text=label_text).grid(
                row=row, column=0, sticky=tk.W, padx=(0, 8), pady=4
            )

        defaults = {
            "name": "",
            "host": "localhost",
            "port": "9000",
            "user": "default",
            "password": "",
            "database": "default",
        }

        # Text entries: name, host, port, user, password, database
        text_fields = ["name", "host", "port", "user", "password", "database"]
        for row, key in enumerate(text_fields):
            show = "*" if key == "password" else ""
            entry = ttk.Entry(form, width=36, show=show)
            entry.grid(row=row, column=1, sticky=tk.EW, pady=4)
            self._entries[key] = entry

            if config is not None:
                value = str(getattr(config, key, defaults[key]))
            else:
                value = defaults[key]
            entry.insert(0, value)

        # Protocol combobox (row 6)
        protocol_combo = ttk.Combobox(
            form, values=["native", "http"], state="readonly", width=33,
        )
        protocol_combo.set(config.protocol if config else "native")
        protocol_combo.grid(row=6, column=1, sticky=tk.EW, pady=4)
        self._entries["protocol"] = protocol_combo

        # SSL checkbox (row 7)
        self._ssl_var = tk.BooleanVar(value=config.secure if config else False)
        ssl_check = ttk.Checkbutton(form, variable=self._ssl_var)
        ssl_check.grid(row=7, column=1, sticky=tk.W, pady=4)
        self._entries["secure"] = ssl_check

        form.columnconfigure(1, weight=1)

        # Auto-update port on protocol/SSL change
        def _update_port(*_args):
            proto = protocol_combo.get()
            secure = self._ssl_var.get()
            new_port = PORT_DEFAULTS.get((proto, secure), 9000)
            port_entry = self._entries["port"]
            port_entry.delete(0, tk.END)
            port_entry.insert(0, str(new_port))

        protocol_combo.bind("<<ComboboxSelected>>", _update_port)
        self._ssl_var.trace_add("write", _update_port)

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
        protocol = self._entries["protocol"].get()
        secure = self._ssl_var.get()

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
            protocol=protocol,
            secure=secure,
        )
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()
