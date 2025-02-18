#!/bin/python

import sys
import argparse
from serial import Serial

class RT4D(Serial):
    ACK_RESPONSE = b'\06'
    FLASH_MODE_RESPONSE = 0xFF
    CMD_ERASE_FLASH = 0x39
    CMD_READ_FLASH = 0x52
    CMD_WRITE_FLASH = 0x57
    WRITE_BLOCK_SIZE = 0x400
    MEMORY_SIZE = 0x3d800

    def append_checksum(self, data):
        data.append((sum(data) + 72) % 256)
        return bytearray(data)

    def check_bootloader_mode(self):
        self.reset_input_buffer()
        payload = self.append_checksum([self.CMD_READ_FLASH, 0, 0])
        self.write(payload)
        return self.read(4)[0] == self.FLASH_MODE_RESPONSE

    def cmd_erase_flash(self):
        for part in [0x10, 0x55]:
            payload = self.append_checksum([self.CMD_ERASE_FLASH, 0x33, 0x05, part])
            if not (self.write(payload) and self.read(1) == self.ACK_RESPONSE):
                return False
        return True

    def cmd_write_flash(self, offset, data):
        payload = self.append_checksum([self.CMD_WRITE_FLASH, (offset >> 8) & 0xFF, offset & 0xFF] + list(data))
        return self.write(payload) and self.read(1) == self.ACK_RESPONSE

    def flash_firmware(self, fw_bytes):
        fw_bytes += bytearray([0x0] * (self.MEMORY_SIZE - len(fw_bytes)))
        for offset in range(0, self.MEMORY_SIZE, self.WRITE_BLOCK_SIZE):
            data = fw_bytes[offset:offset + self.WRITE_BLOCK_SIZE]
            ok = self.cmd_write_flash(offset, data)
            print(f"[~] Write 0x{len(data):02X} bytes at 0x{offset:04X}...[{'OK' if ok else 'FAILED'}]")
            if not ok: break
        return sum(len(chunk) for chunk in [fw_bytes[i:i + self.WRITE_BLOCK_SIZE] for i in range(0, len(fw_bytes), self.WRITE_BLOCK_SIZE)])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("serial_port", help="Serial port where the radio is connected.")
    parser.add_argument("firmware_file", help="File containing the firmware.")
    args = parser.parse_args()

    with RT4D(args.serial_port, 115200, write_timeout=5000, timeout=5) as rt4d, open(args.firmware_file, "rb") as file:
        fw = file.read()
        print(f"Firmware size {len(fw)} (0x{len(fw):04X}) bytes")

        if not rt4d.check_bootloader_mode():
            sys.exit("\n[E] Radio not on flashing mode, or not connected.")
        if not rt4d.cmd_erase_flash():
            sys.exit("\n[E] Could not erase radio memory.")

        print('[i] Flashing...')
        flashed_bytes = rt4d.flash_firmware(fw)
        if flashed_bytes != RT4D.MEMORY_SIZE:
            sys.exit(f"\n[E] Not all bytes are written {flashed_bytes}/{RT4D.MEMORY_SIZE}")
        print(f"[i] Written {flashed_bytes} (0x{flashed_bytes:0X}) bytes.\n[i] All OK!")
