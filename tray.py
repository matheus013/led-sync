# SPDX-License-Identifier: GPL-2.0-or-later
"""Ícone do LED Sync na bandeja do Windows (perto do relógio)."""
import pystray
from PIL import Image, ImageDraw

EFFECT_LABELS = {
    "static": "Estático",
    "breathing": "Respiração",
    "spectrum": "Espectro",
    "rainbow": "Arco-íris",
    "gradient": "Gradiente",
    "audio_pulse": "♪ Pulso",
    "audio_color": "♪ Batida",
    "audio_spectrum": "♪ Equalizador",
    "native": "Nativo (salvo no hardware)",
    "off": "Desligado",
}
COLORS = [
    ("Vermelho", "#ff0000"), ("Laranja", "#ff6a00"), ("Amarelo", "#ffd000"),
    ("Verde", "#00ff40"), ("Ciano", "#00ffd0"), ("Azul", "#0030ff"),
    ("Roxo", "#8a00ff"), ("Rosa", "#ff00c8"), ("Branco", "#ffffff"),
]
BRIGHTNESS = [100, 75, 50, 25]


def make_icon_image(size=64):
    """Anel com as cores do arco-íris."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    import colorsys
    steps = 72
    for i in range(steps):
        r, g, b = colorsys.hsv_to_rgb(i / steps, 1, 1)
        start = i * 360 / steps - 90
        draw.pieslice([2, 2, size - 2, size - 2], start, start + 360 / steps + 1,
                      fill=(int(r * 255), int(g * 255), int(b * 255), 255))
    inner = size * 0.28
    draw.ellipse([size / 2 - inner, size / 2 - inner, size / 2 + inner, size / 2 + inner], fill=(20, 22, 28, 255))
    return img


def build_tray(engine, open_window, shutdown):
    def set_cfg(patch):
        engine.update_config(patch)
        icon.update_menu()

    def effect_item(eff):
        return pystray.MenuItem(
            EFFECT_LABELS[eff],
            lambda: set_cfg({"effect": eff}),
            checked=lambda item: engine.cfg["effect"] == eff,
            radio=True,
        )

    def color_item(name, value):
        return pystray.MenuItem(
            name,
            lambda: set_cfg({"color": value}),
            checked=lambda item: engine.cfg["color"].lower() == value,
            radio=True,
        )

    def brightness_item(value):
        return pystray.MenuItem(
            f"{value}%",
            lambda: set_cfg({"brightness": value}),
            checked=lambda item: engine.cfg["brightness"] == value,
            radio=True,
        )

    def toggle_lights():
        if engine.cfg["effect"] == "off":
            set_cfg({"effect": engine.cfg.get("last_effect") or "rainbow"})
        else:
            engine.cfg["last_effect"] = engine.cfg["effect"]
            set_cfg({"effect": "off"})

    def device_item(name):
        def toggle():
            disabled = set(engine.cfg["disabled"])
            disabled.symmetric_difference_update({name})
            set_cfg({"disabled": sorted(disabled)})
        return pystray.MenuItem(name, toggle, checked=lambda item: name not in engine.cfg["disabled"])

    def devices_menu():
        names = [d["name"] for d in engine.state()["devices"]]
        if not names:
            return [pystray.MenuItem("Detectando...", None, enabled=False)]
        return [device_item(n) for n in names]

    def quit_app():
        icon.stop()
        shutdown()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir painel", lambda: open_window(), default=True),
        pystray.MenuItem(
            lambda item: "Ligar luzes" if engine.cfg["effect"] == "off" else "Desligar luzes",
            toggle_lights,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Efeito", pystray.Menu(*[effect_item(e) for e in EFFECT_LABELS])),
        pystray.MenuItem("Cor", pystray.Menu(*[color_item(n, v) for n, v in COLORS])),
        pystray.MenuItem("Brilho", pystray.Menu(*[brightness_item(v) for v in BRIGHTNESS])),
        pystray.MenuItem("Dispositivos", pystray.Menu(lambda: devices_menu())),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Encerrar LED Sync", quit_app),
    )
    icon = pystray.Icon("LEDSync", make_icon_image(), "LED Sync", menu)
    return icon
