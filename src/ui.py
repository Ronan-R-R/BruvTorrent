import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from typing import Optional


class BitTorrentUI(tk.Tk):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.title("BruvTorrent")
        self.geometry("1000x700")
        self.minsize(800, 600)

        # Enhanced color scheme (lighter dark mode)
        self.themes = {
            "light": {
                "bg": "#f8f9fa", "fg": "#212529",
                "button": "#e9ecef", "tree": "#ffffff",
                "select": "#dee2e6", "text_bg": "#ffffff",
                "text_fg": "#212529", "border": "#ced4da",
                "highlight": "#0078d7", "tab_bg": "#f0f0f0"
            },
            "dark": {
                "bg": "#2b3035",  # Lighter dark background
                "fg": "#e9ecef",  # Soft white text
                "button": "#495057",
                "tree": "#343a40",  # Darker elements
                "select": "#3d4348",
                "text_bg": "#343a40",
                "text_fg": "#e9ecef",
                "border": "#495057",
                "highlight": "#1a73e8",
                "tab_bg": "#1e1e1e"
            }
        }
        self.current_theme = "dark"  # Default to dark mode

        self._setup_style()
        self._setup_ui()
        self._setup_menu()
        self._setup_bindings()
        self._apply_full_theme()

    def _setup_style(self):
        """Configure ttk styles for both themes"""
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Base styles
        self.style.configure('.',
                             background=self.themes[self.current_theme]['bg'],
                             foreground=self.themes[self.current_theme]['fg'],
                             bordercolor=self.themes[self.current_theme]['border'],
                             lightcolor=self.themes[self.current_theme]['bg'],
                             darkcolor=self.themes[self.current_theme]['bg'],
                             troughcolor=self.themes[self.current_theme]['bg']
                             )

        # Treeview
        self.style.configure('Treeview',
                             background=self.themes[self.current_theme]['tree'],
                             fieldbackground=self.themes[self.current_theme]['tree'],
                             foreground=self.themes[self.current_theme]['fg'],
                             selectbackground=self.themes[self.current_theme]['select'],
                             borderwidth=0
                             )

        # Button
        self.style.configure('TButton',
                             background=self.themes[self.current_theme]['button'],
                             foreground=self.themes[self.current_theme]['fg'],
                             relief=tk.RAISED,
                             borderwidth=1
                             )

        # Notebook
        self.style.configure('TNotebook',
                             background=self.themes[self.current_theme]['bg'],
                             borderwidth=0
                             )
        self.style.configure('TNotebook.Tab',
                             background=self.themes[self.current_theme]['tab_bg'],
                             foreground=self.themes[self.current_theme]['fg'],
                             padding=[10, 5]
                             )

    def _setup_ui(self):
        """Initialize all UI components"""
        # Configure root window background
        self.configure(bg=self.themes[self.current_theme]['bg'])

        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Torrent list
        columns = ('name', 'size', 'progress', 'status', 'peers', 'download', 'upload')
        self.torrent_list = ttk.Treeview(main_frame, columns=columns, show='headings')

        # Configure columns
        for col in columns:
            self.torrent_list.heading(col, text=col.title())
            self.torrent_list.column(col, width=100, anchor=tk.CENTER)
        self.torrent_list.column('name', width=200, anchor=tk.W)
        self.torrent_list.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Control buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="Start", command=self.start_torrent).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Pause", command=self.pause_torrent).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Remove", command=self.remove_torrent).pack(side=tk.LEFT, padx=5)

        # Notebook
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Files tab
        files_frame = ttk.Frame(self.notebook)
        self.files_tree = ttk.Treeview(files_frame, columns=('name', 'size', 'progress'))
        self.files_tree.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(files_frame, text="Files")

        # Log tab
        log_frame = ttk.Frame(self.notebook)
        self.log_text = ScrolledText(
            log_frame,
            wrap=tk.WORD,
            bg=self.themes[self.current_theme]['text_bg'],
            fg=self.themes[self.current_theme]['text_fg'],
            insertbackground=self.themes[self.current_theme]['fg'],
            borderwidth=0,
            highlightthickness=0
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(log_frame, text="Log")

    def _setup_menu(self):
        """Create menu bar with theme options"""
        menubar = tk.Menu(self)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add Torrent", command=self.add_torrent)
        file_menu.add_command(label="Add Magnet", command=self.add_magnet)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Light Mode", command=lambda: self.set_theme("light"))
        view_menu.add_command(label="Dark Mode", command=lambda: self.set_theme("dark"))
        menubar.add_cascade(label="View", menu=view_menu)

        self.config(menu=menubar)

    def _setup_bindings(self):
        """Handle window events"""
        self.bind("<Configure>", self._on_window_resize)

    def _on_window_resize(self, event):
        """Handle window resizing"""
        if event.width < 800:
            self.geometry("800x600")

    def _apply_full_theme(self):
        """Apply theme to all widgets including non-ttk ones"""
        # Update root window
        self.configure(bg=self.themes[self.current_theme]['bg'])

        # Special case for text widgets
        self.log_text.configure(
            bg=self.themes[self.current_theme]['text_bg'],
            fg=self.themes[self.current_theme]['text_fg'],
            insertbackground=self.themes[self.current_theme]['fg']
        )

    def set_theme(self, theme_name: str):
        """Switch between light and dark themes"""
        self.current_theme = theme_name
        self._setup_style()
        self._apply_full_theme()

    def update_torrent_list(self):
        """Refresh the torrent list display"""
        self.torrent_list.delete(*self.torrent_list.get_children())
        if hasattr(self.client, 'torrents'):
            for info_hash, torrent in self.client.torrents.items():
                self.torrent_list.insert('', 'end', values=(
                    torrent.name,
                    f"{sum(f.length for f in torrent.files) / 1024 / 1024:.2f} MB",
                    "0%",
                    "Waiting",
                    "0",
                    "0 KB/s",
                    "0 KB/s"
                ))

    # Client control methods
    def start_torrent(self):
        if hasattr(self.client, 'start_selected_torrent'):
            self.client.start_selected_torrent()

    def pause_torrent(self):
        if hasattr(self.client, 'pause_selected_torrent'):
            self.client.pause_selected_torrent()

    def remove_torrent(self):
        if hasattr(self.client, 'remove_selected_torrent'):
            self.client.remove_selected_torrent()

    def add_torrent(self):
        file_path = filedialog.askopenfilename(
            title="Select Torrent File",
            filetypes=[("Torrent Files", "*.torrent")]
        )
        if file_path and hasattr(self.client, 'add_torrent'):
            self.client.add_torrent(file_path)
            self.update_torrent_list()

    def add_magnet(self):
        magnet = simpledialog.askstring(
            "Magnet Link",
            "Enter magnet URL:",
            parent=self
        )
        if magnet and hasattr(self.client, 'add_magnet_link'):
            self.client.add_magnet_link(magnet)


if __name__ == "__main__":
    # Test the UI standalone
    app = BitTorrentUI(client=None)
    app.mainloop()