# Setting up the Jetson from a Steam Deck, with no monitor

For when the Steam Deck is your only PC. No DisplayPort cable, no
keyboard, no monitor — everything over one USB-C cable and then SSH.

**Nothing here has been tested by Claude.** It's assembled from NVIDIA's
docs and the JetsonHacks scripts, both linked at the bottom. Treat it as
a well-researched plan, not a guarantee, and read the error messages.

---

## The one thing to know before you start

There are two ways to get an OS onto this board:

**The SD card route** (this guide) — flash a microSD from the Steam
Deck, boot, then move the root filesystem onto the NVMe. No Ubuntu PC
needed anywhere. This is the route that fits your setup.

**The SDK Manager route** — needs a real Ubuntu x86 machine and ~40GB
free. Flashes the NVMe directly and writes the QSPI bootloader.

The catch: **"Super" mode lives in the QSPI bootloader, and the SD card
method cannot write it.** NVIDIA's own docs say so. That matters because
Super mode is where the 67 TOPS and the extra memory bandwidth come from.

You are buying a kit sold *as* a Super Developer Kit, so it should
arrive with Super firmware already flashed and this is a non-issue —
the warning is aimed at people upgrading older Orin Nano kits. **Verify
it on arrival** (Step 6). If it turns out not to be there, you'll need
the SDK Manager route to get it, and that's worth doing before building
anything else on top.

---

## The DisplayPort cable you forgot

You don't need it. That's what this whole guide is for — first boot
happens over USB-C serial, then SSH forever after. Skip the adapter and
don't spend the money.

The cable that *does* matter is a **USB-C data cable**, and you very
likely already own one:

| cable | data? |
|---|---|
| Z Flip 6's charging cable | **Yes** — Samsung ships data-capable C-to-C (it's what Smart Switch uses) |
| Steam Deck's power brick | Usually **no** — the bundled PSU cable is commonly charge-only |
| Anything that has ever moved files between two devices | Yes, by definition |

**Free test, do it before buying anything:** plug the phone into the
Deck with the cable. If the Deck sees the phone's storage, it's a data
cable and you're done. If it only charges, try another.

If nothing you own works, a USB-C data cable is a few dollars — still
much cheaper than the DisplayPort adapter, and it's the only thing on
this list you might have to buy.

## What you need

- Steam Deck in Desktop Mode
- A **USB-C cable** (data, not charge-only — a charge-only cable will
  power the board and show you nothing)
- A microSD card, 64GB minimum. You have a 128GB and a 256GB.
- The NVMe, installed in **slot J11** before first boot
- The Jetson's own 19V power supply (in the box)

No monitor. No keyboard. No DisplayPort anything.

---

## Step 1 — Flash the microSD, on the Deck

Download the **JetPack 6.x SD card image for Jetson Orin Nano** from
NVIDIA's JetPack page. It's a few GB.

Easiest way to write it, in Desktop Mode:

1. Open **Discover** (the app store)
2. Install **balenaEtcher** (it's a Flatpak, installs to your home, no
   SteamOS filesystem weirdness)
3. Etcher → select the image → select the SD card → Flash

Etcher verifies afterwards, and more importantly it refuses to write to
your system drive. Use it rather than `dd`. A mistyped `dd` target
overwrites the Steam Deck itself, and there is no undo.

Put the flashed card in the slot on the **underside of the module**
(not the carrier board — it's tucked under the heatsink side).

## Step 2 — Get a terminal over USB-C

Plug the USB-C cable from the Deck to the Jetson. Then power the Jetson
on.

The Jetson appears to the Deck as a USB serial device. To talk to it you
need a serial terminal, and SteamOS won't let you `pacman -S screen` on
the read-only filesystem. Use Python's instead — it installs into your
home directory and survives SteamOS updates:

```bash
pip install --user pyserial
python3 -m serial.tools.miniterm /dev/ttyACM0 115200
```

If `/dev/ttyACM0` doesn't exist, check what did appear:

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

If nothing appears at all, it's almost always the cable. Swap it.

To exit miniterm later: **Ctrl-]**

## Step 3 — First-boot setup, over the serial console

You should see Ubuntu's first-boot wizard in the terminal. It's the
same setup you'd get on a monitor, just as text. Work through it:

- Accept the licence
- Language, keyboard, timezone
- **Create your username and password** — write these down
- **Join your wifi here.** This is the step that matters most; get it
  on the network now and everything afterwards is just SSH.

The board reboots at the end. Reconnect with the same miniterm command
and log in with the user you just made.

## Step 4 — Find it on the network and SSH in

At the serial prompt:

```bash
ip addr show wlan0 | grep 'inet '
```

Note the address (something like 192.168.1.x). Then from a normal
Deck terminal:

```bash
ssh yourname@192.168.1.x
```

That's the last time you need the serial cable. Everything from here is
a normal SSH session.

There's also a USB-only fallback: the Jetson exposes itself at
**192.168.55.1** over the USB-C link, so `ssh yourname@192.168.55.1`
works even with no wifi at all. Handy if the network setup goes wrong.

## Step 5 — Move the root filesystem onto the NVMe

Right now you're running off the SD card and the NVMe is idle. This
moves the root filesystem across. It's the step that buys you the swap
headroom the whole purchase was for.

