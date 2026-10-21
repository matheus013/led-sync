"""Controle dos LEDs de placas Galax/KFA2 RTX via I2C da GPU (NvAPI).
# SPDX-License-Identifier: GPL-2.0-or-later

Protocolo "Galax v2" baseado no OpenRGB (Controllers/GalaxGPUController).
"""
import ctypes
import sys

NVAPI_INITIALIZE = 0x0150E828
NVAPI_ENUM_PHYSICAL_GPUS = 0xE5AC921F
NVAPI_I2C_WRITE_EX = 0x283AC65A
NVAPI_I2C_READ_EX = 0x4D7B0709

# Registradores do controlador Galax v2
REG_RED, REG_GREEN, REG_BLUE = 0x02, 0x03, 0x04
REG_SPEED_A, REG_SPEED_B = 0x21, 0x22
REG_SYNC = 0x27
REG_BRIGHTNESS = 0x2D
REG_MODE = 0x30
REG_SAVE = 0x40
MODE_STATIC, MODE_BREATHING, MODE_RAINBOW, MODE_OFF = 0x01, 0x02, 0x16, 0x19
SAVE_VALUE = 0x5A
CANDIDATE_ADDRESSES = (0x51, 0x50)


class NV_I2C_INFO_V3(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("display_mask", ctypes.c_uint32),
        ("is_ddc_port", ctypes.c_uint8),
        ("i2c_dev_address", ctypes.c_uint8),
        ("i2c_reg_address", ctypes.POINTER(ctypes.c_uint8)),
        ("reg_addr_size", ctypes.c_uint32),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
        ("size", ctypes.c_uint32),
        ("i2c_speed", ctypes.c_uint32),
        ("i2c_speed_khz", ctypes.c_int),
        ("port_id", ctypes.c_uint8),
        ("is_port_id_set", ctypes.c_uint32),
    ]


class NvI2C:
    def __init__(self, gpu_index=0):
        dll = ctypes.CDLL("nvapi64.dll")
        query = dll.nvapi_QueryInterface
        query.restype = ctypes.c_void_p
        query.argtypes = [ctypes.c_uint32]

        def fn(fid, *argtypes):
            ptr = query(fid)
            if not ptr:
                raise OSError(f"NvAPI função 0x{fid:08X} indisponível")
            return ctypes.CFUNCTYPE(ctypes.c_int, *argtypes)(ptr)

        fn(NVAPI_INITIALIZE)()
        handles = (ctypes.c_void_p * 64)()
        count = ctypes.c_int(0)
        fn(NVAPI_ENUM_PHYSICAL_GPUS, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))(handles, ctypes.byref(count))
        if gpu_index >= count.value:
            raise OSError("GPU NVIDIA não encontrada")
        self.handle = handles[gpu_index]
        sig = (ctypes.c_void_p, ctypes.POINTER(NV_I2C_INFO_V3), ctypes.POINTER(ctypes.c_uint32))
        self._read = fn(NVAPI_I2C_READ_EX, *sig)
        self._write = fn(NVAPI_I2C_WRITE_EX, *sig)

    def _xfer(self, func, addr, reg, value=0):
        reg_buf = (ctypes.c_uint8 * 1)(reg)
        data_buf = (ctypes.c_uint8 * 4)(value)
        info = NV_I2C_INFO_V3()
        info.version = ctypes.sizeof(NV_I2C_INFO_V3) | (3 << 16)
        info.is_ddc_port = 0
        info.i2c_dev_address = addr << 1
        info.i2c_reg_address = reg_buf
        info.reg_addr_size = 1
        info.data = data_buf
        info.size = 1
        info.i2c_speed = 0xFFFF
        info.i2c_speed_khz = 0
        info.port_id = 1  # porta onde ficam os controladores RGB
        info.is_port_id_set = 1
        unknown = ctypes.c_uint32(0)
        status = func(self.handle, ctypes.byref(info), ctypes.byref(unknown))
        return status, data_buf[0]

    def read_byte(self, addr, reg):
        status, value = self._xfer(self._read, addr, reg)
        return value if status == 0 else None

    def write_byte(self, addr, reg, value):
        status, _ = self._xfer(self._write, addr, reg, value)
        return status == 0


