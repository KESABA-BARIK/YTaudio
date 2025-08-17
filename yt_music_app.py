import os
import sys
import shutil
import threading
import time
import tempfile
from dataclasses import dataclass, field
from typing import Optional, List, Deque, Tuple
from collections import deque
VLC_PATH = r"C:\Program Files\VideoLAN\VLC"  # change if needed
VLC_DLL = r"C:\Program Files\VideoLAN\VLC\libvlc.dll"
if os.path.isdir(VLC_PATH):
    os.add_dll_directory(VLC_PATH)
# Third-party
import yt_dlp  # pip install yt-dlp
import vlc     # pip install python-vlc

if os.path.exists(VLC_DLL):
    instance = vlc.Instance("--no-video")  # force audio only
else:
    raise FileNotFoundError("❌ Could not find libvlc.dll. Please install VLC.")

# ------------ Config ------------

CACHE_DIR = os.path.join(tempfile.gettempdir(), "yt_music_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

YTDLP_OPTS_BASE = {
    "quiet": True,
    "noprogress": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "format": "bestaudio/best",
    "outtmpl": os.path.join(CACHE_DIR, "%(title)s.%(ext)s"),  # use title
    "restrictfilenames": True,
    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
}


# ------------ Data models ------------

@dataclass
class Track:
    title: str
    url: str
    id: str
    filepath: Optional[str] = None
    duration: Optional[int] = None  # seconds
    from_playlist: bool = False

    def __str__(self):
        mins = None
        if self.duration:
            mins = f"{self.duration // 60}:{self.duration % 60:02d}"
        return f"{self.title} {'['+mins+']' if mins else ''}"

# ------------ YouTube client ------------

class YouTubeClient:
    def __init__(self):
        self._ydl_info = yt_dlp.YoutubeDL({**YTDLP_OPTS_BASE, "skip_download": True})
        self._ydl_dl = yt_dlp.YoutubeDL({**YTDLP_OPTS_BASE, "skip_download": False})

    def search(self, query: str, max_results: int = 5) -> List[Track]:
        info = self._ydl_info.extract_info(f"ytsearch{max_results}:{query}", download=False)
        results: List[Track] = []
        if not info or "entries" not in info:
            return results
        for e in info["entries"] or []:
            results.append(
                Track(
                    title=e.get("title") or "Unknown title",
                    url=e.get("webpage_url") or "",
                    id=e.get("id") or "",
                    duration=e.get("duration"),
                )
            )
        return results

    def get_mix_or_playlist(self, url: str) -> List[Track]:
        # Works for playlists and "Mix" (RD...) links as well
        info = self._ydl_info.extract_info(url, download=False)
        tracks: List[Track] = []
        if not info:
            return tracks

        if info.get("_type") == "playlist" and "entries" in info:
            for e in info["entries"] or []:
                if not e:
                    continue
                tracks.append(
                    Track(
                        title=e.get("title") or "Unknown title",
                        url=e.get("webpage_url") or "",
                        id=e.get("id") or "",
                        duration=e.get("duration"),
                        from_playlist=True,
                    )
                )
        else:
            # Single video URL
            tracks.append(
                Track(
                    title=info.get("title") or "Unknown title",
                    url=info.get("webpage_url") or "",
                    id=info.get("id") or "",
                    duration=info.get("duration"),
                    from_playlist=False,
                )
            )
        return tracks

    def download(self, track: Track) -> Tuple[Optional[str], Optional[str]]:
        """
        Download audio if not already in cache. Returns (filepath, err).
        """
        # Check if already downloaded by title
        for ext in ("mp3", "m4a", "webm", "opus", "mp4", "mkv"):
            candidate = os.path.join(CACHE_DIR, f"{track.title}.{ext}")
            if os.path.exists(candidate):
                return candidate, None

        try:
            info = self._ydl_dl.extract_info(track.url, download=True)

            # Look for the final filename in requested_downloads
            if "requested_downloads" in info and info["requested_downloads"]:
                fp = info["requested_downloads"][0]["filepath"]
            else:
                fp = info.get("_filename")

            if fp and os.path.exists(fp):
                return fp, None
            else:
                return None, "File not found after download (postprocess mismatch)."

        except Exception as e:
            return None, f"Download failed: {e}"


# ------------ Player ------------

# class Player:
#     """
#     VLC-based player that plays one track at a time and deletes the file upon completion.
#     """
#     def __init__(self):
#         self._instance = instance
#         self._player = self._instance.media_player_new()
#         self._event_manager = self._player.event_manager()
#         self._event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end)
#         self._event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_error)
#
#         self._current: Optional[Track] = None
#         self._on_track_end = None  # callback(track)
#         self._lock = threading.Lock()
#         self._paused = False
#
#     def set_on_track_end(self, cb):
#         self._on_track_end = cb
#
#     def play(self, track):
#         with self._lock:
#             self.stop()
#             if not track.filepath or not os.path.exists(track.filepath):
#                 print(f"! Cannot play: file missing at {track.filepath}")
#                 return
#             print(f"Playing: {track.filepath}")
#             media = self._instance.media_new_path(track.filepath)
#             self._player.set_media(media)
#             self._current = track
#             result = self._player.play()
#             print(f"VLC play result: {result}")
#             # Force a state check after a short delay
#             def check_state():
#                 time.sleep(1)
#                 state = self._player.get_state()
#                 print(f"Player state after 1s: {state}")
#             threading.Thread(target=check_state, daemon=True).start()
#
#     def pause(self):
#         with self._lock:
#             if self._player and self._player.is_playing():
#                 self._player.pause()
#                 self._paused = True
#
#     def resume(self):
#         with self._lock:
#             if self._player and self._paused:
#                 self._player.pause()  # toggle pause
#                 self._paused = False
#
#     def stop(self):
#         with self._lock:
#             if self._player:
#                 try:
#                     self._player.stop()
#                 except Exception:
#                     pass
#
#     def now_playing(self) -> Optional[Track]:
#         return self._current
#
#     def _on_end(self, event):
#         # Delete file after play
#         print("Playback ended normally. __ on_end  196")
#         track = self._current
#         if track and track.filepath and os.path.exists(track.filepath):
#             try:
#                 os.remove(track.filepath)
#             except Exception:
#                 pass
#         self._current = None
#         if self._on_track_end:
#             self._on_track_end(track)
#
#     def _on_error(self, event):
#         print("! Playback error__on_error 208")
#         track = self._current
#         self._current = None
#         if self._on_track_end:
#             self._on_track_end(track)

class Player:
    """
    VLC-based player that plays one track at a time and deletes the file upon completion.
    """
    def __init__(self):
        self._instance = instance
        self._player = self._instance.media_player_new()
        self._event_manager = self._player.event_manager()

        self._event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end)
        self._event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_error)
        self._event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_playing)
        self._event_manager.event_attach(vlc.EventType.MediaPlayerStopped, self._on_stopped)

        self._current: Optional[Track] = None
        self._on_track_end = None  # callback(track)
        self._lock = threading.Lock()
        self._paused = False
        self._media = None  # <--- keep a strong reference to the Media

        # make sure we’re not muted and volume is sane
        try:
            self._player.audio_set_mute(False)
            self._player.audio_set_volume(100)
        except Exception:
            pass

    def set_on_track_end(self, cb):
        self._on_track_end = cb

    def play(self, item):
        self.stop()
        if isinstance(item, Track):
            # Download before playing
            fp, err = self.client.download(item)
            if err:
                print(f"❌ {err}")
                return
            file = fp
        else:
            file = item

        abs_path = os.path.abspath(file)
        media = vlc.Media(f"file:///{abs_path}")
        self._player.set_media(media)
        self._player.play()
        self._playing = abs_path
        print(f"▶ Now playing: {self._playing}")

    def pause(self):
        with self._lock:
            try:
                self._player.pause()
                self._paused = not self._paused
            except Exception:
                pass

    def resume(self):
        with self._lock:
            try:
                if self._paused:
                    self._player.pause()  # toggle
                    self._paused = False
            except Exception:
                pass

    def stop(self):
        with self._lock:
            if self._player:
                try:
                    self._player.stop()
                except Exception:
                    pass
            # Keep the media around until end/stop is processed;
            # don’t drop it here immediately.

    def now_playing(self) -> Optional[Track]:
        return self._current

    # ---- VLC event handlers ----

    def _on_playing(self, event):
        print("♪ MediaPlayerPlaying event")

    def _on_stopped(self, event):
        print("■ MediaPlayerStopped event")

    def _on_end(self, event):
        print("Playback ended normally (on_end)")
        track = self._current
        # Safe cleanup of file
        if track and track.filepath and os.path.exists(track.filepath):
            try:
                os.remove(track.filepath)
            except Exception:
                pass
        self._current = None
        self._media = None   # allow GC after end
        if self._on_track_end:
            self._on_track_end(track)

    def _on_error(self, event):
        print("! Playback error (on_error)")
        track = self._current
        self._current = None
        self._media = None
        if self._on_track_end:
            self._on_track_end(track)


