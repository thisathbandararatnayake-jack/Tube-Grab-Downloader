# TubeGrab - a modern YouTube downloader
# Stack: Python 3.10+ | CustomTkinter (UI) | yt-dlp (download engine)
# Only download videos you own or have permission to download

from __future__ import annotations

import queue
import re
import shutil
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError

APP_NAME = "TubeGrab"
ACCENT = "#FF3B3B"
ACCENT_HOVER = "#D92B2B"
MUTED_TEXT = ("gray50", "gray55")
CARD_BG = ("#FFFFFF", "#1A1A1A")
BG_COLOR = ("#F3F4F6", "#0F0F0F")
BORDER_COLOR = ("#E5E7EB", "#2A2A2A")

HAS_FFMPEG = shutil.which("ffmpeg") is not None

QUALITY_OPTIONS: dict[str, int | str | None] = {
    "Best available": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "Audio only": "audio",
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# --------------------------------------------------------------------------- #
# Helpers (Unchanged)
# --------------------------------------------------------------------------- #
def fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "live / unknown length"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_speed(bytes_per_sec: float | None) -> str:
    if not bytes_per_sec:
        return "-- MB/s"
    return f"{bytes_per_sec / 1_048_576:.1f} MB/s"


def clean_error(exc: Exception) -> str:
    text = ANSI_RE.sub("", str(exc)).strip()
    return text.replace("ERROR: ", "", 1) or "Something went wrong."


def build_ydl_options(choice: str, folder: Path, hook) -> dict:
    opts: dict = {
        "outtmpl": str(folder / "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    target = QUALITY_OPTIONS[choice]

    if target == "audio":
        if HAS_FFMPEG:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            opts["format"] = "bestaudio[ext=m4a]/bestaudio"
        return opts

    cap = f"[height<={target}]" if target else ""
    if HAS_FFMPEG:
        opts["format"] = f"bestvideo{cap}[ext=mp4]+bestaudio[ext=m4a]/bestvideo{cap}+bestaudio/best{cap}"
        opts["merge_output_format"] = "mp4"
    else:
        opts["format"] = f"best{cap}[ext=mp4]/best{cap}"
    return opts


# --------------------------------------------------------------------------- #
# UI (Modernized)
# --------------------------------------------------------------------------- #
class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("800x680")
        self.minsize(720, 640)
        self.configure(fg_color=BG_COLOR)

        # State variables
        self.folder = Path.home() / "Downloads"
        self.ui_queue = queue.Queue()
        self.cancel_event = threading.Event()

        # Fonts
        self.font_title = ctk.CTkFont(family="Segoe UI", size=28, weight="bold")
        self.font_subtitle = ctk.CTkFont(family="Segoe UI", size=14)
        self.font_main = ctk.CTkFont(family="Segoe UI", size=13)
        self.font_btn = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")

        # Main Container to hold everything with consistent padding
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=40, pady=35)

        # --- Header
        header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 25))

        ctk.CTkLabel(
            header_frame,
            text=f"▶  {APP_NAME}",
            font=self.font_title,
            text_color=(ACCENT, ACCENT)
        ).pack(anchor="w")

        ctk.CTkLabel(
            header_frame,
            text="High-performance media downloader powered by yt-dlp.",
            font=self.font_subtitle,
            text_color=MUTED_TEXT
        ).pack(anchor="w", pady=(2, 0))

        # --- Card 1: URL & Info
        url_card = ctk.CTkFrame(
            self.main_container,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR
        )
        url_card.pack(fill="x", pady=(0, 16))
        url_card.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            url_card,
            height=44,
            corner_radius=8,
            border_width=1,
            placeholder_text="Paste YouTube URL here...",
            font=self.font_main,
        )
        self.url_entry.grid(row=0, column=0, padx=(20, 12), pady=(20, 12), sticky="ew")
        self.url_entry.bind("<Return>", lambda _e: self.fetch_info())

        self.fetch_btn = ctk.CTkButton(
            url_card,
            text="Fetch Info",
            width=110,
            height=44,
            corner_radius=8,
            font=self.font_btn,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self.fetch_info,
        )
        self.fetch_btn.grid(row=0, column=1, padx=(0, 20), pady=(20, 12))

        # Divider line
        divider = ctk.CTkFrame(url_card, height=1, fg_color=BORDER_COLOR)
        divider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20)

        self.info_label = ctk.CTkLabel(
            url_card,
            text="🎬  No video loaded yet. Paste a link above.",
            font=self.font_main,
            anchor="w",
            justify="left",
            text_color=MUTED_TEXT,
        )
        self.info_label.grid(row=2, column=0, columnspan=2, padx=20, pady=(12, 20), sticky="ew")

        # --- Card 2: Configuration
        opt_card = ctk.CTkFrame(
            self.main_container,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR
        )
        opt_card.pack(fill="x", pady=(0, 16))
        opt_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            opt_card, text="⚙️  Quality", font=self.font_btn
        ).grid(row=0, column=0, padx=(20, 12), pady=20, sticky="w")

        self.quality_menu = ctk.CTkOptionMenu(
            opt_card,
            values=list(QUALITY_OPTIONS),
            width=180,
            height=36,
            corner_radius=6,
            font=self.font_main,
            fg_color=("gray90", "gray20"),
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            text_color=("gray10", "gray90"),
        )
        self.quality_menu.grid(row=0, column=1, pady=20, sticky="w")

        ctk.CTkLabel(
            opt_card, text="📁  Save to", font=self.font_btn
        ).grid(row=0, column=2, padx=(20, 12), pady=20, sticky="w")

        self.folder_btn = ctk.CTkButton(
            opt_card,
            text=self._short_path(self.folder, limit=25),
            command=self.choose_folder,
            height=36,
            corner_radius=6,
            font=self.font_main,
            fg_color=("gray85", "gray20"),
            hover_color=("gray75", "gray30"),
            text_color=("gray10", "gray90"),
        )
        self.folder_btn.grid(row=0, column=3, padx=(0, 20), pady=20, sticky="e")

        # --- Card 3: Status & Progress
        status_card = ctk.CTkFrame(
            self.main_container,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR
        )
        status_card.pack(fill="x", pady=(0, 25))
        status_card.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_card,
            text="Ready.",
            font=self.font_main,
            text_color=MUTED_TEXT,
            anchor="w"
        )
        self.status_label.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="ew")
        self._default_status_color = self.status_label.cget("text_color")

        self.progress = ctk.CTkProgressBar(
            status_card,
            height=8,
            corner_radius=4,
            progress_color=ACCENT
        )
        self.progress.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        self.progress.set(0)

        # --- Action Buttons
        btn_row = ctk.CTkFrame(self.main_container, fg_color="transparent")
        btn_row.pack(fill="x")
        btn_row.grid_columnconfigure(0, weight=1)

        self.download_btn = ctk.CTkButton(
            btn_row,
            text="Download Media",
            height=50,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self.start_download,
        )
        self.download_btn.grid(row=0, column=0, sticky="ew")

        self.cancel_btn = ctk.CTkButton(
            btn_row,
            text="Cancel",
            width=120,
            height=50,
            corner_radius=8,
            font=self.font_btn,
            fg_color=("gray85", "gray20"),
            hover_color=("gray75", "gray30"),
            text_color=("gray10", "gray90"),
            state="disabled",
            command=self.cancel_download,
        )
        self.cancel_btn.grid(row=0, column=1, padx=(12, 0))

        # --- Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=40, pady=25)
        footer.grid_columnconfigure(0, weight=1)

        note = "✓ FFmpeg integrated: Ultra HD & MP3 extraction enabled." if HAS_FFMPEG else "⚠️ FFmpeg missing: Install for 1080p+ and MP3 conversion."
        ctk.CTkLabel(
            footer,
            text=note,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=MUTED_TEXT,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.theme_switch = ctk.CTkSwitch(
            footer,
            text="Dark Mode",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=self._toggle_theme
        )
        self.theme_switch.select()
        self.theme_switch.grid(row=0, column=1, sticky="e")

        # Start listening to background threads
        self.after(100, self._poll_queue)

    # ----- small UI helpers ------------------------------------------------ #
    @staticmethod
    def _short_path(path: Path, limit: int = 35) -> str:
        text = str(path)
        return text if len(text) <= limit else "…" + text[-(limit - 1):]

    def _toggle_theme(self) -> None:
        ctk.set_appearance_mode("dark" if self.theme_switch.get() else "light")

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.configure(
            text=text, text_color=ACCENT if error else self._default_status_color
        )

    def _set_busy(self, busy: bool) -> None:
        self.download_btn.configure(state="disabled" if busy else "normal")
        self.fetch_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")

    # ----- actions --------------------------------------------------------- #
    def choose_folder(self) -> None:
        picked = filedialog.askdirectory(initialdir=str(self.folder))
        if picked:
            self.folder = Path(picked)
            self.folder_btn.configure(text=self._short_path(self.folder, limit=25))

    def fetch_info(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("Paste a link first.", error=True)
            return
        self.fetch_btn.configure(state="disabled", text="Fetching…")
        self._set_status("Looking up video info…")
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def start_download(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("Paste a link first.", error=True)
            return

        self.cancel_event.clear()
        self.progress.set(0)
        self._set_busy(True)
        self._set_status("Starting…")

        opts = build_ydl_options(self.quality_menu.get(), self.folder, self._hook)
        threading.Thread(target=self._download_worker, args=(url, opts), daemon=True).start()

    def cancel_download(self) -> None:
        self.cancel_event.set()
        self._set_status("Cancelling…")

    # ----- worker threads (never touch widgets here; use the queue) -------- #
    def _fetch_worker(self, url: str) -> None:
        try:
            opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            self.ui_queue.put(("info", info))
        except Exception as exc:
            self.ui_queue.put(("error", clean_error(exc)))

    def _download_worker(self, url: str, opts: dict) -> None:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            self.ui_queue.put(("done", None))
        except DownloadCancelled:
            self.ui_queue.put(("cancelled", None))
        except DownloadError as exc:
            if self.cancel_event.is_set():
                self.ui_queue.put(("cancelled", None))
            else:
                self.ui_queue.put(("error", clean_error(exc)))
        except Exception as exc:
            self.ui_queue.put(("error", clean_error(exc)))

    def _hook(self, d: dict) -> None:
        if self.cancel_event.is_set():
            raise DownloadCancelled("Cancelled by user")

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = done / total if total else 0
            eta = d.get("eta")
            eta_text = f"{int(eta)}s left" if eta is not None else "…"
            text = f"Downloading: {frac * 100:5.1f}%   •   {fmt_speed(d.get('speed'))}   •   {eta_text}"
            self.ui_queue.put(("progress", frac, text))
        elif d["status"] == "finished":
            self.ui_queue.put(("status", "Processing and merging files…"))

    # ----- queue -> UI ------------------------------------------------------ #
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, *payload = self.ui_queue.get_nowait()

                if kind == "info":
                    info = payload[0]
                    title = info.get("title", "Unknown title")
                    channel = info.get("uploader") or info.get("channel") or "Unknown"
                    length = fmt_duration(info.get("duration"))
                    self.info_label.configure(
                        text=f"🎬  {title}\n👤  {channel}    ⏱  {length}",
                        text_color=("gray10", "gray90"),
                    )
                    self.fetch_btn.configure(state="normal", text="Fetch Info")
                    self._set_status("Ready to download.")

                elif kind == "progress":
                    self.progress.set(payload[0])
                    self._set_status(payload[1])

                elif kind == "status":
                    self._set_status(payload[0])

                elif kind == "done":
                    self.progress.set(1)
                    self._set_status(f"✅  Done! Saved to: {self._short_path(self.folder, limit=40)}")
                    self._set_busy(False)

                elif kind == "cancelled":
                    self.progress.set(0)
                    self._set_status("⏸  Download cancelled.")
                    self._set_busy(False)

                elif kind == "error":
                    self.progress.set(0)
                    self._set_status(f"⚠️  {payload[0]}", error=True)
                    self.fetch_btn.configure(text="Fetch Info")
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()