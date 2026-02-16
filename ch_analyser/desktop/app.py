import tkinter as tk
from tkinter import ttk

from ch_analyser.config import ConnectionManager
from ch_analyser.client import CHClient
from ch_analyser.services import AnalysisService
from ch_analyser.logging_config import get_logger

from ch_analyser.desktop.frames.connections import ConnectionsFrame
from ch_analyser.desktop.frames.tables import TablesFrame
from ch_analyser.desktop.frames.columns import ColumnsFrame

logger = get_logger(__name__)


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ClickHouse Analyser")
        self.geometry("900x600")
        self.minsize(700, 400)

        self.conn_manager = ConnectionManager()
        self.client: CHClient | None = None
        self.service: AnalysisService | None = None

        # Configure ttk style
        style = ttk.Style(self)
        style.theme_use("clam")

        # Container frame that holds all page frames
        self._container = ttk.Frame(self)
        self._container.pack(fill=tk.BOTH, expand=True)

        # Register frames
        self._frames: dict[str, tk.Frame] = {}
        self._current_frame: tk.Frame | None = None

        self._frames["connections"] = ConnectionsFrame(self._container, self)
        self._frames["tables"] = TablesFrame(self._container, self)
        self._frames["columns"] = ColumnsFrame(self._container, self)

        self.show_frame("connections")

    def show_frame(self, name: str, **kwargs):
        """Switch the visible frame by name."""
        frame = self._frames.get(name)
        if frame is None:
            logger.error("Unknown frame: %s", name)
            return

        # Hide current frame
        if self._current_frame is not None:
            self._current_frame.pack_forget()

        # Show target frame
        frame.pack(fill=tk.BOTH, expand=True)
        self._current_frame = frame

        # Call on_show if available
        if hasattr(frame, "on_show"):
            frame.on_show(**kwargs)