def is_galax_v2(bus, addr):
    """Teste de assinatura do OpenRGB, mais a variante encontrada na 4070 Ti EXG White V2."""
    r0 = bus.read_byte(addr, 0x00)
    if addr == 0x51:
        return r0 == 0x80
    if addr == 0x50:
        # 01 08 = RTX 4080 SG (OpenRGB); 02 01 = RTX 4070 Ti EX Gamer White V2
        return (r0, bus.read_byte(addr, 0x01)) in {(0x01, 0x08), (0x02, 0x01)}
    return False


class GalaxGPU:
    def __init__(self, bus=None, addr=None):
        self.bus = bus or NvI2C()
        self.addr = addr or next((a for a in CANDIDATE_ADDRESSES if is_galax_v2(self.bus, a)), None)
        if self.addr is None:
            raise OSError("Controlador de LED Galax não encontrado na GPU")

    def set_color(self, r, g, b):
        self.bus.write_byte(self.addr, REG_RED, r)
        self.bus.write_byte(self.addr, REG_GREEN, g)
        self.bus.write_byte(self.addr, REG_BLUE, b)

    def set_mode(self, mode):
        self.bus.write_byte(self.addr, REG_MODE, mode)

    def set_sync(self, on):
        self.bus.write_byte(self.addr, REG_SYNC, 1 if on else 0)

    def set_brightness(self, value):
        self.bus.write_byte(self.addr, REG_BRIGHTNESS, value)

    def save(self):
        self.bus.write_byte(self.addr, REG_SAVE, SAVE_VALUE)


class _Zone:
    def __init__(self, name, count):
        self.name = name
        self.leds = [0] * count


class _Mode:
    def __init__(self, name):
        self.name = name


class GalaxDevice:
    """Adapta a placa Galax à mesma interface dos dispositivos do openrgb-python."""

    def __init__(self, gpu, name="GALAX GeForce RTX 4070 Ti"):
        from openrgb.utils import DeviceType
        self.gpu = gpu
        self.name = name
        self.type = DeviceType.GPU
        self.id = "galax-i2c"
        self.leds = [0]  # a placa inteira acende numa cor só
        self.zones = [_Zone("Placa de vídeo", 1)]
        self.modes = [_Mode("Direct"), _Mode("Static")]
        self.colors = []
        self._last = None

    def set_mode(self, mode):
        # Sem MB Sync e em modo estático a placa mostra exatamente a cor dos registradores
        self.gpu.set_sync(False)
        self.gpu.set_mode(MODE_STATIC)
        self._last = None

    def set_color(self, color):
        self.set_colors([color])

    def set_colors(self, colors, fast=False):
        c = colors[0]
        rgb = (c.red, c.green, c.blue)
        last = self._last or (None, None, None)
        for reg, new, old in zip((REG_RED, REG_GREEN, REG_BLUE), rgb, last):
            if new != old:
                self.gpu.bus.write_byte(self.gpu.addr, reg, new)
        self._last = rgb
        self.colors = list(colors)

    def save_hardware(self):
        self.gpu.save()


def detect_devices():
    try:
        return [GalaxDevice(GalaxGPU())]
    except (OSError, AttributeError):
        return []


def probe():
    """Somente leitura: procura controladores conhecidos e mostra os registradores."""
    bus = NvI2C()
    for addr in (0x23, 0x32, 0x50, 0x51):
        r0, r1 = bus.read_byte(addr, 0x00), bus.read_byte(addr, 0x01)
        fmt = lambda v: "--" if v is None else f"{v:02X}"
        print(f"0x{addr:02X}: reg00={fmt(r0)} reg01={fmt(r1)}")
    for addr in CANDIDATE_ADDRESSES:
        if is_galax_v2(bus, addr):
            regs = {name: bus.read_byte(addr, reg) for name, reg in [
                ("red", REG_RED), ("green", REG_GREEN), ("blue", REG_BLUE), ("mode", REG_MODE),
                ("sync", REG_SYNC), ("brightness", REG_BRIGHTNESS), ("speed", REG_SPEED_A)]}
            print(f"Galax v2 encontrado em 0x{addr:02X}: {regs}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        probe()
