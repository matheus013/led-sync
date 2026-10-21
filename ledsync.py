"""LED Sync - controla e sincroniza todos os LEDs RGB via servidor SDK do OpenRGB."""
# SPDX-License-Identifier: GPL-2.0-or-later
import colorsys
import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, RGBColor

import galax_gpu

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
INDEX_PATH = os.path.join(HERE, "index.html")
OPENRGB_EXE = r"C:\Program Files\OpenRGB\OpenRGB.exe"
PORT = 7777
FPS = 30
# Dispositivos sem fio: atualiza com menos frequência para não travar o receptor nem gastar bateria
SLOW_TYPES = {DeviceType.MOUSE, DeviceType.HEADSET, DeviceType.KEYBOARD}
SLOW_INTERVAL = 0.15
RESEND_INTERVAL = 2.0

EFFECTS = ["static", "breathing", "spectrum", "rainbow", "gradient",
           "audio_pulse", "audio_spectrum", "audio_color", "native", "off"]
AUDIO_EFFECTS = {"audio_pulse", "audio_spectrum", "audio_color"}
AUDIO_RATE = 48000
AUDIO_BLOCK = 1024  # ~21 ms por bloco
AUDIO_BANDS = 12
DEFAULTS = {
    "effect": "rainbow",
    "color": "#00aaff",
    "color2": "#ff0066",
    "brightness": 100,
    "speed": 40,
    "disabled": [],
    "zone_sizes": {},
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_addressable(zone):
    """Conectores ARGB (fans/fitas do gabinete) aceitam qualquer quantidade de LEDs."""
    name = zone.name.lower()
    return "addressable" in name or "argb" in name or not zone.leds


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hsv(hue):
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 1.0, 1.0)
    return (r * 255, g * 255, b * 255)


class AudioMeter:
    """Captura o som que sai do PC (loopback WASAPI) e extrai volume, faixas de frequência e batidas."""

    def __init__(self):
        self.active = False
        self.device = None
        self.error = None
        self.level = 0.0
        self.bands = [0.0] * AUDIO_BANDS
        self.beat = 0.0
        self.beat_count = 0

    def run(self):
        while True:
            if not self.active:
                self.level, self.bands, self.beat = 0.0, [0.0] * AUDIO_BANDS, 0.0
                time.sleep(0.3)
                continue
            try:
                self.capture()
            except Exception as e:
                self.error = f"Erro no áudio: {e}"
                time.sleep(2)

    def capture(self):
        import numpy as np
        import soundcard as sc  # importado nesta thread por causa da inicialização COM

        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        self.device, self.error = speaker.name, None

        freqs = np.fft.rfftfreq(AUDIO_BLOCK, 1 / AUDIO_RATE)
        edges = np.geomspace(40, 16000, AUDIO_BANDS + 1)
        band_idx = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in zip(edges[:-1], edges[1:])]
        window = np.hanning(AUDIO_BLOCK)
        peaks = np.full(AUDIO_BANDS, 1e-3)
        level_peak = 1e-3
        smooth = np.zeros(AUDIO_BANDS)
        bass_avg = 0.0
        last_check = time.time()

        with mic.recorder(samplerate=AUDIO_RATE, blocksize=AUDIO_BLOCK) as rec:
            while self.active:
                data = rec.record(numframes=AUDIO_BLOCK)
                mono = data.mean(axis=1) if data.ndim > 1 else data
                rms = float(np.sqrt(np.mean(mono ** 2)))
                spec = np.abs(np.fft.rfft(mono * window))
                energy = np.array([spec[i].mean() if len(i) else 0.0 for i in band_idx])

                # Ganho automático: cada faixa é comparada ao próprio pico recente
                peaks = np.maximum(energy, peaks * 0.997)
                level_peak = max(rms, level_peak * 0.997)
                silent = rms < 1e-4
                norm = np.zeros(AUDIO_BANDS) if silent else np.clip(energy / peaks, 0, 1) ** 1.5
                # Sobe rápido, desce devagar
                smooth = np.maximum(norm, smooth * 0.82)
                self.bands = smooth.tolist()
                lvl = 0.0 if silent else min(1.0, rms / level_peak) ** 1.3
                self.level = max(lvl, self.level * 0.85)

                bass = float(energy[:3].mean())
                if not silent and bass > bass_avg * 1.45 and bass > peaks[:3].mean() * 0.35:
                    if self.beat < 0.5:
                        self.beat_count += 1
                    self.beat = 1.0
                else:
                    self.beat *= 0.86
                bass_avg = bass_avg * 0.95 + bass * 0.05

                # Se a saída padrão do Windows mudar (ex.: fone → caixa), reabre a captura
                if time.time() - last_check > 3:
                    last_check = time.time()
                    if sc.default_speaker().name != speaker.name:
                        return