Over SSH:

```bash
git clone https://github.com/jetsonhacks/rootOnNVMe.git
cd rootOnNVMe
./copy-rootfs-ssd.sh      # copies the running system to the SSD
./setup-service.sh        # tells it to use the SSD from now on
sudo reboot
```

After the reboot, confirm it took:

```bash
df -h /
```

The root filesystem should be on `/dev/nvme0n1p1`, not `/dev/mmcblk*`.

**The SD card stays in.** This setup boots from SD and then roots on
NVMe — the bootloader still lives on the card, so don't remove it. All
the actual reading, writing and swapping happens on the SSD, which is
the part that matters. (True NVMe-only boot needs the SDK Manager
route.)

## Step 6 — Check you got Super mode, and unlock it

```bash
sudo nvpmodel -q          # what mode is it in?
sudo nvpmodel -m 0        # maximum power mode
sudo jetson_clocks        # pin clocks high
```

`nvpmodel -q` should list a MAXN / Super power mode. If the only modes
are the older 7W/15W ones, the QSPI doesn't have the Super firmware and
you'd need the SDK Manager route to add it. Worth knowing now rather
than after you've built everything on top.

Then install the monitor so you can watch RAM and temps while the model
runs:

```bash
sudo pip3 install jetson-stats
jtop
```

## Step 7 — Add swap, on the SSD

The reason for the NVMe. 8GB shared between CPU and GPU gets tight once
Whisper, the 3B and Piper are all resident:

```bash
sudo fallocate -l 16G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Because root is now on the NVMe, that swapfile is on the SSD, which is
the whole point. Doing this on a microSD would be slow and would wear
the card out.

## Step 8 — Go headless properly

You're already SSH-only, so drop the desktop and get the RAM back:

```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

That's typically 1–1.5GB back — a meaningful fraction of 8GB.

Now continue with **JETSON_SETUP.md** from "Install Ollama".

---

## The laptop changes the plan — install Ubuntu on it, not Windows

An Acer Aspire V15 Nitro Black Edition (i7, GTX 960M, DDR4, a fresh 1TB
drive) is a bigger deal for this project than any cable, for one
specific reason:

**NVIDIA's SDK Manager only runs on Ubuntu x86_64.** It is the escape
hatch named in three of the five rows of the troubleshooting table
below — pre-JetPack-6 factory firmware, missing Super QSPI firmware,
true NVMe-only boot. Right now there is no machine in the house that
can run it. SteamOS is Arch-based with a read-only filesystem and is
the wrong tool; that laptop with Ubuntu on it is exactly the right one.

Three other things it buys, all free:

- **Ollama on the 960M.** Compute capability 5.0, which Ollama supports.
  Check whether the card is the 2GB or 4GB variant — a 3B at Q4_K_M is
  roughly 2GB, so it fits comfortably in 4GB and is tight in 2GB.
- **The real eval harness.** `python yuzu_prompt_eval.py --persona yuzu2`
  scores 12 prompts × 3 runs against the same parser the robot uses.
  That is a far better instrument than hand-testing in PocketPal and
  screenshotting, and it's the thing that turns "feels good" into a
  number.
- **A second serial-console host.** The Acer has Thunderbolt 3, so it
  can drive the Jetson's first boot just as well as the Deck can.

**Step-by-step for that install is in
[UBUNTU_LAPTOP.md](UBUNTU_LAPTOP.md)** — written to be read off a phone
while standing at the laptop.

Practical notes:

- **Use Ubuntu 22.04 LTS.** SDK Manager supports 18.04/20.04/22.04.
  Do not reach for 24.04 — it is not on that list.
- Make the installer with balenaEtcher on the Deck, same tool and same
  steps as flashing the microSD above.
- Installing Windows *from* Linux is genuinely awkward (the install.wim
  is over FAT32's 4GB file limit). Ubuntu is a straight ISO write. If
  you want Windows as well, the 1TB drive has room to dual-boot it
  later, from inside Ubuntu, with much less hassle.
- Optimus laptops of this era occasionally need the proprietary NVIDIA
  driver selected by hand after install. Well-trodden ground for this
  exact model, just don't be surprised by it.

## If it goes wrong

| Symptom | Likely cause |
|---|---|
| No `/dev/ttyACM*` on the Deck | Charge-only USB-C cable. Swap it. |
| Board powers on, serial shows nothing | SD card not flashed correctly, or seated in the carrier-board slot instead of the one under the module |
| SD flashed but won't boot | Factory firmware may predate JetPack 6. This is the case that needs the SDK Manager route. |
| `nvpmodel -q` shows no Super mode | QSPI lacks Super firmware — SDK Manager route |
| Can't find it on wifi | `ssh yourname@192.168.55.1` over the USB-C link instead |

## Sources

- [Orin Nano Developer Kit quick start](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/quick_start.html)
- [JetPack 6.x firmware update path](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/update_firmware.html)
- [JetPack SDK downloads](https://developer.nvidia.com/embedded/jetpack-sdk-62)
- [jetsonhacks/rootOnNVMe](https://github.com/jetsonhacks/rootOnNVMe)
- [jetsonhacks/bootFromExternalStorage](https://github.com/jetsonhacks/bootFromExternalStorage) (the SDK Manager route)
