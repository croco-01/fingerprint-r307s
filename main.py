import time
import serial
import json
import os
import adafruit_fingerprint

# Configuration Constants
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 57600
DB_FILE = "fingerprint_database.json"

class AdvancedFingerprintManager:
    def __init__(self):
        self.uart = None
        self.finger = None
        self.user_db = {}
        self.load_local_database()
        self.connect_sensor()

    def connect_sensor(self):
        """Establishes or heals the serial connection to the R307S"""
        try:
            if self.uart:
                self.uart.close()
            
            self.uart = serial.Serial(SERIAL_PORT, baudrate=BAUD_RATE, timeout=1)
            self.uart.reset_input_buffer()
            self.uart.reset_output_buffer()
            
            self.finger = adafruit_fingerprint.Adafruit_Fingerprint(self.uart)
            
            # Perform a test read to verify the sensor is responsive
            if self.finger.read_templates() == adafruit_fingerprint.OK:
                return True
        except Exception as e:
            print(f"\n[⚠️ SERIAL ERROR] Connection failure: {e}")
        return False

    def ensure_connection(self):
        """Heartbeat check to verify the link hasn't died mid-runtime"""
        try:
            if self.finger and self.finger.read_templates() == adafruit_fingerprint.OK:
                return True
        except Exception:
            pass
        print("\n[🔄 RECONNECTING] Connection lost. Attempting hardware re-sync...")
        return self.connect_sensor()

    def load_local_database(self):
        """Loads the Slot ID -> Name mapping from local JSON storage"""
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r") as f:
                    self.user_db = json.load(f)
            except Exception:
                self.user_db = {}
        else:
            self.user_db = {}

    def save_local_database(self):
        """Saves the Slot ID -> Name mapping to local JSON storage"""
        try:
            with open(DB_FILE, "w") as f:
                json.dump(self.user_db, f, indent=4)
        except Exception as e:
            print(f"[Error] Failed to write database backup: {e}")

    def get_next_free_slot(self):
        """Finds the lowest unassigned storage slot number"""
        for slot in range(1, 128):
            if str(slot) not in self.user_db:
                return slot
        return None

    def _capture_and_extract(self, phase):
        """Runs the capture loop + feature extraction for one enrollment phase.
        Returns True on success, False on any failure (caller should abort)."""
        prompt = "Place finger on sensor..." if phase == 1 else "Place same finger again..."
        print(prompt, end="", flush=True)

        # High-reliability image capture loop
        while True:
            if not self.ensure_connection():
                print("\n[Error] Connection broke during capture.")
                return False
            try:
                stat = self.finger.get_image()
                if stat == adafruit_fingerprint.OK:
                    print(" Image taken.")
                    break
                if stat == adafruit_fingerprint.NOFINGER:
                    time.sleep(0.1)
                    continue
                print("\n[!] Sensor read error. Keep finger steady...")
            except RuntimeError:
                self.uart.reset_input_buffer()
                time.sleep(0.2)

        print("Processing feature extraction...", end="", flush=True)
        try:
            if self.finger.image_2_tz(phase) != adafruit_fingerprint.OK:
                print(" Error defining features.")
                return False
            print(" Done.")
        except RuntimeError:
            print(" Serial packet timeout.")
            return False

        if phase == 1:
            print("Remove finger from glass.")
            time.sleep(1.5)
            while True:
                try:
                    if self.finger.get_image() == adafruit_fingerprint.NOFINGER:
                        break
                except Exception:
                    pass
                time.sleep(0.1)

        return True

    def _finalize_and_store(self, name, slot):
        """Creates the model from the two buffered scans and writes it to flash + local db."""
        print("Compiling fingerprint map template...", end="", flush=True)
        try:
            if self.finger.create_model() != adafruit_fingerprint.OK:
                print(" Error creating distinct model.")
                return
            print(" Created.")

            print(f"Writing template to internal hardware flash...", end="", flush=True)
            if self.finger.store_model(slot) == adafruit_fingerprint.OK:
                print(" Stored!")
                # Update our local name-mapping database
                self.user_db[str(slot)] = name
                self.save_local_database()
                print(f"🎉 Success! '{name}' is securely registered under ID #{slot}.")
            else:
                print(" Hardware refused to store model data.")
        except RuntimeError:
            print(" Communication failure during final compilation.")

    def enroll_user(self, start_phase=1):
        """Enrolls a fingerprint with custom names and background retries.

        start_phase=1 (default): does both scans, as when called from the menu.
        start_phase=2: skips the first scan/capture because the caller (e.g. a
        failed authentication) already has a valid first scan sitting in the
        sensor's buffer 1 from its own image_2_tz(1) call.
        """
        if not self.ensure_connection():
            print("[Error] Cannot enroll. Sensor is offline.")
            return

        name = input("\nEnter name/label for this fingerprint: ").strip()
        if not name:
            print("Name cannot be empty!")
            return

        slot = self.get_next_free_slot()
        if slot is None:
            print("[Error] Sensor database is full (Max 127 fingerprints)!")
            return

        print(f"\nTargeting storage slot #{slot} for '{name}'...")
        time.sleep(0.5)

        for phase in range(start_phase, 3):
            if not self._capture_and_extract(phase):
                return

        self._finalize_and_store(name, slot)

    def search_user(self):
        """Scans a finger and cross-references its ID against the local name database"""
        if not self.ensure_connection():
            print("[Error] Sensor offline.")
            return

        print("\nReady to scan. Place finger down...", end="", flush=True)
        while True:
            if not self.ensure_connection():
                return
            try:
                stat = self.finger.get_image()
                if stat == adafruit_fingerprint.OK:
                    print(" Image captured.")
                    break
                if stat == adafruit_fingerprint.NOFINGER:
                    time.sleep(0.1)
                    continue
            except RuntimeError:
                self.uart.reset_input_buffer()
                time.sleep(0.2)

        try:
            if self.finger.image_2_tz(1) != adafruit_fingerprint.OK:
                print("[Error] Could not process scan features.")
                return

            print("Searching hardware database...", end="", flush=True)
            if self.finger.finger_search() == adafruit_fingerprint.OK:
                matched_id = str(self.finger.finger_id)
                confidence = self.finger.confidence
                name = self.user_db.get(matched_id, "Unknown User (No Local Mapping)")
                
                print(f" Match Found!")
                print(f"User: {name}")
                print(f"Slot: #{matched_id}")
                print(f"Match Confidence: {confidence}")
                return matched_id
            else:
                print(" No match found.")
                choice = input("This fingerprint isn't registered. Enroll it now? (y/n): ").strip().lower()
                if choice == "y":
                    # The scan we just took is already processed into buffer 1
                    # (image_2_tz(1) above), so enrollment only needs the second
                    # confirmation scan — no need to re-scan from the start.
                    self.enroll_user(start_phase=2)
                return None
        except RuntimeError:
            print(" Core communications timed out during query.")

    def delete_user(self):
        """Removes a user from both hardware flash and local JSON metadata"""
        if not self.user_db:
            print("\nDatabase is currently completely empty.")
            return

        print("\n--- Current Registered Profiles ---")
        for slot, name in self.user_db.items():
            print(f"Slot #{slot}: {name}")

        target = input("\nEnter the Slot ID number to completely delete: ").strip()
        if target not in self.user_db:
            print("Invalid slot number or slot already vacant.")
            return

        if not self.ensure_connection():
            print("[Error] Sensor offline.")
            return

        print(f"Purging profile from hardware memory...", end="", flush=True)
        try:
            if self.finger.delete_model(int(target)) == adafruit_fingerprint.OK:
                print(" Cleared from flash.")
                del self.user_db[target]
                self.save_local_database()
                print("Profile mapping wiped successfully.")
            else:
                print(" Hardware execution failed.")
        except RuntimeError:
            print(" Communication failure during profile delete command.")

if __name__ == "__main__":
    manager = AdvancedFingerprintManager()
    
    while True:
        print("\n" +"   SECURITY CONTROL INTERFACE")
        print("1) Register/Enroll New User Profile")
        print("2) Authenticate Scan (Identify Finger)")
        print("3) Delete/Revoke User Profile")
        print("4) Terminate Core Program")
        
        choice = input("\nEnter system selection (1-4): ").strip()
        
        if choice == "1":
            manager.enroll_user()
        elif choice == "2":
            manager.search_user()
        elif choice == "3":
            manager.delete_user()
        elif choice == "4":
            print("\nClosing secure background processes. Goodbye!")
            break
        else:
            print("Invalid input selection. Try again.")
