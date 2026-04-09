#
# License: See LICENSE.md file
# GitHub: https://github.com/Baekalfen/PyBoy
#

import array

import pyboy
from pyboy.utils import IntIOWrapper, PyBoyException, PyBoyInvalidInputException

from .rtc import RTC

logger = pyboy.logging.get_logger(__name__)


class BaseMBC:
    def __init__(self, rombanks, ram_file, rtc_file, external_ram_count, carttype, sram, battery, rtc_enabled):
        self.rombanks = rombanks
        self.carttype = carttype

        self.battery = battery
        self.rtc_enabled = rtc_enabled

        if self.rtc_enabled:
            self.rtc = RTC(rtc_file)
        else:
            self.rtc = None

        self.rambank_initialized = False
        self.external_rom_count = len(rombanks)
        self.external_ram_count = external_ram_count
        self.init_rambanks(external_ram_count)

        # CGB flag overlaps with earlier game titles
        self.cgb = bool(self.rombanks[0, 0x0143] >> 7)
        self.gamename = self.getgamename(rombanks)

        self.memorymodel = 0
        self.rambank_enabled = False
        self.rambank_selected = 0
        self.rombank_selected = 1
        self.rombank_selected_low = 0

        if ram_file is not None and self.battery:
            self.load_ram(IntIOWrapper(ram_file))
        else:
            logger.debug("No RAM file found. Skipping.")

    def stop(self, ram_file, rtc_file):
        if ram_file is not None and self.battery:
            self.save_ram(IntIOWrapper(ram_file))

        if self.rtc_enabled:
            self.rtc.stop(rtc_file)

    def save_state(self, f):
        f.write(self.rombank_selected)
        f.write(self.rambank_selected)
        f.write(self.rambank_enabled)
        f.write(self.memorymodel)
        self.save_ram(f)
        if self.rtc_enabled:
            self.rtc.save_state(f)

    def load_state(self, f, state_version):
        self.rombank_selected = f.read()
        self.rambank_selected = f.read()
        self.rambank_enabled = f.read()
        self.memorymodel = f.read()
        self.load_ram(f)
        if self.rtc_enabled:
            self.rtc.load_state(f, state_version)

    def save_ram(self, f):
        if not self.rambank_initialized:
            logger.warning("Saving RAM is not supported on %0.2x", self.carttype)
            return 0

        for bank in range(self.external_ram_count):
            for byte in range(8 * 1024):
                f.write(self.rambanks[bank, byte])

        logger.debug("RAM saved.")

    def load_ram(self, f):
        if not self.rambank_initialized:
            logger.warning("Loading RAM is not supported on %0.2x", self.carttype)
            return 0

        for bank in range(self.external_ram_count):
            for byte in range(8 * 1024):
                self.rambanks[bank, byte] = f.read()

        logger.debug("RAM loaded.")

    def init_rambanks(self, n):
        self.rambank_initialized = True
        # In real life the values in RAM are scrambled on initialization.
        # Allocating the maximum, as it is easier in Cython. And it's just 128KB...
        self.rambanks = memoryview(array.array("B", [0] * (8 * 1024 * 16))).cast("B", shape=(16, 8 * 1024))

    def getgamename(self, rombanks):
        # Title was originally 0x134-0x143.
        # Later 0x13F-0x142 became manufacturer code and 0x143 became a CGB flag
        if self.cgb:
            end = 0x0142  # Including manufacturer code
            # end = 0x013F # Excluding potential(?) manufacturer code
        else:
            end = 0x0143
        return "".join([chr(rombanks[0, x]) for x in range(0x0134, end)]).split("\0")[0]

    def setitem(self, address, value):
        raise PyBoyException("Cannot set item in MBC")

    def overrideitem(self, rom_bank, address, value):
        if 0x0000 <= address < 0x4000:
            logger.debug(
                "Performing overwrite on address: 0x%04x:0x%04x. New value: 0x%04x Old value: 0x%04x",
                rom_bank,
                address,
                value,
                self.rombanks[rom_bank, address],
            )
            self.rombanks[rom_bank, address] = value
        else:
            raise PyBoyInvalidInputException("Invalid override address: %0.4x", address)

    def getitem(self, address):
        if 0xA000 <= address < 0xC000:
            # if not self.rambank_initialized:
            #     logger.error("RAM banks not initialized: 0.4x", address)

            if not self.rambank_enabled:
                return 0xFF

            if self.rtc_enabled and 0x08 <= self.rambank_selected <= 0x0C:
                return self.rtc.getregister(self.rambank_selected)
            else:
                return self.rambanks[self.rambank_selected, address - 0xA000]
        # else:
        #     logger.error("Reading address invalid: %0.4x", address)

    def __repr__(self):
        return "\n".join(
            [
                "MBC class: %s" % self.__class__.__name__,
                "Game name: %s" % self.gamename,
                "GB Color: %s" % str(self.rombanks[0, 0x143] == 0x80),
                "Cartridge type: %s" % hex(self.carttype),
                "Number of ROM banks: %s" % self.external_rom_count,
                "Active ROM bank: %s" % self.rombank_selected,
                # "Memory bank type: %s" % self.ROMBankController,
                "Number of RAM banks: %s" % len(self.rambanks),
                "Active RAM bank: %s" % self.rambank_selected,
                "Battery: %s" % self.battery,
                "RTC: %s" % self.rtc_enabled,
            ]
        )

