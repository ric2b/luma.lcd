# -*- coding: utf-8 -*-
# Copyright (c) 2013-17 Richard Hull and contributors
# See LICENSE.rst for details.

"""
Collection of serial interfaces to LCD devices.
"""

# Example usage:
#
#   from luma.core.interface.serial import spi
#   from luma.core.render import canvas
#   from luma.lcd.device import pcd8544
#   from PIL import ImageDraw
#
#   serial = spi(port=0, device=0)
#   device = pcd8544(serial)
#
#   with canvas(device) as draw:
#      draw.rectangle(device.bounding_box, outline="white", fill="black")
#      draw.text(30, 40, "Hello World", fill="white")
#
# As soon as the with-block scope level is complete, the graphics primitives
# will be flushed to the device.
#
# Creating a new canvas is effectively 'carte blanche': If you want to retain
# an existing canvas, then make a reference like:
#
#    c = canvas(device)
#    for X in ...:
#        with c as draw:
#            draw.rectangle(...)
#
# As before, as soon as the with block completes, the canvas buffer is flushed
# to the device

from luma.core.lib import rpi_gpio
from luma.core.device import device
from luma.core.interface.serial import noop
import luma.core.error
import luma.core.framebuffer
import luma.lcd.const
from luma.lcd.segment_mapper import dot_muncher


__all__ = ["pcd8544", "st7735", "ht1621", "uc1701x", "st7567", "ili9341"]


@rpi_gpio
class backlit_device(device):
    """
    Controls a backlight (active low), assumed to be on GPIO 18 (``PWM_CLK0``) by default.

    :param gpio: GPIO interface (must be compatible with `RPi.GPIO <https://pypi.python.org/pypi/RPi.GPIO>`_).
    :param gpio_LIGHT: the GPIO pin to use for the backlight.
    :type gpio_LIGHT: int
    :param active_low: Set to true if active low (default), false otherwise.
    :type active_low: bool
    :raises luma.core.error.UnsupportedPlatform: GPIO access not available.

    .. versionadded:: 2.0.0
    """
    def __init__(self, const=None, serial_interface=None, gpio=None, gpio_LIGHT=18, active_low=True, **kwargs):
        super(backlit_device, self).__init__(const, serial_interface)

        self._gpio_LIGHT = gpio_LIGHT
        self._gpio = gpio or self.__rpi_gpio__()
        if active_low:
            self._enabled = self._gpio.LOW
            self._disabled = self._gpio.HIGH
        else:
            self._enabled = self._gpio.HIGH
            self._disabled = self._gpio.LOW

        try:
            self._gpio.setup(self._gpio_LIGHT, self._gpio.OUT)
        except RuntimeError as e:
            if str(e) == 'Module not imported correctly!':
                raise luma.core.error.UnsupportedPlatform('GPIO access not available')

        self.persist = True
        self.backlight(True)

    def backlight(self, value):
        """
        Switches on the backlight on and off.

        :param value: Switched on when ``True`` supplied, else ``False`` switches it off.
        :type value: bool
        """
        assert(value in [True, False])
        self._gpio.output(self._gpio_LIGHT,
                          self._enabled if value else self._disabled)

    def cleanup(self):
        """
        Attempt to reset the device & switching it off prior to exiting the
        python process.
        """
        super(backlit_device, self).cleanup()
        if self.persist:
            self.backlight(False)