class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.cfg = load_config()
        self.client = None
        self.extras = None  # dispositivos controlados fora do OpenRGB (ex.: GPU Galax via I2C)
        self.status = "Conectando ao OpenRGB..."
        self.needs_setup = True
        self.last_sent = {}
        self.running = True
        self.audio = AudioMeter()
        self.audio.active = self.cfg["effect"] in AUDIO_EFFECTS

    # ---------- conexão ----------
    def connect(self):
        launched = False
        deadline = time.time() + 60
        while self.running and time.time() < deadline:
            try:
                self.client = OpenRGBClient("127.0.0.1", 6742, "LED Sync")
                break
            except OSError:
                if not launched and os.path.exists(OPENRGB_EXE):
                    self.status = "Iniciando o OpenRGB..."
                    subprocess.Popen([OPENRGB_EXE, "--server", "--startminimized"])
                    launched = True
                time.sleep(1)
        if self.client is None:
            self.status = "OpenRGB não encontrado. Verifique se está instalado."
            return False
        # O servidor aceita conexões antes de terminar a detecção: espera a lista estabilizar
        self.status = "Detectando dispositivos..."
        stable_since, count = time.time(), -1
        while time.time() - stable_since < 6 and time.time() < deadline + 40:
            self.client.update()
            if len(self.client.devices) != count:
                count, stable_since = len(self.client.devices), time.time()
            time.sleep(1)
        if self.extras is None:
            self.extras = galax_gpu.detect_devices()
        self.status = "Conectado"
        self.needs_setup = True
        return True

    def setup(self):
        """Aplica tamanhos de zonas ARGB e coloca os dispositivos no modo certo."""
        for dev in self.client.devices:
            for zone in dev.zones:
                key = f"{dev.name}|{zone.name}"
                size = self.cfg["zone_sizes"].get(key)
                if size is not None and len(zone.leds) != size:
                    try:
                        zone.resize(int(size))
                    except Exception:
                        pass
        self.client.update()
        native = self.cfg["effect"] == "native"
        for dev in self.enabled_devices():
            try:
                if native:
                    self.apply_native(dev)
                else:
                    dev.set_mode("direct")
            except Exception:
                pass
        self.last_sent.clear()
        self.needs_setup = False

    def apply_native(self, dev):
        names = [m.name.lower() for m in dev.modes]
        color = RGBColor(*self.scaled(hex_to_rgb(self.cfg["color"])))
        if "static" in names:
            dev.set_mode("static")
        dev.set_color(color)
        if hasattr(dev, "save_hardware"):
            dev.save_hardware()

    def all_devices(self):
        return list(self.client.devices) + list(self.extras or [])

    def enabled_devices(self):
        return [d for d in self.all_devices() if d.name not in self.cfg["disabled"]]

    # ---------- efeitos ----------
    def scaled(self, rgb):
        k = self.cfg["brightness"] / 100
        return tuple(max(0, min(255, int(c * k))) for c in rgb)

    def color_fn(self, t):
        eff = self.cfg["effect"]
        c1 = hex_to_rgb(self.cfg["color"])
        c2 = hex_to_rgb(self.cfg["color2"])
        speed = 0.05 + self.cfg["speed"] / 100 * 1.2
        if eff == "static":
            return lambda pos: c1
        if eff == "breathing":
            k = 0.05 + 0.95 * (0.5 - 0.5 * math.cos(2 * math.pi * t * speed * 0.5))
            col = tuple(c * k for c in c1)
            return lambda pos: col
        if eff == "spectrum":
            col = hsv(t * speed * 0.2)
            return lambda pos: col
        if eff == "rainbow":
            return lambda pos: hsv(t * speed * 0.3 + pos)
        if eff == "gradient":
            def grad(pos):
                m = 0.5 + 0.5 * math.sin(2 * math.pi * (pos - t * speed * 0.3))
                return tuple(a + (b - a) * m for a, b in zip(c1, c2))
            return grad
        if eff == "audio_pulse":
            # Cor 1 pulsando com o volume; nas batidas do grave puxa para a cor 2
            k = 0.04 + 0.96 * self.audio.level
            b = self.audio.beat
            col = tuple((a + (c - a) * b) * k for a, c in zip(c1, c2))
            return lambda pos: col
        if eff == "audio_color":
            # Todos na mesma cor, que muda a cada batida; brilho segue o volume
            k = 0.04 + 0.96 * self.audio.level
            hue = self.audio.beat_count * 0.11 + t * 0.01
            col = tuple(c * k for c in hsv(hue))
            return lambda pos: col
        if eff == "audio_spectrum":
            # Cada dispositivo mostra o espectro inteiro: grave (vermelho) → agudo (roxo)
            bands = self.audio.bands
            def spec(pos):
                i = min(AUDIO_BANDS - 1, int(pos * AUDIO_BANDS))
                k = 0.03 + 0.97 * bands[i]
                return tuple(c * k for c in hsv(pos * 0.8))
            return spec
        return lambda pos: (0, 0, 0)

    def render(self, now):
        devices = [d for d in self.enabled_devices() if d.leds]
        total = sum(len(d.leds) for d in devices) or 1
        fn = self.color_fn(now)
        offset = 0
        for dev in devices:
            n = len(dev.leds)
            if self.cfg["effect"] == "audio_spectrum":
                positions = [i / n + 0.5 / n for i in range(n)]
            else:
                positions = [(offset + i) / total for i in range(n)]
            colors = [RGBColor(*self.scaled(fn(p))) for p in positions]
            offset += n
            key = (dev.name, dev.id)
            last_t, last_c = self.last_sent.get(key, (0, None))
            interval = SLOW_INTERVAL if dev.type in SLOW_TYPES else 0
            if now - last_t < interval:
                continue
            if colors == last_c and now - last_t < RESEND_INTERVAL:
                continue
            dev.set_colors(colors, fast=True)
            self.last_sent[key] = (now, colors)

    def run(self):
        while self.running:
            if self.client is None and not self.connect():
                time.sleep(5)
                continue
            try:
                with self.lock:
                    if self.needs_setup:
                        self.setup()
                    if self.cfg["effect"] != "native":
                        self.render(time.time())
            except (OSError, ConnectionError) as e:
                self.status = f"Conexão perdida ({e}). Reconectando..."
                self.client = None
                continue
            time.sleep(1 / FPS)

    # ---------- API ----------
    def state(self):
        with self.lock:
            devices = []
            if self.client:
                for d in self.all_devices():
                    devices.append({
                        "name": d.name,
                        "type": DeviceType(d.type).name.lower(),
                        "enabled": d.name not in self.cfg["disabled"],
                        "leds": len(d.leds),
                        "zones": [{
                            "name": z.name,
                            "leds": len(z.leds),
                            "resizable": is_addressable(z),
                        } for z in d.zones],
                    })
            audio = None
            if self.audio.active:
                audio = {"device": self.audio.device, "error": self.audio.error,
                         "level": round(self.audio.level, 3)}
            return {"status": self.status, "config": self.cfg, "devices": devices,
                    "effects": EFFECTS, "audio": audio}

    def update_config(self, patch):
        with self.lock:
            prev_effect = self.cfg["effect"]
            prev_disabled = list(self.cfg["disabled"])
            for k in ("effect", "color", "color2", "brightness", "speed", "disabled"):
                if k in patch:
                    self.cfg[k] = patch[k]
            if self.cfg["effect"] not in EFFECTS:
                self.cfg["effect"] = "rainbow"
            self.audio.active = self.cfg["effect"] in AUDIO_EFFECTS
            mode_changed = (prev_effect == "native") != (self.cfg["effect"] == "native")
            if mode_changed or prev_disabled != self.cfg["disabled"]:
                self.needs_setup = True
            elif self.cfg["effect"] == "native" and self.client:
                for dev in self.enabled_devices():
                    try:
                        self.apply_native(dev)
                    except Exception:
                        pass
            save_config(self.cfg)

    def resize_zone(self, device, zone, size):
        with self.lock:
            self.cfg["zone_sizes"][f"{device}|{zone}"] = int(size)
            save_config(self.cfg)
            self.needs_setup = True

    def rescan(self):
        with self.lock:
            self.client = None
            self.status = "Reescaneando..."