# ROM-only is the simplest cartridge type.
#
# In the normal case:
# - the cartridge is just 32KB total
# - bank 0 is shown at 0x0000-0x3FFF
# - bank 1 is shown at 0x4000-0x7FFF
# - there is no real bank switching logic
#
# Some unlicensed or homebrew games are different. They still *claim* to be
# ROM-only in the header, but the ROM is larger than 32KB and writes to the
# cartridge control area are used to switch banks anyway. Wisdom Tree games are
# a common example. This class keeps the simple ROM-only behavior, but also
# handles those non-standard switching cases when more than two ROM banks exist.
class ROMOnly(BaseMBC):
    """Handle cartridges marked as ROM-only.

    A true ROM-only game is fixed and simple. If a cartridge reports ROM-only
    but contains more than two ROM banks, it may actually be an oversized cart
    that still performs bank switching through special write addresses.
    """

    def setitem(self, address, value):
        """Interpret writes to ROM-only cartridges.

        Address ranges used here:
        - 0x0000-0x1FFF: Wisdom Tree-style full 32KB window switching based on
          the write address itself.
        - 0x2000-0x3FFF: regular value-based bank selection for oversized ROMs.
        - 0xA000-0xBFFF: external RAM writes.
        """
        # More than two ROM banks means the cartridge is larger than a normal
        # 32KB ROM-only game. At that point, writes in the control region may
        # need to be treated as bank-switch commands
        if self.external_rom_count > 2 and 0x0000 <= address < 0x2000:
            # Wisdom Tree-style mappers choose a *pair* of visible 16KB banks
            # from the low byte of the address.
            #
            # Easy example:
            # - write to 0x0000 -> page = 0 -> show banks 0 and 1
            # - write to 0x0001 -> page = 1 -> show banks 2 and 3
            # - write to 0x0002 -> page = 2 -> show banks 4 and 5
            #
            # So 0x0002 does NOT mean "switch to bank 2".
            # Instead, the mapper reads the low byte of the address, doubles it,
            # and uses that result to choose the next 32KB ROM chunk.
            #
            # `address & 0xFF` means "keep only the lowest 8 bits of the
            # address". That low byte is the number this mapper uses.
            page = address & 0xFF
            self.rombank_selected_low = (page * 2) % self.external_rom_count
            self.rombank_selected = (self.rombank_selected_low + 1) % self.external_rom_count
            logger.debug(
                "Switching full ROM window 0x%0.4x, 0x%0.2x -> (%d, %d)",
                address,
                value,
                self.rombank_selected_low,
                self.rombank_selected,
            )
        elif 0x2000 <= address < 0x4000:
            if value == 0:
                value = 1

            # This is the more standard style of switching: the written value is
            # used as the bank number for the upper 16KB ROM window.
            #
            # So if the game writes value 5 here, PyBoy shows ROM bank 5 at
            # 0x4000-0x7FFF.
            #
            # Bank 0 is avoided in the switchable slot because many cartridges
            # reserve it for the fixed lower ROM area.
            self.rombank_selected = value % self.external_rom_count
            if self.external_rom_count > 1 and self.rombank_selected == 0:
                self.rombank_selected = 1
            logger.debug("Switching bank 0x%0.4x, 0x%0.2x -> %d", address, value, self.rombank_selected)
        elif 0xA000 <= address < 0xC000:
            self.rambanks[self.rambank_selected, address - 0xA000] = value
        # else:
        #     logger.debug("Unexpected write to 0x%0.4x, value: 0x%0.2x", address, value)
