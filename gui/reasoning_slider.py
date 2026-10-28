"""Compact gradient reasoning slider that fits the existing API form field."""

import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

from gui.theme import COLOR_BG_APP, FONT_BODY


class ReasoningSlider(tk.Canvas):
    LABELS = {"auto": "自动", "none": "关闭思考", "minimal": "极低",
              "low": "低", "medium": "中", "high": "高", "xhigh": "超高"}

    def __init__(self, parent, *, variable, values, font=FONT_BODY):
        self.variable = variable
        self.values = tuple(values)
        self._font = tkfont.Font(master=parent, font=font)
        self._focused = False
        self._dragging = False
        self._track_size = None
        # Match the borderless Combobox's requested height; the host adds its padding.
        super().__init__(parent, width=1, height=max(18, self._font.metrics("linespace")),
                         bg=COLOR_BG_APP, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=True)
        self.label_var = tk.StringVar(self)
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<FocusIn>", lambda _e: self._focus(True))
        self.bind("<FocusOut>", lambda _e: self._focus(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        for key, delta in (("Left", -1), ("Right", 1), ("Down", -1), ("Up", 1)):
            self.bind(f"<{key}>", lambda _e, step=delta: self._step(step))
        self.bind("<Home>", lambda _e: self._select(0))
        self.bind("<End>", lambda _e: self._select(len(self.values) - 1))
        self._trace = variable.trace_add("write", self._changed)
        self.bind("<Destroy>", self._dispose, add="+")
        self._changed()

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        values = options.pop("values", None)
        if values is not None:
            self.values = tuple(values)
            if not self.values:
                raise ValueError("At least one reasoning level is required")
            if self.get() not in self.values:
                self.variable.set("auto" if "auto" in self.values else self.values[0])
            self._changed()
        if isinstance(cnf, dict):
            cnf = None
        if options or values is None:
            return super().configure(cnf, **options)

    config = configure

    def cget(self, key):
        if key == "font":
            return str(self._font)
        if key == "values":
            return self.values
        return super().cget(key)

    def get(self):
        return self.variable.get()

    def _changed(self, *_args):
        self.label_var.set(self.LABELS.get(self.get(), "自动"))
        self.redraw()

    def _positions(self):
        width, height = self.winfo_width(), self.winfo_height()
        radius = min(max(1, height / 2 - 3), max(1, width / 2 - 3))
        start, end = radius + 3, width - radius - 3
        return tuple(start + max(0, end - start) * index / max(1, len(self.values) - 1)
                     for index in range(len(self.values)))

    def _build_track(self, width, height):
        scale = 3
        self._track_size = width, height
        size = width * scale, height * scale
        self._base = Image.new("RGBA", size, COLOR_BG_APP)
        center = height / 2
        track_height = max(4, min(24, height - 12))
        bounds = (2 * scale, (center - track_height / 2) * scale,
                  (width - 2) * scale, (center + track_height / 2) * scale)
        ImageDraw.Draw(self._base).rounded_rectangle(bounds, radius=track_height * scale / 2, fill="#E7E9F2")
        self._gradient = Image.new("RGBA", size)
        draw = ImageDraw.Draw(self._gradient)
        stops = ((71, 76, 204), (174, 132, 230), (111, 79, 210))
        for x in range(size[0]):
            position = x / max(1, size[0] - 1) * 2
            segment = min(1, int(position))
            fraction = position - segment
            color = tuple(round(stops[segment][i] * (1 - fraction) + stops[segment + 1][i] * fraction)
                          for i in range(3))
            draw.line((x, 0, x, size[1]), fill=(*color, 255))
        speckles = Image.new("RGBA", size)
        stars = ImageDraw.Draw(speckles)
        for x, y, radius in ((.12, -.27, .75), (.19, .25, .9), (.29, -.14, .65),
                              (.38, .30, 1), (.40, -.26, .6), (.56, .21, .75),
                              (.67, -.18, .9), (.71, .30, .6), (.84, .05, .8)):
            cx, cy = width * x * scale, (center + track_height * y) * scale
            r = radius * scale
            stars.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 100))
        self._gradient = Image.alpha_composite(self._gradient, speckles)
        mask = Image.new("L", size)
        ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=track_height * scale / 2, fill=255)
        self._gradient.putalpha(mask)

    def redraw(self):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 8 or height < 8:
            return
        if self._track_size != (width, height):
            self._build_track(width, height)
        scale = 3
        positions = self._positions()
        index = self.values.index(self.get()) if self.get() in self.values else 0
        x, y = positions[index], height / 2
        bitmap = self._base.copy()
        edge = max(1, round(x * scale))
        bitmap.alpha_composite(self._gradient.crop((0, 0, edge, height * scale)), (0, 0))
        draw = ImageDraw.Draw(bitmap)
        radius = min(height / 2 - 3, width / 2 - 3)
        if self._focused:
            draw.ellipse(((x - radius - 2) * scale, (y - radius - 2) * scale,
                          (x + radius + 2) * scale, (y + radius + 2) * scale), fill="#DDD6FE")
        draw.ellipse(((x - radius) * scale, (y - radius + 1) * scale,
                      (x + radius) * scale, (y + radius + 1) * scale), fill="#D7D4E6")
        draw.ellipse(((x - radius) * scale, (y - radius) * scale,
                      (x + radius) * scale, (y + radius) * scale), fill="#FFFFFF", outline="#E5E1F0", width=scale)
        self._image = ImageTk.PhotoImage(bitmap.resize((width, height), Image.Resampling.LANCZOS), master=self)
        self.delete("all")
        self.create_image(0, 0, image=self._image, anchor="nw")

    def _focus(self, focused):
        self._focused = focused
        self.redraw()

    def _select(self, index):
        self.variable.set(self.values[max(0, min(len(self.values) - 1, index))])
        return "break"

    def _step(self, delta):
        current = self.values.index(self.get()) if self.get() in self.values else 0
        return self._select(current + delta)

    def _pick(self, x):
        positions = self._positions()
        self._select(min(range(len(positions)), key=lambda index: abs(positions[index] - x)))

    def _press(self, event):
        self.focus_set()
        self._dragging = True
        self._pick(event.x)
        return "break"

    def _drag(self, event):
        if self._dragging:
            self._pick(event.x)
        return "break"

    def _release(self, _event=None):
        self._dragging = False
        return "break"

    def _dispose(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self._trace)
