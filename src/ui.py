import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from typing import Dict, Optional
import asyncio


class BitTorrentUI(tk.Tk):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.title("BruvTorrent")
        self.geometry("1000x700")
        self.minsize(800, 600)

        # DeepSeek-inspired theme colors
        self.themes = {
            "light": {
                "bg": "#ffffff", "fg": "#333333",
                "button": "#f5f5f5", "tree": "#ffffff",
                "select": "#e6f2ff", "text_bg": "#ffffff",
                "text_fg": "#333333", "border": "#e1e1e1",
                "highlight": "#0078d7", "tab_bg": "#f0f0f0"
            },
            "dark": {
                "bg": "#1a1a1a", "fg": "#e6e6e6",
                "button": "#2d2d2d", "tree": "#252525",
                "select": "#3a3a3a", "text_bg": "#252525",
                "text_fg": "#e6e6e6", "border": "#333333",
                "highlight": "#4a90e2", "tab_bg": "#2d2d2d"
            }
        }
        self.current_theme = "dark"  # Default to dark mode

        self._setup_style()
        self._setup_ui()
        self._setup_menu()
        self._setup_window_bindings()
        self._apply_theme()

    def _setup_style(self):
        """Configure ttk styles for themes"""
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Base style
        self.style.configure('.',
                             background=self.themes[self.current_theme]['bg'],
                             foreground=self.themes[self.current_theme]['fg'],
                             bordercolor=self.themes[self.current_theme]['border'],
                             lightcolor=self.themes[self.current_theme]['bg'],
                             darkcolor=self.themes[self.current_theme]['bg']
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
                             bordercolor=self.themes[self.current_theme]['border'],
                             focuscolor=self.themes[self.current_theme]['highlight']
                             )

        # Notebook
        self.style.configure('TNotebook',
                             background=self.themes[self.current_theme]['bg'],
                             borderwidth=0
                             )
        self.style.configure('TNotebook.Tab',
                             background=self.themes[self.current_theme]['tab_bg'],
                             foreground=self.themes[self.current_theme]['fg'],
                             padding=[10, 5],
                             borderwidth=0
                             )

    def _setup_ui(self):
        """Initialize all UI components"""
        # Configure root window background
        self.configure(bg=self.themes[self.current_theme]['bg'])

        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Torrent list
        columns = ('name', 'size', 'progress', 'status', 'peers', 'download', 'upload')
        self.torrent_list = ttk.Treeview(
            main_frame,
            columns=columns,
            show='headings',
            height=15,
            selectmode='browse'
        )

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
        self.files_tree = ttk.Treeview(
            files_frame,
            columns=('name', 'size', 'progress'),
            show='headings'
        )
        self.files_tree.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(files_frame, text="Files")

        # Log tab
        log_frame = ttk.Frame(self.notebook)
        self.log_text = ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg=self.themes[self.current_theme]['text_bg'],
            fg=self.themes[self.current_theme]['text_fg'],
            insertbackground=self.themes[self.current_theme]['fg'],
            borderwidth=0,
            highlightthickness=0
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(log_frame, text="Log")

    def _setup_menu(self):
        """Create menu bar"""
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

    def _setup_window_bindings(self):
        """Handle window events"""
        self.bind("<Configure>", self._on_window_resize)

    def _on_window_resize(self, event):
        """Handle window resizing"""
        if event.width < 800:
            self.geometry("800x600")

    def _apply_theme(self):
        """Apply current theme to all widgets"""
        # Update root window
        self.configure(bg=self.themes[self.current_theme]['bg'])

        # Update text widgets
        self.log_text.configure(
            bg=self.themes[self.current_theme]['text_bg'],
            fg=self.themes[self.current_theme]['text_fg'],
            insertbackground=self.themes[self.current_theme]['fg']
        )

        # Update all ttk widgets
        self.style.theme_use('clam')
        self._update_ttk_styles()

    def _update_ttk_styles(self):
        """Refresh ttk widget styles"""
        self.style.configure('Treeview',
                             background=self.themes[self.current_theme]['tree'],
                             foreground=self.themes[self.current_theme]['fg'],
                             selectbackground=self.themes[self.current_theme]['select']
                             )
        self.style.configure('TButton',
                             background=self.themes[self.current_theme]['button'],
                             foreground=self.themes[self.current_theme]['fg']
                             )

    def set_theme(self, theme_name: str):
        """Switch between light/dark themes"""
        self.current_theme = theme_name
        self._setup_style()
        self._apply_theme()

    def update_torrent_list(self, torrents: Dict):
        """Refresh the torrent list display"""
        self.torrent_list.delete(*self.torrent_list.get_children())
        for info_hash, metadata in torrents.items():
            self.torrent_list.insert('', 'end',
                                     values=(
                                         metadata.name,
                                         "0 B",  # Placeholder for size
                                         "0%",  # Progress placeholder
                                         "Queued",  # Status
                                         "0",  # Peers
                                         "0 B/s",  # Download speed
                                         "0 B/s"  # Upload speed
                                     ),
                                     tags=(info_hash,)  # Store hash as tag
                                     )

    def update_torrent_progress(self, info_hash: str, **kwargs):
        """Update specific torrent's progress info"""
        for item in self.torrent_list.get_children():
            item_tags = self.torrent_list.item(item, 'tags')
            if item_tags and item_tags[0] == info_hash:
                values = list(self.torrent_list.item(item, 'values'))

                if 'progress' in kwargs:
                    values[2] = f"{kwargs['progress']}%"
                if 'status' in kwargs:
                    values[3] = kwargs['status']
                if 'peers' in kwargs:
                    values[4] = str(kwargs['peers'])
                if 'download_speed' in kwargs:
                    values[5] = kwargs['download_speed']
                if 'upload_speed' in kwargs:
                    values[6] = kwargs['upload_speed']

                self.torrent_list.item(item, values=values)
                break

    def log_message(self, message: str):
        """Add message to log"""
        self.log_text.configure(state='normal')
        self.log_text.insert('end', message + '\n')
        self.log_text.configure(state='disabled')
        self.log_text.see('end')

    def start_torrent(self):
        """Start selected torrent"""
        selected = self.torrent_list.selection()
        if selected and self.client:
            item = self.torrent_list.item(selected[0])
            info_hash = item['tags'][0] if item['tags'] else None
            if info_hash:
                asyncio.create_task(self.client.download_torrent(info_hash))

    def pause_torrent(self):
        """Pause selected torrent"""
        selected = self.torrent_list.selection()
        if selected and self.client:
            item = self.torrent_list.item(selected[0])
            info_hash = item['tags'][0] if item['tags'] else None
            if info_hash:
                asyncio.create_task(self.client.pause_torrent(info_hash))

    def remove_torrent(self):
        """Remove selected torrent"""
        selected = self.torrent_list.selection()
        if selected and self.client:
            item = self.torrent_list.item(selected[0])
            info_hash = item['tags'][0] if item['tags'] else None
            if info_hash:
                asyncio.create_task(self.client.remove_torrent(info_hash))

    def add_torrent(self):
        """Add torrent file"""
        file_path = filedialog.askopenfilename(
            title="Select Torrent File",
            filetypes=[("Torrent Files", "*.torrent")]
        )
        if file_path and self.client:
            asyncio.create_task(self.client.add_torrent(file_path))

    def add_magnet(self):
        """Add magnet link"""
        magnet = simpledialog.askstring(
            "Magnet Link",
            "Enter magnet URL:",
            parent=self
        )
        if magnet and self.client:
            self.log_message(f"Adding magnet link: {magnet}")
            # TODO: Implement magnet link handling

    async def start_ui(self):
        """Start the UI main loop"""
        while True:
            self.update()
            await asyncio.sleep(0.1)


if __name__ == "__main__":
    async def test_ui():
        ui = BitTorrentUI(client=None)
        await ui.start_ui()


    asyncio.run(test_ui())