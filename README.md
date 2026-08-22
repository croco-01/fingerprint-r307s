# Fingerprint Manager (R307S + Raspberry Pi)

A command-line tool for enrolling, identifying, and deleting fingerprints on
an R307S optical fingerprint sensor connected to a Raspberry Pi over UART,
using the `adafruit_fingerprint` library. Fingerprint templates live on the
sensor's own flash memory; this script keeps a local JSON file that maps
each sensor slot number to a human-readable name.

## What it does

- Connects to the sensor over serial (`/dev/serial0` at 57600 baud) and
  reconnects automatically if the link drops.
- **Enroll** — takes two scans of the same finger, builds a template on the
  sensor, stores it in the next free slot (1–127), and saves
  `{slot: name}` to `fingerprint_database.json`.
- **Authenticate** — scans a finger, asks the sensor to search its own
  on-board database, and looks up the matched slot's name locally. If
  nothing matches, it offers to enroll that finger immediately, reusing the
  scan just taken instead of asking for a fresh one.
- **Delete** — removes a template from the sensor's flash and its matching
  entry from the local JSON file.

That's the full feature set. No networking, no encryption, no login/PIN in
front of the menu, and no logging beyond what's printed to the terminal.

## Hardware needed

- Raspberry Pi (any model with a GPIO header / UART)
- R307S (or compatible) optical fingerprint sensor, 6-pin JST-SM connector
- Python 3

## Wiring

The script only needs 4 of the sensor's 6 wires — power, ground, and the
two serial data lines. **Wire colors vary by supplier** — check your own
module's datasheet/sticker rather than trusting this table blindly.

| R307S wire | Function | Pi GPIO header pin |
|---|---|---|
| Red | VCC (power) | Pin 2 or 4 (5V) — confirm your module's rated voltage first |
| Black | GND | Pin 6 (GND) |
| Yellow | TX (sensor → host) | Pin 10 / GPIO15 (RXD) |
| Green | RX (host → sensor) | Pin 8 / GPIO14 (TXD) |

**This crosses over**: sensor TX → Pi RX, and sensor RX → Pi TX. Not
straight across — straight across won't work.

**Not used by this script:**
- **Blue** — on most R307S boards this is an unused or internal 3.3V
  reference pin. The script powers the sensor through the red wire; nothing
  reads or drives green.
- **White** — a touch/wake interrupt line, meant for waking a sleeping
  microcontroller when a finger is placed. This script instead polls the
  sensor over UART in a loop (`get_image()`), so it has no use for an
  interrupt pin.

Leave both disconnected.

## OS setup (what actually needs to be configured, and why)

The sensor needs a clean, dedicated UART — by default the Pi's serial port
is either occupied by a login shell, or (on boards with onboard Bluetooth)
shared with Bluetooth on an unstable clock. Both have to be dealt with.

**1. Enable the UART and turn off the serial login shell.**

Either via `sudo raspi-config` → Interface Options → Serial Port →
"login shell over serial" = **No**, "serial hardware enabled" = **Yes** —
or by editing `/boot/firmware/config.txt` directly and confirming
`cmdline.txt` has no `console=serial0,...` entry. Verified working values:

`/boot/firmware/config.txt`, in the `[all]` section:
```
enable_uart=1
dtoverlay=disable-bt
```

`/boot/firmware/cmdline.txt` — should **not** contain a `console=serial0...`
or `console=ttyAMA0...` entry. Just `console=tty1` (plus your normal root/
boot parameters) is correct.

**2. Free the full UART from Bluetooth.**

`dtoverlay=disable-bt` above does the actual work — without it,
`/dev/serial0` maps to the mini-UART, which Bluetooth also uses and whose
clock isn't stable enough for reliable 57600 baud, causing intermittent
read errors. As a belt-and-suspenders step (not strictly required once the
overlay is set, but prevents Bluetooth from ever re-claiming the interface
after an OS update), also disable the service:

```bash
sudo systemctl disable bluetooth.service
sudo systemctl mask bluetooth.service
```

**3. Reboot, then verify.**

```bash
sudo reboot
ls -l /dev/serial0
```

You want to see:
```
serial0 -> ttyAMA0
```

If it instead points to `ttyS0`, `disable-bt` didn't take effect — check
`config.txt` and reboot again.

> **Note on Raspberry Pi 5:** the UART is routed through the RP1 I/O chip
> rather than directly off the SoC, so `/dev/serial0` behaves slightly
> differently under the hood than on Pi 3/4/Zero. The same two settings
> (`enable_uart=1` + `dtoverlay=disable-bt`) are still correct and
> sufficient — RP1 doesn't change what you need to set, just how it's
> implemented internally.

## Software setup

```bash
pip3 install pyserial adafruit-circuitpython-fingerprint
```

This is the full dependency list — the script only ever imports `serial`
and `adafruit_fingerprint`. `adafruit-blinka` and `rpi.gpio` are **not**
required (there's no direct GPIO access in this script), and
`pyfingerprint` is a separate, incompatible library with a different API —
don't mix its example code in here.

## Running it

```bash
python3 fingerprint.py
```

```
1) Register/Enroll New User Profile
2) Authenticate Scan (Identify Finger)
3) Delete/Revoke User Profile
4) Terminate Core Program
```

Enrollment asks for a name, then two placements of the same finger.
Authentication scans once; on no match it asks `y/n` to enroll that finger
right away, reusing the scan already taken.

## Data storage

`fingerprint_database.json` is created in the working directory the script
is run from — a flat, unencrypted `{slot_id: name}` map:

```json
{
    "1": "P",
    "2": "Q"
}
```

The fingerprint templates themselves never leave the sensor; this file is
only a label lookup. Deleting the JSON file does **not** delete templates
from the sensor's flash, and deleting a slot on the sensor by some other
means (without going through `delete_user()`) leaves a stale entry here.

## Known limitations

The script works as described above, but the following are genuinely
absent — worth knowing before relying on this for anything beyond a hobby
project:

- **No match-confidence threshold** — any `OK` from `finger_search()` is
  accepted regardless of the confidence score.
- **No duplicate-finger check on enroll** — the same finger can be
  registered under multiple names/slots.
- **No access control on the menu itself** — anyone with terminal access
  can enroll or delete profiles; no PIN, admin fingerprint, or lock on
  options 1 and 3.
- **No lockout after repeated failed scans.**
- **Non-atomic JSON writes** — `save_local_database()` writes directly to
  the file; a power loss mid-write can corrupt it.
- **Unbounded capture loops** — if no finger is placed, the capture loops
  wait indefinitely instead of timing out.
- **No structured logging or audit trail** — only `print()` to the
  terminal, nothing persisted.
- **Not a service** — running it directly means a crash or closed terminal
  stops the program; nothing restarts it automatically.

## File layout

```
fingerprint.py                  # the script itself
fingerprint_database.json       # generated at runtime, in the cwd
```
