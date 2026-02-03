import os
import shutil
import threading
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import yt_dlp as ytdlp
except ImportError:
    ytdlp = None

APP_TITLE = "YouTube Downloader"
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")

QUALITY_OPTIONS_MP4 = [
    "Best",
    "1080p",
    "720p",
    "480p",
    "360p",
    "Audio-only (m4a)",
]

BITRATE_OPTIONS_MP3 = [
    "320k",
    "192k",
    "128k",
]


def ensure_download_dir():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def configure_ffmpeg_path():
    """Ensure ffmpeg is discoverable even if the shell PATH wasn't refreshed yet."""
    # If already resolvable, nothing to do
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    candidates = []
    # Winget shims directory
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Microsoft", "WinGet", "Links"))
    # Common manual installs
    candidates.extend([
        r"C:\\ffmpeg\\bin",
        r"C:\\Program Files\\ffmpeg\\bin",
        r"C:\\Program Files (x86)\\ffmpeg\\bin",
    ])
    for p in candidates:
        if p and os.path.isdir(p) and p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
    # No hard fail here; yt-dlp error handling will inform the user if still missing


def get_ffmpeg_location() -> tuple[str | None, str | None]:
    """Return (directory, exe_path) for ffmpeg if found, else (None, None)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return os.path.dirname(exe), exe
    # Prefer: explicit WinGet Gyan.FFmpeg package bin
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        wg_packages = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(wg_packages):
            try:
                for name in os.listdir(wg_packages):
                    if name.startswith("Gyan.FFmpeg_"):
                        cand = os.path.join(wg_packages, name)
                        # Common structure: ffmpeg-<ver>-full_build/bin
                        for sub in ("bin", os.path.join("ffmpeg-8.0.1-full_build", "bin")):
                            p = os.path.join(cand, sub)
                            ff = os.path.join(p, "ffmpeg.exe")
                            fp = os.path.join(p, "ffprobe.exe")
                            if os.path.isfile(ff) and os.path.isfile(fp):
                                return p, ff
                        # Fallback: scan shallow
                        for n2 in os.listdir(cand):
                            p = os.path.join(cand, n2, "bin")
                            ff = os.path.join(p, "ffmpeg.exe")
                            fp = os.path.join(p, "ffprobe.exe")
                            if os.path.isfile(ff) and os.path.isfile(fp):
                                return p, ff
            except Exception:
                pass
    # Fall back: scan common locations
    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Microsoft", "WinGet", "Links"))
        candidates.append(os.path.join(local_appdata, "Programs"))
        candidates.append(local_appdata)
    candidates.extend([
        r"C:\\ffmpeg\\bin",
        r"C:\\Program Files\\ffmpeg\\bin",
        r"C:\\Program Files (x86)\\ffmpeg\\bin",
    ])
    # First, quick non-recursive checks
    for base in list(candidates):
        if not base or not os.path.isdir(base):
            continue
        # Check base and base/bin
        for check in (base, os.path.join(base, "bin")):
            ff = os.path.join(check, "ffmpeg.exe")
            fp = os.path.join(check, "ffprobe.exe")
            if os.path.isfile(ff) and os.path.isfile(fp):
                return check, ff
    # Recursive scan with safety cap
    scanned = 0
    max_scans = 2000
    for root in candidates:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            scanned += 1
            if scanned > max_scans:
                break
            if "ffmpeg.exe" in filenames and "ffprobe.exe" in filenames:
                return dirpath, os.path.join(dirpath, "ffmpeg.exe")
    return None, None

def build_format_string(filetype: str, quality: str) -> tuple[str, dict]:
    """
    Returns a (format, extra_opts) pair for yt-dlp based on UI choices.
    extra_opts may include postprocessors.
    """
    extra_opts: dict = {}
    if filetype == "MP4":
        if quality == "Best":
            fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        elif quality == "1080p":
            fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]"
        elif quality == "720p":
            fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]"
        elif quality == "480p":
            fmt = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]"
        elif quality == "360p":
            fmt = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]"
        else:  # Audio-only (m4a)
            fmt = "bestaudio[ext=m4a]/bestaudio/best"
        return fmt, extra_opts
    else:  # MP3
        # Download best audio and convert to mp3 via ffmpeg postprocessor
        bitrate = quality.replace("kbps", "k") if quality.endswith("kbps") else quality
        fmt = "bestaudio/best"
        extra_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate.replace("k", ""),
            }
        ]
        # Better filename handling after conversion
        extra_opts["postprocessor_args"] = ["-ar", "44100"]
        return fmt, extra_opts


def progressive_fmt_for_height(max_h: int | None) -> str:
    """Return a yt-dlp format selector that ensures progressive (no-merge) MP4.
    If max_h is None, pick best progressive MP4.
    """
    base = "best[acodec!=none][vcodec!=none][ext=mp4]"
    if max_h:
        return f"{base}[height<={max_h}]/{base}"
    return base


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("680x420")
        self.resizable(True, False)
        ensure_download_dir()
        configure_ffmpeg_path()

        self.url_var = tk.StringVar()
        self.type_var = tk.StringVar(value="MP4")
        self.quality_var = tk.StringVar(value=QUALITY_OPTIONS_MP4[0])

        self._build_ui()

    def _build_ui(self):
        pad = 10

        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        # URL
        ttk.Label(frm, text="YouTube URL").grid(row=0, column=0, sticky="w")
        url_entry = ttk.Entry(frm, textvariable=self.url_var, width=70)
        url_entry.grid(row=1, column=0, columnspan=3, sticky="we", pady=(0, pad))
        url_entry.focus_set()

        # Type selection
        ttk.Label(frm, text="Format").grid(row=2, column=0, sticky="w")
        rb_mp4 = ttk.Radiobutton(frm, text="MP4 (video)", value="MP4", variable=self.type_var, command=self._on_type_change)
        rb_mp3 = ttk.Radiobutton(frm, text="MP3 (audio)", value="MP3", variable=self.type_var, command=self._on_type_change)
        rb_mp4.grid(row=3, column=0, sticky="w")
        rb_mp3.grid(row=3, column=1, sticky="w")

        # Quality
        self.quality_label = ttk.Label(frm, text="Quality")
        self.quality_label.grid(row=4, column=0, sticky="w", pady=(pad//2, 0))

        self.quality_combo = ttk.Combobox(frm, textvariable=self.quality_var, values=QUALITY_OPTIONS_MP4, state="readonly", width=20)
        self.quality_combo.grid(row=5, column=0, sticky="w")

        # Download button
        self.download_btn = ttk.Button(frm, text="Download", command=self._on_download)
        self.download_btn.grid(row=5, column=2, sticky="e")

        # Progress
        self.progress = ttk.Progressbar(frm, orient="horizontal", length=400, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky="we", pady=(pad, 0))

        # Status/log
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(frm, textvariable=self.status_var).grid(row=7, column=0, columnspan=3, sticky="w", pady=(5, 0))

        self.log = tk.Text(frm, height=10, wrap="word")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(5, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=3, sticky="we", pady=(8, 0))
        self.clear_btn = ttk.Button(btns, text="Clear", command=self._on_clear)
        self.clear_btn.pack(side=tk.LEFT)
        self.open_btn = ttk.Button(btns, text="Open Downloads", command=self._on_open_downloads)
        self.open_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.restart_btn = ttk.Button(btns, text="Restart", command=self._on_restart)
        self.restart_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.close_btn = ttk.Button(btns, text="Close", command=self._on_close)
        self.close_btn.pack(side=tk.LEFT, padx=(8, 0))

        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=0)
        frm.columnconfigure(2, weight=0)
        frm.rowconfigure(8, weight=1)

    def _on_type_change(self):
        if self.type_var.get() == "MP3":
            self.quality_combo.configure(values=BITRATE_OPTIONS_MP3)
            self.quality_var.set(BITRATE_OPTIONS_MP3[0])
            self.quality_label.configure(text="Bitrate")
        else:
            self.quality_combo.configure(values=QUALITY_OPTIONS_MP4)
            self.quality_var.set(QUALITY_OPTIONS_MP4[0])
            self.quality_label.configure(text="Quality")

    def _append_log(self, text: str):
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def _progress_hook(self, d):
        # Called by yt-dlp
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            pct = (downloaded / total * 100) if total else 0
            self.after(0, lambda: self._update_progress(pct, d.get('speed'), d.get('eta')))
        elif status == 'finished':
            self.after(0, lambda: self._update_progress(100, None, None, finished=True))

    def _update_progress(self, percent, speed, eta, finished=False):
        self.progress['value'] = percent
        if finished:
            self.status_var.set("Download complete. Processing...")
        else:
            spd = f" | {speed/1024:.1f} KiB/s" if speed else ""
            eta_txt = f" | ETA {int(eta)}s" if eta is not None else ""
            self.status_var.set(f"Downloading... {percent:.1f}%{spd}{eta_txt}")

    def _on_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a YouTube URL.")
            return
        if ytdlp is None:
            messagebox.showerror("yt-dlp missing", "yt-dlp is not installed. Please install dependencies from requirements.txt")
            return

        filetype = self.type_var.get()
        quality = self.quality_var.get()

        self.download_btn.configure(state=tk.DISABLED)
        self.status_var.set("Starting download...")
        self.progress['value'] = 0
        self._append_log(f"URL: {url}")
        self._append_log(f"Type: {filetype} | Quality: {quality}")

        threading.Thread(target=self._run_download, args=(url, filetype, quality), daemon=True).start()

    def _on_clear(self):
        self.url_var.set("")
        self.type_var.set("MP4")
        self._on_type_change()
        self.quality_var.set(QUALITY_OPTIONS_MP4[0])
        self.progress['value'] = 0
        self.status_var.set("Idle")
        self.log.delete('1.0', tk.END)
        self.download_btn.configure(state=tk.NORMAL)

    def _on_restart(self):
        py = sys.executable
        args = [py] + sys.argv
        try:
            subprocess.Popen(args, cwd=os.path.dirname(__file__) or None)
        finally:
            os._exit(0)

    def _on_close(self):
        self.destroy()

    def _on_open_downloads(self):
        ensure_download_dir()
        try:
            os.startfile(DOWNLOAD_DIR)
        except Exception as e:
            messagebox.showerror("Open folder failed", str(e))

    def _run_download(self, url: str, filetype: str, quality: str):
        fmt, extra = build_format_string(filetype, quality)
        outtmpl = os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s')

        ydl_opts = {
            'format': fmt,
            'progress_hooks': [self._progress_hook],
            'outtmpl': outtmpl,
            'noplaylist': True,
            'merge_output_format': 'mp4' if filetype == 'MP4' else None,
            'quiet': True,
            'no_warnings': True,
        }

        # Prefer ffmpeg and pass explicit location if available
        ffmpeg_dir, ffmpeg_exe = get_ffmpeg_location()
        if ffmpeg_dir:
            # Point to directory so yt-dlp can find both ffmpeg and ffprobe
            ydl_opts['ffmpeg_location'] = ffmpeg_dir
            ydl_opts['prefer_ffmpeg'] = True
            self.after(0, lambda: self._append_log(f"Using FFmpeg dir: {ffmpeg_dir}"))
        else:
            self.after(0, lambda: self._append_log("WARNING: FFmpeg not found on system PATH or WinGet Packages"))

        # If no FFmpeg and MP4 selected, avoid merge-only formats by forcing progressive
        if filetype == 'MP4' and not ffmpeg_dir:
            cap_map = {
                'Best': None,
                '1080p': 720,  # 1080p usually requires merge; fallback to 720p progressive
                '720p': 720,
                '480p': 480,
                '360p': 360,
                'Audio-only (m4a)': None,
            }
            cap = cap_map.get(quality, None)
            ydl_opts['format'] = progressive_fmt_for_height(cap)
            self.after(0, lambda: self._append_log("No FFmpeg detected: using progressive MP4 (no merge) format"))

        # Merge extra opts
        for k, v in extra.items():
            ydl_opts[k] = v

        # Better console logging into the text box
        class Logger:
            def debug(inner, msg):
                if msg.strip():
                    self.after(0, lambda m=msg: self._append_log(str(m)))
            def warning(inner, msg):
                if msg.strip():
                    self.after(0, lambda m=msg: self._append_log("WARNING: " + str(m)))
            def error(inner, msg):
                if msg.strip():
                    self.after(0, lambda m=msg: self._append_log("ERROR: " + str(m)))

        ydl_opts['logger'] = Logger()

        try:
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self.after(0, lambda: self.status_var.set(f"Done. Saved to: {DOWNLOAD_DIR}"))
        except Exception as e:
            # Handle missing ffmpeg case explicitly if converting to mp3
            if filetype == 'MP3' and ('ffmpeg' in str(e).lower() or 'ffprobe' in str(e).lower()):
                msg = (
                    "FFmpeg is required for MP3 conversion.\n"
                    "Install it and ensure it's on PATH, then try again."
                )
                self.after(0, lambda: messagebox.showerror("FFmpeg required", msg))
            else:
                self.after(0, lambda: messagebox.showerror("Download failed", str(e)))
            self.after(0, lambda: self.status_var.set("Failed."))
        finally:
            self.after(0, lambda: self.download_btn.configure(state=tk.NORMAL))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
