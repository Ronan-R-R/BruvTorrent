import asyncio
import hashlib
import logging
import os
import struct
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Set

# Security imports
import ssl
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# UI imports
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import webbrowser

# Constants
DEFAULT_PIECE_LENGTH = 2 ** 14  # 16KB
MAX_PEER_CONNECTIONS = 50
BLOCK_SIZE = 2 ** 14  # 16KB
DEFAULT_PORT = 6881
DHT_PORT = 6882
MAX_CONCURRENT_DOWNLOADS = 5


class TorrentState(Enum):
    QUEUED = auto()
    DOWNLOADING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    ERROR = auto()


@dataclass
class TorrentFile:
    length: int
    path: str
    md5sum: Optional[str] = None


@dataclass
class TorrentMetadata:
    announce: str
    info_hash: bytes
    piece_length: int
    pieces: List[bytes]
    files: List[TorrentFile]
    name: str
    length: Optional[int] = None
    private: bool = False
    created_by: Optional[str] = None
    creation_date: Optional[int] = None
    comment: Optional[str] = None


@dataclass
class Peer:
    ip: str
    port: int
    peer_id: Optional[bytes] = None
    connected: bool = False
    choked: bool = True
    interested: bool = False
    bitfield: Optional[bytes] = None
    download_speed: float = 0.0
    upload_speed: float = 0.0


