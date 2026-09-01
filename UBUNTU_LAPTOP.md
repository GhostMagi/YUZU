# Putting Ubuntu on the Acer

Written to be read off a phone while standing at the laptop.

**Why:** NVIDIA's SDK Manager — the rescue tool if the Jetson's SD card
route fails — only runs on Ubuntu x86. This laptop becomes that. It
also runs Ollama on the GTX 960M, so the prompt eval can run for real
instead of being hand-scored from PocketPal screenshots.

**Use Ubuntu 22.04 LTS.** SDK Manager supports 18.04 / 20.04 / 22.04.
Not 24.04 — it isn't on that list.

---

## Before you start

- **Something to boot from, 8GB or bigger.** A USB stick works. So does
  **a microSD in a USB card reader** — the reader looks like a plain USB
  drive to the BIOS, so it boots the same way. See the note below.
- The Acer plugged into power the whole time. Do not let it die during
  an install.
- "No Bootable Device" on the Acer is expected. The drive is blank.
  That's the screen a blank drive makes, and it means there is nothing
  on there to lose.

### Using the Deck's microSD instead of a flash drive

Works fine, with three things worth knowing:

**It erases the card, games included.** A card that's been living in the
Steam Deck holds installed games. Writing Ubuntu to it wipes them. They
are not gone-gone — they redownload from Steam for free — but it's hours
of bandwidth, so check nothing on there is precious first.

**Don't format it first.** Natural instinct, wasted step: Etcher
overwrites the whole card regardless of what was on it. Flash straight
over the top.

**Write it in the Deck, boot it from the dongle.** The Deck has its own
microSD slot, so the card can stay in the Deck for the writing half. The
dongle is only needed to plug it into the Acer. Use the dongle rather
than the Acer's built-in SD slot — built-in card readers on laptops this
age often can't be booted from. (If it does show up in the F12 menu,
fine, use it.)

Afterwards the card will look broken — SteamOS or Windows may show a
tiny unreadable partition and offer to format it. That's just what an
installer image looks like. Ignore it until you're done with it.

**To make it a Steam card again:** Steam Deck → Settings → System →
Format SD Card. Undoes all of this in about a minute.

---

# Part 1 — On the Steam Deck

### 1. Desktop Mode
Steam button → Power → Switch to Desktop.