engine = Engine()
tray_icon = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(INDEX_PATH, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self.send_json(engine.state())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send_json({"error": "json inválido"}, 400)
        if self.path == "/api/config":
            engine.update_config(data)
        elif self.path == "/api/resize":
            engine.resize_zone(data["device"], data["zone"], data["size"])
        elif self.path == "/api/rescan":
            engine.rescan()
        elif self.path == "/api/quit":
            self.send_json({"ok": True})
            if tray_icon:
                tray_icon.stop()
            shutdown()
            return
        else:
            return self.send_json({"error": "not found"}, 404)
        self.send_json(engine.state())


def open_window():
    url = f"http://127.0.0.1:{PORT}/"
    for edge in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(edge):
            subprocess.Popen([edge, f"--app={url}", "--window-size=980,820"])
            return
    webbrowser.open(url)


def shutdown():
    engine.running = False
    threading.Thread(target=server.shutdown, daemon=True).start()


def already_running():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


if __name__ == "__main__":
    headless = "--background" in sys.argv
    if already_running():
        open_window()
        sys.exit(0)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=engine.run, daemon=True).start()
    threading.Thread(target=engine.audio.run, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if not headless:
        threading.Timer(0.5, open_window).start()
    try:
        import tray
        tray_icon = tray.build_tray(engine, open_window, shutdown)
        tray_icon.run()  # bloqueia até "Encerrar"
    except ImportError:
        # Sem pystray: segue rodando só com a interface web
        while engine.running:
            time.sleep(1)
