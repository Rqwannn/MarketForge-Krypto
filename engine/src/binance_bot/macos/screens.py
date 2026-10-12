"""Area layar yang boleh dipakai jendela: tanpa menu bar dan Dock."""

from __future__ import annotations

from binance_bot.macos.window import Rect


def visible_areas() -> list[Rect]:
    """Area tiap layar, dalam koordinat yang sama dengan posisi jendela.

    AppKit memakai titik asal di kiri bawah layar utama; posisi jendela (System Events)
    memakai kiri atas. Layar pertama adalah layar utama (yang punya menu bar).
    """
    from AppKit import NSScreen

    screens = list(NSScreen.screens())
    if not screens:
        return []
    primary_height = screens[0].frame().size.height
    areas = []
    for screen in screens:
        visible = screen.visibleFrame()
        top = primary_height - visible.origin.y - visible.size.height
        areas.append(
            Rect(
                round(visible.origin.x),
                round(top),
                int(visible.size.width),
                int(visible.size.height),
            )
        )
    return areas
