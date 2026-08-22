# Fingerprint Manager (R307S + Raspberry Pi)

A command-line tool for enrolling, identifying, and deleting fingerprints on an
R307S optical fingerprint sensor connected to a Raspberry Pi over UART, using
the `adafruit_fingerprint` library. Enrolled fingerprint templates live on the
sensor's own flash memory; this script keeps a local JSON file mapping each
sensor slot ID to a human-readable name.

## What this actually does

- Connects to the sensor over serial (`/dev/serial0` at 57600 baud) and
  re-establishes the connection automatically if it drops.
- **Enroll**: takes two scans of the same finger, builds a template on the
  sensor, stores it in the next free slot (1–127), and records
  `{slot: name}` in `fingerprint_database.json`.
- **Authenticate**: scans a finger, asks the sensor to search its own
  on-board database, and looks up the matched slot's name locally. If
  nothing matches, it offers to enroll the finger on the spot, reusing the
  scan that was just taken instead of asking for a fresh one.
- **Delete**: removes a template from the sensor's flash and its entry from
  the local JSON file.

That's the whole feature set. There's no networking, no encryption, no
authentication in front of the menu itself, and no logging beyond `print()`
statements.

## Hardware requirements

- Raspberry Pi (any model with a GPIO header / UART)
- R307S (or compatible) optical fingerprint sensor, 6-pin JST-SM connector
- Python 3

## Wiring

The script only uses 4 of the sensor's 6 wires: power, ground, and the two
serial data lines. Wire colors vary by supplier — confirm against your
module's datasheet/sticker rather than assuming.

| R307S wire | Function | Connects to (Pi GPIO header) |
|---|---|---|
| Red | VCC (power) | Pin 2 or 4 (5V) — check your module's rated voltage |
| Black | GND | Pin 6 (GND) |
| Yellow | TX (sensor → host) | Pin 10 / GPIO15 (RXD) |
| Green | RX (host → sensor) | Pin 8 / GPIO14 (TXD) |

Note the cross-over: sensor **TX** → Pi **RX**, sensor **RX** → Pi **TX**, not
straight across.

### Before it'll work

1. **Enable the UART, disable the login shell on it** — `sudo raspi-config`
   → Interface Options → Serial Port → "login shell over serial" = **No**,
   "serial hardware enabled" = **Yes**. Skipping this leaves `/dev/serial0`
   occupied by a getty, and `serial.Serial(...)` will fail or read garbage.
2. **On Pi models with onboard Bluetooth** (3, 4, Zero W, etc.),
   `/dev/serial0` defaults to the mini-UART, which Bluetooth also uses and
   whose clock isn't stable enough for reliable 57600 baud. Add
   `dtoverlay=disable-bt` to `/boot/config.txt` (or
   `/boot/firmware/config.txt` on newer OS builds) and reboot to free the
   full PL011 UART for the sensor.
3. **Reboot after config changes**, then confirm the device exists:
   `ls -l /dev/serial0`.

## Software setup

```bash
pip3 install pyserial adafruit-circuitpython-fingerprint
```

That's the full dependency list this script needs — it only ever imports
`serial` and `adafruit_fingerprint`. `adafruit-blinka` and `rpi.gpio` are
not required (this script does no direct GPIO access), and `pyfingerprint`
is a separate, incompatible library with a different API — don't mix its
example code into this script.

## Running it

```bash
python3 fingerprint.py
```

You get a menu:

```
1) Register/Enroll New User Profile
2) Authenticate Scan (Identify Finger)
3) Delete/Revoke User Profile
4) Terminate Core Program
```

Enrollment asks for a name, then two finger placements of the same finger.
Authentication scans once; on no match it will ask `y/n` whether to enroll
that finger immediately, reusing the scan already taken.

## Data storage

`fingerprint_database.json` is created in the working directory the script
is run from. It is a flat, unencrypted `{slot_id: name}` map:

```json
{
    "1": "P",
    "2": "Q"
}
```

The actual fingerprint templates never leave the sensor — this file is only
a label lookup. Deleting the JSON file does not delete templates from the
sensor's flash, and deleting a slot on the sensor without going through
`delete_user()` will leave a stale entry in this file.

## Known limitations (not yet handled)

These are gaps, not bugs — the script works as described above, but the
following are absent and worth knowing about before relying on it for
anything beyond a hobby project:

- **No match-confidence threshold.** Any `OK` result from `finger_search()`
  is accepted regardless of the confidence score printed alongside it.
- **No duplicate-finger check on enroll.** The same finger can be registered
  under multiple names/slots.
- **No access control on the menu itself.** Anyone with terminal access can
  enroll or delete profiles — there's no PIN, admin fingerprint, or lock on
  options 1 and 3.
- **No lockout after repeated failed scans.**
- **Non-atomic JSON writes.** `save_local_database()` writes directly to
  `fingerprint_database.json`; a power loss mid-write can corrupt it.
- **Unbounded capture loops.** If no finger is placed, the capture loops in
  enrollment and authentication wait indefinitely rather than timing out.
- **No structured logging or audit trail** — only `print()` to stdout, not
  persisted anywhere.
- **Not a service.** Running via `python3 fingerprint.py` directly means a
  crash or terminal disconnect stops the program; nothing restarts it.

## File layout

```
fingerprint.py                  # the script itself
fingerprint_database.json       # generated at runtime, in the cwd
```
