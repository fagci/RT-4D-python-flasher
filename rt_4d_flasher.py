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
        # discard any leftovers
        while self.in_waiting:
            self.read()

        payload = [self.CMD_READ_FLASH, 0, 0]
        payload = self.append_checksum(payload)

        print(f"CMD Read:\n{hexdump(payload, 32)}")

        self.write(payload)

        data_read = bytearray(self.read(4))

        # empty the input buffer, should be empty already
        # though, and maybe recover from a timeout

        for _i in range(8):
            while self.in_waiting:
                data_read += bytearray(self.read())

        if not data_read:
            return False

        print(f"Response:\n{hexdump(data_read, 32)}\n")

        return data_read[0] == self.FLASH_MODE_RESPONSE

    def _cmd_erase_flash(self, part):
        if part == 0:
            payload = [self.CMD_ERASE_FLASH, 0x33, 0x05, 0x10]
        else:
            payload = [self.CMD_ERASE_FLASH, 0x33, 0x05, 0x55]

        payload = self.append_checksum(payload)

        print(f"CMD Erase:\n{hexdump(payload, 32)}")

        self.write(payload)
        response = self.read(1)

        if not response:
            return False

        print(f"Response:\n{hexdump(response, 32)}")

        return response == self.ACK_RESPONSE

    def cmd_erase_flash(self):
        return self._cmd_erase_flash(0) and self._cmd_erase_flash(1)


    def cmd_write_flash(self, offset, bytes_128):
        if len(bytes_128) != self.WRITE_BLOCK_SIZE:
            raise AssertionError(
                (
                    "FAILED: FW chunk does not have the correct size. "
                    f"Got 0x{len(bytes_128):02X} bytes, expected 0x{self.WRITE_BLOCK_SIZE:02X}."
                )
            )

        payload = [self.CMD_WRITE_FLASH, (offset >> 8) & 0xFF, (offset >> 0) & 0xFF]
        payload += bytes_128
        payload = self.append_checksum(payload)
        print(f"{payload[0]:02x} {payload[1]:02x} {payload[2]:02x} | {payload[3]:02x} {payload[4]:02x} ... {payload[-3]:02x} {payload[-2]:02x} => {payload[-1]:02x}")

        self.write(payload)
        response = self.read(1)

        if not response:
            return False

        return response == self.ACK_RESPONSE

    def flash_firmware(self, fw_bytes):
        padding_to_add = (
            self.MEMORY_SIZE - len(fw_bytes) if len(fw_bytes) else 0
        )

        if padding_to_add:
            print(
                f"Note: Padding with {padding_to_add} ZERO-bytes to align the FW to {self.WRITE_BLOCK_SIZE:02x} bytes."
            )

            fw_bytes += bytearray([0x0] * padding_to_add)

        chunks = [
            [offset, fw_bytes[offset : offset + self.WRITE_BLOCK_SIZE]]
            for offset in range(0, self.MEMORY_SIZE, self.WRITE_BLOCK_SIZE)
        ]

        total_bytes = 0
        for chunk in chunks:
            ok = self.cmd_write_flash(*chunk)

            print(
                (
                    f"Writting at 0x{chunk[0]:04X}, "
                    f"length: 0x{len(chunk[1]):02X}, "
                    f"result: {'OK' if ok else 'FAILED'}"
                )
            )

            if not ok:
                break

            total_bytes += len(chunk[1])

        print(f"Written a total of {total_bytes} (0x{total_bytes:0X}) bytes.")
        return (total_bytes, padding_to_add)


def hexdump(byte_array, step):
    dump = [byte_array[off : off + step] for off in range(0, len(byte_array), step)]
    dump = [" ".join([f"{byte:02X}" for byte in _bytes]) for _bytes in dump]
    dump = [f"{off * step:03X} | {_bytes}" for off, _bytes in enumerate(dump)]
    header = ''

    separator = ["="] * len(dump[0])
    separator[4] = "|"
    separator = "".join(separator)

    return "{}\n{separator}\n{}\n{separator}".format(
        header, "\n".join(dump), separator=separator
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "A tool for programming RT-4D (and clones) firmware.\nFirst, "
            "put your radio on programming mode by turning it on while pressing PTT."
        ),
    )

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
            sys.exit("\nFAILED: Radio not on flashing mode, or not connected.")

        if not flasher.cmd_erase_flash():
            sys.exit("\nFAILED: Could not erase radio memory.")


        flashed_bytes, added_padding = flasher.flash_firmware(fw)
        padded_fw_size = fw_len + added_padding
        if flashed_bytes != padded_fw_size:
            sys.exit(
                (
                    "\nFAILED: The amount of bytes written does not match the "
                    f"FW size padded to 0x{WRITE_BLOCK_SIZE:02x}. "
                    f"Expected {padded_fw_size} (0x{padded_fw_size:04X}) bytes, "
                    f"wrote: {flashed_bytes} (0x{flashed_bytes:04X})."
                )
            )

        print("\nAll OK!")

        if flashed_bytes != RT4DFlasher.MEMORY_SIZE:
            NOTE_STR = (
                "# Note: The FW does not fill the whole memory."
                " The radio will not restart automatically. #"
            )
            FRAME = "#" * len(NOTE_STR)
            print(f"{FRAME}\n{NOTE_STR}\n{FRAME}")
