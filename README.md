# YouTube Downloader (Tkinter + yt-dlp)

A simple Windows desktop app to download YouTube as MP4 video or MP3 audio. Choose quality/bitrate and files are saved into the `downloads/` folder inside this project.

## Features
- Paste a YouTube URL
- Choose MP4 (video) or MP3 (audio)
- Select quality (1080p/720p/480p/360p/Best) or MP3 bitrate (320k/192k/128k)
- Progress bar and log output
- Auto-creates `downloads/` folder in the project directory

## Requirements
- Python 3.9+
- yt-dlp (installed via requirements.txt)
- FFmpeg (required only for MP3 conversion)

## Setup (Windows PowerShell)
1) Create a virtual environment (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

2) Install dependencies:

```powershell
pip install -r requirements.txt
```

3) (Optional but recommended for MP3) Install FFmpeg and ensure it is on PATH. One option with winget:

```powershell
winget install --id Gyan.FFmpeg -e --source winget
```

If you install FFmpeg manually, add its `bin` directory (that contains `ffmpeg.exe` and `ffprobe.exe`) to your PATH, then restart the terminal.

## Run the app
```powershell
python .\main.py
```

Downloads will be saved to:
```
<project-folder>\downloads\
```

## Notes
- For MP4, the app prefers MP4 video + M4A audio. If not available, it falls back to the best available.
- For MP3, the app downloads best audio and converts to MP3 with your selected bitrate using FFmpeg.
- The app downloads a single URL at a time and ignores playlists.
