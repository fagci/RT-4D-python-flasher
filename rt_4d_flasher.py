#!/bin/python

import sys
import argparse

from serial import Serial

class RT4DFlasher(Serial):
    ACK_RESPONSE = b'\06'
    FLASH_MODE_RESPONSE = 0xFF
    CMD_ERASE_FLASH = 0x39
    CMD_READ_FLASH = 0x52
    CMD_WRITE_FLASH = 0x57
    WRITE_BLOCK_SIZE = 0x400
    MEMORY_SIZE = 0x3d800


    @classmethod
    def append_checksum(cls, data):
        data.append((sum(data) + 72) % 256)
        return bytearray(data)


    def check_bootloader_mode(self):
        while self.in_waiting:
            self.read()

        payload = [self.CMD_READ_FLASH, 0, 0]
        payload = self.append_checksum(payload)

        self.write(payload)
        response = bytearray(self.read(4))

        return response and response[0] == self.FLASH_MODE_RESPONSE


    def _cmd_erase_flash(self, part):
        payload = [self.CMD_ERASE_FLASH, 0x33, 0x05, 0x10 if part == 0 else 0x55]
        payload = self.append_checksum(payload)

        self.write(payload)
        return self.read(1) == self.ACK_RESPONSE


    def cmd_erase_flash(self):
        return self._cmd_erase_flash(0) and self._cmd_erase_flash(1)


    def cmd_write_flash(self, offset, data):
        payload = bytearray([self.CMD_WRITE_FLASH, (offset >> 8) & 0xFF, offset & 0xFF]) + data
        payload = self.append_checksum(payload)

        self.write(payload)
        return self.read(1) == self.ACK_RESPONSE


    def flash_firmware(self, fw_bytes):
        padding_to_add = self.MEMORY_SIZE - len(fw_bytes)
        fw_bytes += bytearray([0x0] * padding_to_add)

        chunks = [
            [offset, fw_bytes[offset : offset + self.WRITE_BLOCK_SIZE]]
            for offset in range(0, self.MEMORY_SIZE, self.WRITE_BLOCK_SIZE)
        ]

        total_bytes = 0
        for chunk in chunks:
            ok = self.cmd_write_flash(*chunk)

            print(f"[~] Write 0x{len(chunk[1]):02X} bytes at 0x{chunk[0]:04X}...[{'OK' if ok else 'FAILED'}]")

            if not ok:
                break

            total_bytes += len(chunk[1])

        print(f"[i] Written a total of {total_bytes} (0x{total_bytes:0X}) bytes.")
        return (total_bytes, padding_to_add)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("serial_port", help="serial port where the radio is connected.")
    parser.add_argument("firmware_file", help="file containing the firmware.")

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    with RT4DFlasher(args.serial_port, 115200, write_timeout=5000, timeout=5) as flasher:
        with open(args.firmware_file, "rb") as file:
            fw = file.read()

        fw_len = len(fw)
        print(f"Firmware size {fw_len} (0x{fw_len:04X}) bytes")

        if not flasher.check_bootloader_mode():
            sys.exit("\n[E] Radio not on flashing mode, or not connected.")

        if not flasher.cmd_erase_flash():
            sys.exit("\n[E] Could not erase radio memory.")

        print('[i] Flashing...')

        flashed_bytes, added_padding = flasher.flash_firmware(fw)
        padded_fw_size = fw_len + added_padding
        if flashed_bytes != padded_fw_size:
            sys.exit(f"\n[E] Not all bytes are written {flashed_bytes}/{padded_fw_size}")

        print("\n[i] All OK!")