### 2. Download Ubuntu
Firefox → **releases.ubuntu.com/22.04/**

Get the file ending **`-desktop-amd64.iso`**. It's about 4.7GB, so give
it time. `amd64` is correct even though the laptop is Intel — it means
"64-bit PC", not the CPU brand.

### 3. Install a disk writer
Open **Discover** (the app store) and install **Impression**. It's a
Flatpak, it installs to your home directory, and it survives SteamOS
updates.

**balenaEtcher may not show up in Discover** — it didn't in Sept 2026.
Impression does the same job (pick image, pick drive, write) and is
less hassle. `ISO Image Writer` is a third option. Any of them is fine.

If you end up on balena's website instead, the one you want is **ETCHER
FOR LINUX X64 (64-BIT) (ZIP)** — not the LEGACY 32 BIT one, and not the
`.deb` (that's for Debian/Ubuntu; SteamOS is Arch-based). Unzip it,
right-click the `.AppImage` → Properties → Permissions → tick **"Is
executable"**, then double-click. That permission tick is the step
everyone misses, and without it double-clicking does nothing at all.

Use one of these rather than the `dd` command. They refuse to write to
your system drive; a mistyped `dd` would overwrite the Steam Deck itself
and there is no undo.

### 4. Write the card (or stick)
Card in the Deck's own microSD slot. Open Etcher:

1. **Flash from file** → pick the `.iso` you downloaded
2. **Select target** → pick the card. **Check the size says ~128GB.**
   This is the one step with no undo, so read it twice.
3. **Flash**

It verifies afterwards. When it says done, you're finished with the Deck.

---

# Part 2 — On the Acer

### 5. Boot from the stick
Plug the USB stick in. Power on and **tap F12 repeatedly** the moment
you press the power button.

You want a boot menu. Pick the entry with your stick's name — usually
prefixed **UEFI:**.

**If F12 does nothing** — Acer ships with the boot menu switched off:

1. Power on, tap **F2** to get into BIOS setup
2. **Main** tab → set **F12 Boot Menu** to **Enabled**
3. **F10** to save and exit
4. Try F12 again

### 5b. This particular Acer's quirks (VN7-592G)

Found the hard way, Sept 2026:

- **The F2 window is about one second.** Hold the power button for ten
  seconds first so the machine is genuinely off, then tap F2 four or
  five times a second from the instant you press power. Pressing keys
  once "No Bootable Device" is on screen does nothing at all — POST is
  over by then and that screen ignores everything.
- **The main Enter key is dead; the NUMPAD Enter works.** Keyboards are
  wired as a grid and the two Enters sit on different lines, so one
  dying doesn't touch the other. If a key seems dead, look for a
  duplicate of it elsewhere on the board before concluding anything.
- **The up arrow is dead too.** Down arrow wraps around to the top of a
  list, and F5/F6 move boot entries, so neither BIOS nor the installer
  actually needs it. In a terminal later, `Ctrl+P` is up-arrow and
  `Ctrl+N` is down-arrow for command history.
- **The built-in SD card reader is not in the boot list.** Boot priority
  offers the Samsung drive, USB FDD/HDD/CDROM and network — nothing for
  the internal reader. So the microSD has to arrive over USB: a card
  reader dongle, or write the image to a plain USB stick instead.

### 6. If it still refuses to boot the stick
Acer's Secure Boot has an odd lock: you can't turn it off until a
supervisor password exists. In BIOS (F2):

1. **Security** tab → **Set Supervisor Password** → set one.
   **Write it down.** You will be annoyed later if you don't.
2. **Boot** tab → **Secure Boot** → **Disabled**
3. **F10** to save and exit

Try the stick again.

### 7. Try it before you commit
At the purple screen choose **Try Ubuntu** first. Nothing is written to
the laptop — it runs entirely off the stick.

Check the things that are annoying to fix later:
- Does Wi-Fi see your network?
- Does the trackpad work?
- Does sound work?

Happy? There's an **Install Ubuntu** icon on the desktop. Double-click it.

### 8. The installer
Mostly Next, with two answers that matter:

| Screen | Answer |
|---|---|
| Keyboard | US (or whatever yours is) |
| Updates and other software | **Normal installation**, and **tick "Install third-party software for graphics and Wi-Fi hardware"** |
| Installation type | **Erase disk and install Ubuntu** |
| Who are you? | Username + password — **write these down** |

That third-party checkbox is the one people skip and regret. It's what
gets the NVIDIA driver and the Wi-Fi firmware.

"Erase disk" is safe here. The drive is blank — that's what the "No
Bootable Device" screen was telling you.

### 9. Reboot
When it asks, **remove the USB stick**, then press Enter.

---

# Part 3 — First ten minutes on Ubuntu

Open a terminal with **Ctrl + Alt + T**. Copy these one line at a time.

### Update everything
```
sudo apt update && sudo apt upgrade -y
```
`sudo` means "as administrator" — it'll ask for the password you just
made. The password won't show as you type it, not even dots. That's
normal, keep typing and hit Enter.

### Check the graphics card
```
nvidia-smi
```
If it prints a table mentioning the 960M, the driver is in. If it says
"command not found", open **Software & Updates** → **Additional
Drivers** → pick the recommended NVIDIA driver → Apply → reboot.

### Get the tools this project needs
```
sudo apt install -y git python3 python3-pip
curl -fsSL https://ollama.com/install.sh | sh
```

### Pull the project and prove it works
```
git clone https://github.com/GhostMagi/YUZU.git
cd YUZU
python3 test_yuzu.py
```
154 tests, about 9 seconds. If they pass, the laptop is ready.

### Run a persona for real
```
ollama pull llama3.2:3b
python3 build_yuzu_model.py --all --create
python3 yuzu_prompt_eval.py --persona yuzu2
```
That last one is the payoff — 12 prompts × 3 runs, scored against the
same parser the robot uses. A number instead of a vibe.

---

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| F12 does nothing | Boot menu disabled — Step 5 |
| Stick doesn't appear in the boot menu | Secure Boot — Step 6. Or the stick didn't write; re-run Etcher. |
| Installer can't see the hard drive | The drive may be loose. It is new — reseat it. |
| Wi-Fi missing after install | Third-party checkbox was skipped. Software & Updates → Additional Drivers |
| `nvidia-smi` not found | Same — Additional Drivers |
| Screen tears or won't wake from sleep | Optimus quirk on this era of laptop. Not urgent; nothing here needs the GPU except Ollama. |

Screenshot whatever it says and send it over. Error messages on Linux
are usually specific and honest, which makes them easy to act on.