# ------------ Controller (Queue + Worker) ------------
player1 = instance.media_player_new()
class MusicController:
    def __init__(self):
        self.yt = YouTubeClient()
        self.player = Player()
        self.player.set_on_track_end(self._on_track_end)
        self.queue: Deque[Track] = deque()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._wake = threading.Event()
        self._running = True
        self._worker_thread.start()

    def add_query(self, query: str):
        results = self.yt.search(query)
        if not results:
            print("No results.")
            return
        print("Search results:")
        for i, tr in enumerate(results, 1):
            print(f"  {i}. {tr}")
        choice = input("Choose a track number (default 1): ").strip()
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(results)):
                idx = 0
        except:
            idx = 0
        tr = results[idx]
        self.queue.append(tr)
        print(f"Enqueued: {tr}")
        self._wake.set()

    def add_mix(self, url: str):
        print("369 error")
        tracks = self.yt.get_mix_or_playlist(url)
        print("371 error")
        if not tracks:
            print("No tracks found for that URL.")
            return
        for t in tracks:
            print("376 error")
            self.queue.append(t)
        print(f"Enqueued {len(tracks)} tracks from mix/playlist.")
        self._wake.set()

    def skip(self):
        # Stop current; worker will pick the next
        self.player.stop()

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.resume()

    def show_queue(self):
        if not self.queue:
            print("(queue is empty)")
            return
        print("Queue:")
        for i, t in enumerate(self.queue, 1):
            print(f"  {i}. {t}")

    def now(self):
        cur = self.player.now_playing()
        print(f"Now playing: {cur}" if cur else "Nothing is playing.")

    def shutdown(self):
        self._running = False
        self.player.stop()
        self._wake.set()

    # ----- internals -----

    def _worker_loop(self):
        while self._running:
            # If nothing is playing, and queue has tracks, download and play next
            if self.player.now_playing() is None:
                if self.queue:
                    tr = self.queue.popleft()
                    # download
                    fp, err = self.yt.download(tr)
                    if err:
                        print(f"! {tr.title}: {err}")
                        continue
                    tr.filepath = fp
                    print(f"▶ Playing: {tr}")
                    self.player.play(tr)

                else:
                    # wait until new items
                    self._wake.clear()
                    self._wake.wait(timeout=0.5)
            else:
                time.sleep(0.2)

    def _on_track_end(self, finished_track: Optional[Track]):
        if finished_track:
            print(f"✓ Finished: {finished_track} (deleted from cache)")