class BitTorrentClient:
    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)

        self.torrents: Dict[str, TorrentMetadata] = {}
        self.peers: Dict[str, Dict[Tuple[str, int], Peer]] = defaultdict(dict)
        self.torrent_states: Dict[str, TorrentState] = {}
        self.download_progress: Dict[str, float] = {}

        # Security setup
        self.ssl_context = self._create_ssl_context()

        # DHT setup
        self.dht = DHTNode(DHT_PORT)

        # Rate limiting
        self.max_download_rate = 0  # 0 means unlimited
        self.max_upload_rate = 0

        # Initialize logging
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('bittorrent_client.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def _create_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        context.set_ciphers('ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384')
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    async def add_torrent(self, torrent_file: str) -> bool:
        """Add a new torrent to the client."""
        try:
            metadata = self._parse_torrent_file(torrent_file)
            if metadata.info_hash in self.torrents:
                self.logger.warning(f"Torrent already added: {metadata.name}")
                return False

            self.torrents[metadata.info_hash] = metadata
            self.torrent_states[metadata.info_hash] = TorrentState.QUEUED
            self.download_progress[metadata.info_hash] = 0.0

            # Start peer discovery
            asyncio.create_task(self._discover_peers(metadata))

            return True
        except Exception as e:
            self.logger.error(f"Error adding torrent: {e}")
            self.torrent_states[metadata.info_hash] = TorrentState.ERROR
            return False

    def _parse_torrent_file(self, torrent_file: str) -> TorrentMetadata:
        """Parse a torrent file and return its metadata."""
        with open(torrent_file, 'rb') as f:
            torrent_data = self._decode_bencode(f.read())

        info = torrent_data['info']
        info_hash = hashlib.sha1(self._encode_bencode(info)).digest()

        # Handle single file vs multi-file torrents
        if 'files' in info:
            files = [
                TorrentFile(
                    length=file['length'],
                    path=os.path.join(*file['path']),
                    md5sum=file.get('md5sum')
                )
                for file in info['files']
            ]
            length = None
        else:
            files = [
                TorrentFile(
                    length=info['length'],
                    path=info['name'],
                    md5sum=info.get('md5sum')
                )
            ]
            length = info['length']

        return TorrentMetadata(
            announce=torrent_data['announce'],
            info_hash=info_hash,
            piece_length=info['piece length'],
            pieces=self._split_pieces(info['pieces']),
            files=files,
            name=info['name'],
            length=length,
            private=info.get('private', False),
            created_by=torrent_data.get('created by'),
            creation_date=torrent_data.get('creation date'),
            comment=torrent_data.get('comment')
        )

    def _split_pieces(self, pieces: bytes) -> List[bytes]:
        """Split the pieces hash list into individual hashes."""
        return [pieces[i:i + 20] for i in range(0, len(pieces), 20)]

    async def _discover_peers(self, metadata: TorrentMetadata):
        """Discover peers for a torrent using trackers and DHT."""
        try:
            # Contact trackers
            if not metadata.private:
                tracker_peers = await self._contact_tracker(metadata)
                self._add_peers(metadata.info_hash, tracker_peers)

            # Use DHT for peer discovery
            if not metadata.private:
                dht_peers = await self.dht.get_peers(metadata.info_hash)
                self._add_peers(metadata.info_hash, dht_peers)

        except Exception as e:
            self.logger.error(f"Error discovering peers: {e}")

    async def _contact_tracker(self, metadata: TorrentMetadata) -> List[Peer]:
        """Contact the tracker and get the list of peers."""
        # Implementation of tracker communication
        pass

    def _add_peers(self, info_hash: bytes, peers: List[Peer]):
        """Add discovered peers to the torrent."""
        for peer in peers:
            self.peers[info_hash][(peer.ip, peer.port)] = peer

        # Start connections if we're downloading this torrent
        if self.torrent_states.get(info_hash) == TorrentState.DOWNLOADING:
            asyncio.create_task(self._connect_to_peers(info_hash))

    async def _connect_to_peers(self, info_hash: bytes):
        """Establish connections with peers for a torrent."""
        metadata = self.torrents[info_hash]
        connected_peers = 0

        for peer in list(self.peers[info_hash].values()):
            if connected_peers >= MAX_PEER_CONNECTIONS:
                break

            if not peer.connected:
                try:
                    await self._handshake_with_peer(info_hash, peer)
                    peer.connected = True
                    connected_peers += 1

                    # Start peer communication
                    asyncio.create_task(self._handle_peer_communication(info_hash, peer))
                except Exception as e:
                    self.logger.warning(f"Failed to connect to peer {peer.ip}:{peer.port}: {e}")
                    peer.connected = False

    async def _handshake_with_peer(self, info_hash: bytes, peer: Peer):
        """Perform BitTorrent handshake with a peer."""
        # Implementation of handshake protocol
        pass

    async def _handle_peer_communication(self, info_hash: bytes, peer: Peer):
        """Handle ongoing communication with a peer."""
        # Implementation of peer communication
        pass

    async def download_torrent(self, info_hash: bytes):
        """Start downloading a torrent."""
        if info_hash not in self.torrents:
            raise ValueError("Torrent not found")

        if self.torrent_states[info_hash] in {TorrentState.DOWNLOADING, TorrentState.COMPLETED}:
            return

        self.torrent_states[info_hash] = TorrentState.DOWNLOADING
        await self._connect_to_peers(info_hash)

    async def pause_torrent(self, info_hash: bytes):
        """Pause a torrent download."""
        if info_hash in self.torrents:
            self.torrent_states[info_hash] = TorrentState.PAUSED

    async def resume_torrent(self, info_hash: bytes):
        """Resume a paused torrent."""
        if info_hash in self.torrents and self.torrent_states[info_hash] == TorrentState.PAUSED:
            await self.download_torrent(info_hash)

    async def remove_torrent(self, info_hash: bytes, delete_files: bool = False):
        """Remove a torrent from the client."""
        if info_hash in self.torrents:
            del self.torrents[info_hash]
            del self.torrent_states[info_hash]
            del self.download_progress[info_hash]

            if delete_files:
                # Delete downloaded files
                pass

    def get_torrent_info(self, info_hash: bytes) -> Optional[Dict]:
        """Get information about a torrent."""
        if info_hash not in self.torrents:
            return None

        metadata = self.torrents[info_hash]
        return {
            'name': metadata.name,
            'size': metadata.length or sum(f.length for f in metadata.files),
            'progress': self.download_progress.get(info_hash, 0.0),
            'state': self.torrent_states.get(info_hash, TorrentState.QUEUED).name,
            'peers': len(self.peers.get(info_hash, {})),
            'download_speed': 0,  # TODO: Calculate
            'upload_speed': 0,  # TODO: Calculate
            'files': [{'path': f.path, 'size': f.length} for f in metadata.files]
        }


class DHTNode:
    """Distributed Hash Table implementation for peer discovery."""

    def __init__(self, port: int):
        self.port = port
        self.node_id = self._generate_node_id()
        self.routing_table = {}
        self.logger = logging.getLogger('DHT')

    def _generate_node_id(self) -> bytes:
        """Generate a random node ID for DHT."""
        return os.urandom(20)

    async def get_peers(self, info_hash: bytes) -> List[Peer]:
        """Find peers for a given info hash using DHT."""
        # Implementation of DHT peer discovery
        return []

    async def start(self):
        """Start the DHT node."""
        # Implementation of DHT server
        pass


class BitTorrentUI(tk.Tk):
    """Graphical user interface for the BitTorrent client."""

    def __init__(self, client: BitTorrentClient):
        super().__init__()
        self.client = client
        self.title("Python BitTorrent Client")
        self.geometry("1000x700")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Configure styles
        self.style = ttk.Style()
        self.style.configure('Treeview', rowheight=25)
        self.style.configure('TButton', padding=6)
        self.style.configure('TFrame', padding=10)

        self._setup_ui()
        self._setup_menu()

        # Start periodic updates
        self.after(1000, self.update_ui)

    def _setup_menu(self):
        """Setup the application menu bar."""
        menubar = tk.Menu(self)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add Torrent", command=self.add_torrent)
        file_menu.add_command(label="Add Magnet Link", command=self.add_magnet)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Dark Mode", command=self.toggle_dark_mode)
        view_menu.add_command(label="Light Mode", command=self.toggle_light_mode)
        menubar.add_cascade(label="View", menu=view_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _setup_ui(self):
        """Setup the main user interface."""
        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Torrent list
        self.torrent_list = ttk.Treeview(
            main_frame,
            columns=('name', 'size', 'progress', 'status', 'peers', 'download', 'upload'),
            show='headings'
        )

        # Configure columns
        self.torrent_list.heading('name', text='Name')
        self.torrent_list.heading('size', text='Size')
        self.torrent_list.heading('progress', text='Progress')
        self.torrent_list.heading('status', text='Status')
        self.torrent_list.heading('peers', text='Peers')
        self.torrent_list.heading('download', text='Download')
        self.torrent_list.heading('upload', text='Upload')

        self.torrent_list.column('name', width=200)
        self.torrent_list.column('size', width=100, anchor=tk.E)
        self.torrent_list.column('progress', width=100, anchor=tk.E)
        self.torrent_list.column('status', width=100, anchor=tk.CENTER)
        self.torrent_list.column('peers', width=80, anchor=tk.E)
        self.torrent_list.column('download', width=100, anchor=tk.E)
        self.torrent_list.column('upload', width=100, anchor=tk.E)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.torrent_list.yview)
        self.torrent_list.configure(yscrollcommand=scrollbar.set)

        # Pack torrent list
        self.torrent_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Control buttons
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        self.start_button = ttk.Button(control_frame, text="Start", command=self.start_torrent)
        self.pause_button = ttk.Button(control_frame, text="Pause", command=self.pause_torrent)
        self.remove_button = ttk.Button(control_frame, text="Remove", command=self.remove_torrent)
        self.settings_button = ttk.Button(control_frame, text="Settings", command=self.show_settings)

        self.start_button.pack(side=tk.LEFT, padx=5)
        self.pause_button.pack(side=tk.LEFT, padx=5)
        self.remove_button.pack(side=tk.LEFT, padx=5)
        self.settings_button.pack(side=tk.RIGHT, padx=5)

        # Details panel
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Files tab
        self.files_frame = ttk.Frame(self.notebook)
        self.files_tree = ttk.Treeview(self.files_frame, columns=('name', 'size', 'progress'), show='headings')
        self.files_tree.heading('name', text='File')
        self.files_tree.heading('size', text='Size')
        self.files_tree.heading('progress', text='Progress')

        files_scroll = ttk.Scrollbar(self.files_frame, orient=tk.VERTICAL, command=self.files_tree.yview)
        self.files_tree.configure(yscrollcommand=files_scroll.set)

        self.files_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        files_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.notebook.add(self.files_frame, text='Files')

        # Peers tab
        self.peers_frame = ttk.Frame(self.notebook)
        self.peers_tree = ttk.Treeview(self.peers_frame, columns=('ip', 'client', 'down_speed', 'up_speed'),
                                       show='headings')
        self.peers_tree.heading('ip', text='IP Address')
        self.peers_tree.heading('client', text='Client')
        self.peers_tree.heading('down_speed', text='Download Speed')
        self.peers_tree.heading('up_speed', text='Upload Speed')

        peers_scroll = ttk.Scrollbar(self.peers_frame, orient=tk.VERTICAL, command=self.peers_tree.yview)
        self.peers_tree.configure(yscrollcommand=peers_scroll.set)

        self.peers_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        peers_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.notebook.add(self.peers_frame, text='Peers')

        # Log tab
        self.log_frame = ttk.Frame(self.notebook)
        self.log_text = ScrolledText(self.log_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.notebook.add(self.log_frame, text='Log')

        # Bind events
        self.torrent_list.bind('<<TreeviewSelect>>', self.on_torrent_select)

    def add_torrent(self):
        """Add a new torrent file."""
        file_path = filedialog.askopenfilename(
            title="Select Torrent File",
            filetypes=[("Torrent Files", "*.torrent"), ("All Files", "*.*")]
        )

        if file_path:
            asyncio.create_task(self._async_add_torrent(file_path))

    async def _async_add_torrent(self, file_path: str):
        """Async wrapper for adding a torrent."""
        try:
            success = await self.client.add_torrent(file_path)
            if success:
                messagebox.showinfo("Success", "Torrent added successfully")
            else:
                messagebox.showerror("Error", "Failed to add torrent")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add torrent: {str(e)}")

    def add_magnet(self):
        """Add a new torrent via magnet link."""
        magnet_link = simpledialog.askstring("Magnet Link", "Enter magnet link:")
        if magnet_link:
            # TODO: Implement magnet link support
            messagebox.showinfo("Info", "Magnet link support coming soon!")

    def start_torrent(self):
        """Start selected torrent."""
        selected = self.torrent_list.selection()
        if selected:
            item = self.torrent_list.item(selected[0])
            info_hash = item['values'][-1]  # Assuming we store info_hash in hidden column
            asyncio.create_task(self.client.download_torrent(info_hash))

    def pause_torrent(self):
        """Pause selected torrent."""
        selected = self.torrent_list.selection()
        if selected:
            item = self.torrent_list.item(selected[0])
            info_hash = item['values'][-1]
            asyncio.create_task(self.client.pause_torrent(info_hash))

    def remove_torrent(self):
        """Remove selected torrent."""
        selected = self.torrent_list.selection()
        if selected:
            item = self.torrent_list.item(selected[0])
            info_hash = item['values'][-1]

            # Ask for confirmation
            if messagebox.askyesno("Confirm", "Remove this torrent?"):
                delete_files = messagebox.askyesno("Confirm", "Also delete downloaded files?")
                asyncio.create_task(self.client.remove_torrent(info_hash, delete_files))

    def show_settings(self):
        """Show settings dialog."""
        settings_window = tk.Toplevel(self)
        settings_window.title("Settings")

        # Download directory
        ttk.Label(settings_window, text="Download Directory:").grid(row=0, column=0, sticky=tk.W)
        dir_entry = ttk.Entry(settings_window, width=50)
        dir_entry.grid(row=0, column=1, padx=5, pady=5)
        dir_entry.insert(0, str(self.client.download_dir))

        def browse_directory():
            directory = filedialog.askdirectory()
            if directory:
                dir_entry.delete(0, tk.END)
                dir_entry.insert(0, directory)

        ttk.Button(settings_window, text="Browse...", command=browse_directory).grid(row=0, column=2, padx=5)

        # Rate limiting
        ttk.Label(settings_window, text="Max Download Speed (KB/s):").grid(row=1, column=0, sticky=tk.W)
        download_speed = ttk.Entry(settings_window, width=10)
        download_speed.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        download_speed.insert(0, str(self.client.max_download_rate))

        ttk.Label(settings_window, text="Max Upload Speed (KB/s):").grid(row=2, column=0, sticky=tk.W)
        upload_speed = ttk.Entry(settings_window, width=10)
        upload_speed.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        upload_speed.insert(0, str(self.client.max_upload_rate))

        def save_settings():
            try:
                self.client.download_dir = Path(dir_entry.get())
                self.client.max_download_rate = int(download_speed.get())
                self.client.max_upload_rate = int(upload_speed.get())
                settings_window.destroy()
                messagebox.showinfo("Success", "Settings saved")
            except ValueError:
                messagebox.showerror("Error", "Please enter valid numbers for speed limits")

        ttk.Button(settings_window, text="Save", command=save_settings).grid(row=3, column=1, pady=10)

    def toggle_dark_mode(self):
        """Switch to dark theme."""
        self.style.theme_use('clam')
        self.configure(background='#333')
        self.torrent_list.configure(style='Treeview')

    def toggle_light_mode(self):
        """Switch to light theme."""
        self.style.theme_use('default')
        self.configure(background='SystemButtonFace')
        self.torrent_list.configure(style='Treeview')

    def show_about(self):
        """Show about dialog."""
        about_window = tk.Toplevel(self)
        about_window.title("About Python BitTorrent Client")

        ttk.Label(about_window, text="Python BitTorrent Client", font=('Arial', 14, 'bold')).pack(pady=10)
        ttk.Label(about_window, text="A modern BitTorrent client written in Python 3.13").pack()
        ttk.Label(about_window, text="\nSecure and efficient torrent downloading").pack()
        ttk.Label(about_window, text=f"Version 1.0.0").pack(pady=10)

        def open_github():
            webbrowser.open("https://github.com/yourusername/python-bittorrent")

        ttk.Button(about_window, text="GitHub Repository", command=open_github).pack(pady=10)

    def on_torrent_select(self, event):
        """Handle torrent selection event."""
        selected = self.torrent_list.selection()
        if selected:
            item = self.torrent_list.item(selected[0])
            info_hash = item['values'][-1]
            self.update_torrent_details(info_hash)

    def update_torrent_details(self, info_hash: bytes):
        """Update the details panel for the selected torrent."""
        info = self.client.get_torrent_info(info_hash)
        if not info:
            return

        # Update files tab
        self.files_tree.delete(*self.files_tree.get_children())
        for file in info['files']:
            self.files_tree.insert('', 'end', values=(
                file['path'],
                self._format_size(file['size']),
                "0%"  # TODO: Add per-file progress
            ))

        # Update peers tab
        self.peers_tree.delete(*self.peers_tree.get_children())
        # TODO: Add actual peer information

    def update_ui(self):
        """Periodically update the UI with current torrent information."""
        self.torrent_list.delete(*self.torrent_list.get_children())

        for info_hash, metadata in self.client.torrents.items():
            info = self.client.get_torrent_info(info_hash)
            if info:
                self.torrent_list.insert('', 'end', values=(
                    info['name'],
                    self._format_size(info['size']),
                    f"{info['progress']:.1f}%",
                    info['state'],
                    info['peers'],
                    self._format_speed(info['download_speed']),
                    self._format_speed(info['upload_speed']),
                    info_hash  # Hidden column
                ))

        # Schedule next update
        self.after(1000, self.update_ui)

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _format_speed(self, speed: float) -> str:
        """Format speed in bytes/s to human-readable format."""
        if speed <= 0:
            return "0 B/s"

        for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
            if speed < 1024:
                return f"{speed:.1f} {unit}"
            speed /= 1024
        return f"{speed:.1f} TB/s"

    def on_close(self):
        """Handle window close event."""
        if messagebox.askokcancel("Quit", "Do you want to quit the BitTorrent client?"):
            # Clean up resources
            asyncio.create_task(self._async_shutdown())
            self.destroy()

    async def _async_shutdown(self):
        """Perform async cleanup before shutdown."""
        # TODO: Implement proper shutdown
        pass


async def main():
    # Initialize the client
    client = BitTorrentClient()

    # Start DHT node
    await client.dht.start()

    # Start the UI
    root = BitTorrentUI(client)
    root.mainloop()


if __name__ == "__main__":
    asyncio.run(main())