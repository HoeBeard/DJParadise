<p align="left">
  <img src="assets/hb_software_logo.png" alt="HB Software" height="110">
</p>

# DJ Paradise

**Build your crate from Spotify, SoundCloud and YouTube.**
Developed by [HB Software](https://hbcs.info/software/) · Huntsville, Alabama

DJ Paradise gives you six download spots in one window. Paste a link, press **Download**, and the music lands in your library as MP3, M4A, FLAC or WAV with artwork and tags. Run one spot or all six at once.

| | Playlist | Song |
|---|---|---|
| **Spotify** | Playlists and albums | Single tracks |
| **SoundCloud** | Playlists and sets | Single tracks |
| **YouTube** | Playlists | Single videos |

---

## Download and start

1. Click the green **Code** button on this page, then **Download ZIP**.
2. Unzip the folder anywhere you like (Desktop, Documents, a USB drive).
3. Start it:
   - **Windows:** double-click **Start DJ Paradise.bat**
   - **Mac:** double-click **Start DJ Paradise.command** (first time only: right-click it and choose **Open**)
   - **Linux:** run `./start-dj-paradise.sh`

That's it. There is nothing else to install.

### What happens when it starts

Every time DJ Paradise opens, it checks that everything it needs is on your computer:

- **Python** – installed automatically if your computer doesn't have it
- **Download engines** for Spotify, SoundCloud and YouTube
- **Audio converter** for MP3, M4A, FLAC and WAV
- **YouTube script runtime**

Anything missing is downloaded and installed for you. Download engines are checked for updates once a day so links keep working when sites change. The first start takes a few minutes; after that it opens in seconds.

Everything DJ Paradise installs stays inside its own folder (in a hidden `.runtime` folder), so it never interferes with other programs. To remove DJ Paradise completely, delete the folder.

---

## Using DJ Paradise

- **Save to** – choose where your music goes, right from the top bar:
  - Type or paste a folder path and press **Enter**, or click **Change…** to browse.
  - **Recent ▾** jumps back to any folder you've used before.
  - **Open** shows the folder.
  - Turn **Sort into Spotify, SoundCloud and YouTube folders** on or off.
  - By default music goes to `Music/DJ Paradise`. Playlists always get their own folder.
- **Folder per spot** – every spot shows where it saves at the bottom of its card. Click **Change** there to give that spot its own folder (marked with ★), for example send SoundCloud songs straight to your edits folder. **Settings** can send every spot back to the main folder.
- **Format** – MP3 (320 kbps), M4A, FLAC or WAV.
- **Download all** – starts every spot that has a link in it.
- **Stop** – cancels a running download.
- **Settings** – reset spot folders and add your own Spotify app keys (see below).

### Spotify request limits

If Spotify downloads stop with a request-limit message, create a free app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), then paste its **Client ID** and **Client secret** into **Settings**.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Startup stops with an error | Check your internet connection and press **Try again**. **View log** shows details. |
| A download fails that used to work | Delete `.runtime/state.json` and reopen DJ Paradise. That forces an engine update right away. |
| Windows says it protected your PC | Click **More info**, then **Run anyway**. |
| Mac says the file can't be opened | Right-click **Start DJ Paradise.command** and choose **Open**. |
| Something is badly broken | Delete the `.runtime` folder and start again. Your settings reset, your music is untouched. |

---

## Responsible use

Only download music you own or have permission to use. Respect artists, labels and each platform's terms of service.

---

© 2026 HB Software · [hbcs.info](https://hbcs.info) · HBServicesCombined@gmail.com · 256-658-0547