# ------------ CLI loop ------------

HELP = """
Commands:
  play <query>       Search YouTube and enqueue the top match
  mix <url>          Enqueue all tracks from a YouTube Mix/playlist URL
  queue              Show queue
  now                Show currently playing track
  pause              Pause playback
  resume             Resume playback
  skip               Skip current track
  help               Show this help
  quit               Exit

Examples:
  play blinding lights
  mix https://www.youtube.com/watch?v=ID&list=RDID
""".strip()

def main():
    print("YouTube Music (yt-dlp + VLC) — simple CLI")
    print("Cache directory:", CACHE_DIR)
    print("Type 'help' for commands.")
    controller = MusicController()

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue

            if line.lower() in ("quit", "exit", "q"):
                break
            elif line.lower() in ("help", "?"):
                print(HELP)
            elif line.lower() == "queue":
                controller.show_queue()
            elif line.lower() == "now":
                controller.now()
            elif line.lower() == "pause":
                controller.pause()
            elif line.lower() == "resume":
                controller.resume()
            elif line.lower() == "skip":
                controller.skip()
            elif line.startswith("play "):
                query = line[5:].strip()
                if query:
                    controller.add_query(query)
                else:
                    print("Usage: play <query>")
            elif line.startswith("mix "):
                url = line[4:].strip()
                if url:
                    controller.add_mix(url)
                else:
                    print("Usage: mix <youtube mix/playlist url>")
            else:
                print("Unknown command. Type 'help' for usage.")
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
        print("\nGoodbye!")

if __name__ == "__main__":
    main()