class pcd8544(backlit_device):
    """
    Serial interface to a monochrome PCD8544 LCD display.

    On creation, an initialization sequence is pumped to the display
    to properly configure it. Further control commands can then be called to
    affect the brightness and other settings.

    :param serial_interface: The serial interface (usually a
        :py:class:`luma.core.interface.serial.spi` instance) to delegate sending
        data and commands through.
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int
    """
    def __init__(self, serial_interface=None, rotate=0, **kwargs):
        super(pcd8544, self).__init__(luma.lcd.const.pcd8544, serial_interface, **kwargs)
        self.capabilities(84, 48, rotate)

        self._mask = [1 << (i // self._w) % 8 for i in range(self._w * self._h)]
        self._offsets = [(self._w * (i // (self._w * 8))) + (i % self._w) for i in range(self._w * self._h)]

        self.contrast(0xB0)
        self.clear()
        self.show()

    def display(self, image):
        """
        Takes a 1-bit :py:mod:`PIL.Image` and dumps it to the PCD8544
        LCD display.
        """
        assert(image.mode == self.mode)
        assert(image.size == self.size)

        image = self.preprocess(image)

        self.command(0x20, 0x80, 0x40)

        buf = bytearray(self._w * self._h // 8)
        off = self._offsets
        mask = self._mask

        for idx, pix in enumerate(image.getdata()):
            if pix > 0:
                buf[off[idx]] |= mask[idx]

        self.data(list(buf))

    def contrast(self, value):
        """
        Sets the LCD contrast
        """
        assert(0 <= value <= 255)
        self.command(0x21, 0x14, value | 0x80, 0x20)


class st7567(backlit_device):
    """
    Serial interface to a monochrome ST7567 128x64 pixel LCD display.

    On creation, an initialization sequence is pumped to the display to properly
    configure it. Further control commands can then be called to affect the
    brightness and other settings.

    :param serial_interface: The serial interface (usually a
        :py:class:`luma.core.interface.serial.spi` instance) to delegate sending
        data and commands through.
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int

    .. versionadded:: 1.1.0
    """
    def __init__(self, serial_interface=None, rotate=0, **kwargs):
        super(st7567, self).__init__(luma.lcd.const.st7567, serial_interface, **kwargs)
        self.capabilities(128, 64, rotate)

        self._pages = self._h // 8

        self.command(0xA3)  # Bias 1/7
        self.command(0xA1)
        self.command(0xC0)  # Normal Orientation
        self.command(0xA6)  # Normal Display (0xA7 = inverse)
        self.command(0x40)
        self.command(0x2F)
        self.command(0x22)
        self.command(0xAF)

        self.contrast(57)

        self.clear()
        self.show()

    def display(self, image):
        """
        Takes a 1-bit :py:mod:`PIL.Image` and dumps it to the ST7567
        LCD display
        """
        assert(image.mode == self.mode)
        assert(image.size == self.size)

        image = self.preprocess(image)

        set_page_address = 0xB0

        image_data = image.getdata()
        pixels_per_page = self.width * 8
        buf = bytearray(self.width)

        for y in range(0, int(self._pages * pixels_per_page), pixels_per_page):
            self.command(set_page_address, 0x04, 0x10)
            set_page_address += 1
            offsets = [y + self.width * i for i in range(8)]

            for x in range(self.width):
                buf[x] = \
                    (image_data[x + offsets[0]] and 0x01) | \
                    (image_data[x + offsets[1]] and 0x02) | \
                    (image_data[x + offsets[2]] and 0x04) | \
                    (image_data[x + offsets[3]] and 0x08) | \
                    (image_data[x + offsets[4]] and 0x10) | \
                    (image_data[x + offsets[5]] and 0x20) | \
                    (image_data[x + offsets[6]] and 0x40) | \
                    (image_data[x + offsets[7]] and 0x80)

            self.data(list(buf))

    def contrast(self, value):
        """
        Sets the LCD contrast
        """
        assert(0 <= value <= 255)
        self.command(0x81, value)


class st7735(backlit_device):
    """
    Serial interface to a 262K color (6-6-6 RGB) ST7735 LCD display.

    On creation, an initialization sequence is pumped to the display to properly
    configure it. Further control commands can then be called to affect the
    brightness and other settings.

    :param serial_interface: the serial interface (usually a
        :py:class:`luma.core.interface.serial.spi` instance) to delegate sending
        data and commands through.
    :param width: The number of pixels laid out horizontally.
    :type width: int
    :param height: The number of pixels laid out vertically.
    :type width: int
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int
    :param framebuffer: Framebuffering strategy, currently values of
        ``diff_to_previous`` or ``full_frame`` are only supported.
    :type framebuffer: str
    :param bgr: Set to ``True`` if device pixels are BGR order (rather than RGB).
    :type bgr: bool
    :param h_offset: Horizontal offset (in pixels) of screen to device memory
        (default: 0).
    :type h_offset: int
    :param v_offset: Vertical offset (in pixels) of screen to device memory
        (default: 0).
    :type v_offset: int

    .. versionadded:: 0.3.0
    """
    def __init__(self, serial_interface=None, width=160, height=128, rotate=0,
                 framebuffer="diff_to_previous", h_offset=0, v_offset=0,
                 bgr=False, **kwargs):
        super(st7735, self).__init__(luma.lcd.const.st7735, serial_interface, **kwargs)
        self.capabilities(width, height, rotate, mode="RGB")
        self.framebuffer = getattr(luma.core.framebuffer, framebuffer)(self)

        if h_offset != 0 or v_offset != 0:
            def offset(bbox):
                left, top, right, bottom = bbox
                return (left + h_offset, top + v_offset, right + h_offset, bottom + v_offset)
            self.apply_offsets = offset
        else:
            self.apply_offsets = lambda bbox: bbox

        # Supported modes
        supported = (width, height) in [(160, 80), (160, 128), (128, 128)]
        if not supported:
            raise luma.core.error.DeviceDisplayModeError(
                "Unsupported display mode: {0} x {1}".format(width, height))

        # RGB or BGR order
        order = 0x08 if bgr else 0x00

        self.command(0x01)                      # reset
        self.command(0x11)                      # sleep out & booster on
        self.command(0xB1, 0x01, 0x2C, 0x2D)    # frame rate control: normal mode
        self.command(0xB2, 0x01, 0x2C, 0x2D)    # frame rate control: idle mode
        self.command(0xB3, 0x01, 0x2C, 0x2D,    # frame rate control: partial mode dot inversion mode
                     0x01, 0x2C, 0x2D)          # frame rate control: line inversion mode
        self.command(0xB4, 0x07)                # display inversion: none
        self.command(0xC0, 0xA2, 0x02, 0x84)    # power control 1: -4.6V auto mode
        self.command(0xC1, 0xC5)                # power control 2: VGH
        self.command(0xC2, 0x0A, 0x00)          # power control 3: OpAmp current small, boost freq
        self.command(0xC3, 0x8A, 0x2A)          # power control 4: BCLK/2, Opamp current small & Medium low
        self.command(0xC4, 0x8A, 0xEE)          # power control 5: partial mode/full-color
        self.command(0xC5, 0x0E)                # VCOM Control 1
        self.command(0x36, 0x60 | order)        # memory data access control
        self.command(0x20)                      # display inversion off
        self.command(0x3A, 0x06)                # interface pixel format
        self.command(0x13)                      # partial off (normal)
        self.command(0xE0,                      # gamma adjustment (+ polarity)
                     0x0F, 0x1A, 0x0F, 0x18, 0x2F, 0x28, 0x20, 0x22,
                     0x1F, 0x1B, 0x23, 0x37, 0x00, 0x07, 0x02, 0x10)
        self.command(0xE1,                      # gamma adjustment (- polarity)
                     0x0F, 0x1B, 0x0F, 0x17, 0x33, 0x2C, 0x29, 0x2E,
                     0x30, 0x30, 0x39, 0x3F, 0x00, 0x07, 0x03, 0x10)

        self.clear()
        self.show()

    def display(self, image):
        """
        Renders a 24-bit RGB image to the ST7735 LCD display. The 8-bit RGB
        values are passed directly to the devices internal storage, but only
        the 6 most-significant bits are used by the display.

        :param image: The image to render.
        :type image: PIL.Image.Image
        """
        assert(image.mode == self.mode)
        assert(image.size == self.size)

        image = self.preprocess(image)

        if self.framebuffer.redraw_required(image):
            left, top, right, bottom = self.apply_offsets(self.framebuffer.bounding_box)
            width = right - left
            height = bottom - top

            self.command(0x2A, left >> 8, left & 0xFF, (right - 1) >> 8, (right - 1) & 0xFF)     # Set column addr
            self.command(0x2B, top >> 8, top & 0xFF, (bottom - 1) >> 8, (bottom - 1) & 0xFF)     # Set row addr
            self.command(0x2C)                                                                   # Memory write

            i = 0
            buf = bytearray(width * height * 3)
            for r, g, b in self.framebuffer.getdata():
                if not(r == g == b == 0):
                    # 262K format
                    buf[i] = r
                    buf[i + 1] = g
                    buf[i + 2] = b
                i += 3

            self.data(list(buf))

    def contrast(self, level):
        """
        NOT SUPPORTED

        :param level: Desired contrast level in the range of 0-255.
        :type level: int
        """
        assert(0 <= level <= 255)

    def command(self, cmd, *args):
        """
        Sends a command and an (optional) sequence of arguments through to the
        delegated serial interface. Note that the arguments are passed through
        as data.
        """
        self._serial_interface.command(cmd)
        if len(args) > 0:
            self._serial_interface.data(list(args))


class ili9341(backlit_device):
    """
    Serial interface to a 262k color (6-6-6 RGB) ILI9341 LCD display.

    On creation, an initialization sequence is pumped to the display to properly
    configure it. Further control commands can then be called to affect the
    brightness and other settings.

    :param serial_interface: the serial interface (usually a
        :py:class:`luma.core.interface.serial.spi` instance) to delegate sending
        data and commands through.
    :param width: The number of pixels laid out horizontally.
    :type width: int
    :param height: The number of pixels laid out vertically.
    :type width: int
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int
    :param framebuffer: Framebuffering strategy, currently values of
        ``diff_to_previous`` or ``full_frame`` are only supported.
    :type framebuffer: str
    :param bgr: Set to ``True`` if device pixels are BGR order (rather than RGB).
    :type bgr: bool
    :param h_offset: Horizontal offset (in pixels) of screen to device memory
        (default: 0).
    :type h_offset: int
    :param v_offset: Vertical offset (in pixels) of screen to device memory
        (default: 0).
    :type v_offset: int

    .. versionadded:: 2.1.0
    """
    def __init__(self, serial_interface=None, width=320, height=240, rotate=0,
                 framebuffer="diff_to_previous", h_offset=0, v_offset=0,
                 bgr=False, **kwargs):
        super(ili9341, self).__init__(luma.lcd.const.ili9341, serial_interface, **kwargs)
        self.capabilities(width, height, rotate, mode="RGB")
        self.framebuffer = getattr(luma.core.framebuffer, framebuffer)(self)

        if h_offset != 0 or v_offset != 0:
            def offset(bbox):
                left, top, right, bottom = bbox
                return (left + h_offset, top + v_offset, right + h_offset, bottom + v_offset)
            self.apply_offsets = offset
        else:
            self.apply_offsets = lambda bbox: bbox

        # Supported modes
        supported = (width, height) in [(320, 240), (240, 240), (320, 180)]  # full, 1x1, 16x9
        if not supported:
            raise luma.core.error.DeviceDisplayModeError(
                "Unsupported display mode: {0} x {1}".format(width, height))

        # RGB or BGR order
        order = 0x00 if bgr else 0x08

        # Note: based on the Adafruit implementation at
        # `https://github.com/adafruit/Adafruit_CircuitPython_RGB_Display` (MIT licensed)

        self.command(0xef, 0x03, 0x80, 0x02)              # ?
        self.command(0xcf, 0x00, 0xc1, 0x30)              # Power control B
        self.command(0xed, 0x64, 0x03, 0x12, 0x81)        # Power on sequence control
        self.command(0xe8, 0x85, 0x00, 0x78)              # Driver timing control A
        self.command(0xcb, 0x39, 0x2c, 0x00, 0x34, 0x02)  # Power control A
        self.command(0xf7, 0x20)                          # Pump ratio control
        self.command(0xea, 0x00, 0x00)                    # Driver timing control B
        self.command(0xc0, 0x23)                          # Power Control 1, VRH[5:0]
        self.command(0xc1, 0x10)                          # Power Control 2, SAP[2:0], BT[3:0]
        self.command(0xc5, 0x3e, 0x28)                    # VCM Control 1
        self.command(0xc7, 0x86)                          # VCM Control 2
        self.command(0x36, 0x20 | order)                  # Memory Access Control
        self.command(0x3a, 0x46)                          # Pixel Format 6-6-6
        self.command(0xb1, 0x00, 0x18)                    # FRMCTR1
        self.command(0xb6, 0x08, 0x82, 0x27)              # Display Function Control
        self.command(0xf2, 0x00)                          # 3Gamma Function Disable
        self.command(0x26, 0x01)                          # Gamma Curve Selected
        self.command(0xe0,                                # Set Gamma (+ polarity)
                     0x0f, 0x31, 0x2b, 0x0c, 0x0e, 0x08, 0x4e, 0xf1,
                     0x37, 0x07, 0x10, 0x03, 0x0e, 0x09, 0x00)
        self.command(0xe1,                                # Set Gamma (- polarity)
                     0x00, 0x0e, 0x14, 0x03, 0x11, 0x07, 0x31, 0xc1,
                     0x48, 0x08, 0x0f, 0x0c, 0x31, 0x36, 0x0f)
        self.command(0x11)                                # Sleep out
        self.clear()
        self.show()

    def display(self, image):
        """
        Renders a 24-bit RGB image to the ILI9341 LCD display. The 8-bit RGB
        values are passed directly to the devices internal storage, but only
        the 6 most-significant bits are used by the display.

        :param image: The image to render.
        :type image: PIL.Image.Image
        """
        assert(image.mode == self.mode)
        assert(image.size == self.size)

        image = self.preprocess(image)

        if self.framebuffer.redraw_required(image):
            left, top, right, bottom = self.apply_offsets(self.framebuffer.bounding_box)

            self.command(0x2a, left >> 8, left & 0xff, (right - 1) >> 8, (right - 1) & 0xff)     # Set column addr
            self.command(0x2b, top >> 8, top & 0xff, (bottom - 1) >> 8, (bottom - 1) & 0xff)     # Set row addr
            self.command(0x2c)                                                                   # Memory write

            self.data(self.framebuffer.image.crop(self.framebuffer.bounding_box).tobytes())

    def contrast(self, level):
        """
        NOT SUPPORTED

        :param level: Desired contrast level in the range of 0-255.
        :type level: int
        """
        assert(0 <= level <= 255)

    def command(self, cmd, *args):
        """
        Sends a command and an (optional) sequence of arguments through to the
        delegated serial interface. Note that the arguments are passed through
        as data.
        """
        self._serial_interface.command(cmd)
        if len(args) > 0:
            self._serial_interface.data(list(args))


@rpi_gpio
class ht1621(backlit_device):
    """
    Serial interface to a seven segment HT1621 monochrome LCD display.

    On creation, an initialization sequence is pumped to the display to properly
    configure it. Further control commands can then be called to affect the
    brightness and other settings.

    :param gpio: The GPIO library to use (usually RPi.GPIO)
        to delegate sending data and commands through.
    :param width: The number of 7 segment characters laid out horizontally.
    :type width: int
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int
    :param WR: The write (SPI clock) pin to connect to, default BCM 11.
    :type WR: int
    :param DAT: The data pin to connect to, default BCM 10.
    :type DAT: int
    :param CS: The chip select pin to connect to, default BCM 8.
    :type CS: int

    .. versionadded:: 0.4.0
    """
    def __init__(self, gpio=None, width=6, rotate=0, WR=11, DAT=10, CS=8, **kwargs):
        if 'serial_interface' in kwargs:
            del kwargs['serial_interface']
        super(ht1621, self).__init__(luma.lcd.const.ht1621, noop(), gpio=gpio, **kwargs)
        self.capabilities(width, 8, rotate)
        self.segment_mapper = dot_muncher
        self._gpio = gpio or self.__rpi_gpio__()

        self._WR = self._configure(WR)
        self._DAT = self._configure(DAT)
        self._CS = self._configure(CS)

        self.command(0x30)   # Internal RC oscillator @ 256KHz
        self.command(0x52)   # 1/2 Bias and 4 commons
        self.command(0x02)   # System enable

        self.clear()
        self.show()

    def _configure(self, pin):
        if pin is not None:
            self._gpio.setup(pin, self._gpio.OUT)
            return pin

    def display(self, image):
        """
        Takes a 1-bit :py:mod:`PIL.Image` and dumps it to the PCD8544
        LCD display.
        """
        assert(image.mode == self.mode)
        assert(image.size == self.size)

        image = self.preprocess(image)

        buf = []

        for x in range(self._w):
            byte = 0
            for y in range(self._h):
                if image.getpixel((x, y)) > 0:
                    byte |= 1 << y

            buf.append(byte)

        self.data(buf)

    def command(self, cmd):
        gpio = self._gpio
        gpio.output(self._CS, gpio.LOW)
        self._write_bits(0x80, 4)   # Command mode
        self._write_bits(cmd, 8)
        gpio.output(self._CS, gpio.HIGH)

    def data(self, data):
        gpio = self._gpio
        gpio.output(self._CS, gpio.LOW)
        self._write_bits(0xA0, 3)   # Write mode
        self._write_bits(0x00, 6)   # Address
        for byte in data:
            self._write_bits(byte, 8)
        gpio.output(self._CS, gpio.HIGH)

    def _write_bits(self, value, num_bits):
        gpio = self._gpio
        for _ in range(num_bits):
            gpio.output(self._WR, gpio.LOW)
            bit = gpio.HIGH if value & 0x80 > 0 else gpio.LOW
            gpio.output(self._DAT, bit)
            value <<= 1
            gpio.output(self._WR, gpio.HIGH)

    def cleanup(self):
        """
        Attempt to reset the device & switching it off prior to exiting the
        python process.
        """
        super(ht1621, self).cleanup()
        self.command(0x00)   # System disable
        self._gpio.cleanup()


class uc1701x(backlit_device):
    """
    Serial interface to a monochrome UC1701X LCD display.

    On creation, an initialization sequence is pumped to the display to properly
    configure it. Further control commands can then be called to affect the
    brightness and other settings.

    :param serial_interface: The serial interface (usually a
        :py:class:`luma.core.interface.serial.spi` instance) to delegate sending
        data and commands through.
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int

    .. versionadded:: 0.5.0
    """
    def __init__(self, serial_interface=None, rotate=0, **kwargs):
        super(uc1701x, self).__init__(luma.lcd.const.uc1701x, serial_interface, **kwargs)
        self.capabilities(128, 64, rotate)

        self._pages = self._h // 8

        self.command(0xE2)          # System reset
        self.command(0x2C)          # Power: Boost ON
        self.command(0x2E)          # Power: Voltage Regulator ON
        self.command(0x2F)          # Power: Voltage Follower ON
        self.command(0xF8, 0x00)    # Booster ratio to 4x
        self.command(0x23)          # Set resistor ratio = 3
        self.command(0xA2)          # Bias 1/9
        self.command(0xC0)          # Set COM direction
        self.command(0xA1)          # Set SEG direction
        self.command(0xAC)          # Static indicator
        self.command(0xA6)          # Disable inverse
        self.command(0xA5)          # Display all points
        self.command(0xA4)          # Normal Display

        self.contrast(0xB0)

        self.clear()
        self.show()

    def display(self, image):
        """
        Takes a 1-bit :py:mod:`PIL.Image` and dumps it to the UC1701X
        LCD display.
        """
        assert(image.mode == self.mode)
        assert(image.size == self.size)

        image = self.preprocess(image)

        set_page_address = 0xB0
        image_data = image.getdata()
        pixels_per_page = self.width * 8
        buf = bytearray(self.width)

        for y in range(0, int(self._pages * pixels_per_page), pixels_per_page):
            self.command(set_page_address, 0x04, 0x10)
            set_page_address += 1
            offsets = [y + self.width * i for i in range(8)]

            for x in range(self.width):
                buf[x] = \
                    (image_data[x + offsets[0]] and 0x01) | \
                    (image_data[x + offsets[1]] and 0x02) | \
                    (image_data[x + offsets[2]] and 0x04) | \
                    (image_data[x + offsets[3]] and 0x08) | \
                    (image_data[x + offsets[4]] and 0x10) | \
                    (image_data[x + offsets[5]] and 0x20) | \
                    (image_data[x + offsets[6]] and 0x40) | \
                    (image_data[x + offsets[7]] and 0x80)

            self.data(list(buf))

    def contrast(self, value):
        """
        Sets the LCD contrast
        """
        assert(0 <= value <= 255)
        self.command(0x81, value >> 2)
