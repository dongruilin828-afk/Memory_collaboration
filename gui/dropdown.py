"""Rounded dropdown menus with native Combobox values and selection events."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from gui.theme import (
    COLOR_CARD, COLOR_BORDER, COLOR_GENERATION_ACCENT,
    COLOR_TEXT_PRIMARY, FONT_BODY, FONT_BODY_BOLD,
)


class RoundedCombobox(ttk.Combobox):
    """Readonly selector whose popup shares the desktop app's visual language."""

    def __init__(self, parent, **kwargs):
        self._popup = None
        super().__init__(parent, **kwargs)
        self.configure(cursor="hand2")
        self.bind("<ButtonPress-1>", self._toggle)
        self.bind("<ButtonRelease-1>", lambda _e: "break")
        for key in ("<Down>", "<Up>", "<Return>", "<space>", "<F4>", "<Alt-Down>"):
            self.bind(key, self._open_key)
        self.bind("<Escape>", self._escape)
        self.bind("<Destroy>", self._destroyed, add="+")
        self.bind("<Unmap>", lambda _e: self.close_dropdown(), add="+")

    @property
    def popup(self):
        return self._popup

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        if self._popup is not None and any(key in options for key in ("values", "state", "textvariable")):
            self.close_dropdown()
        return super().configure(cnf, **kwargs)

    config = configure

    def state(self, statespec=None):
        if statespec and "disabled" in statespec:
            self.close_dropdown()
        return super().state(statespec)

    def _toggle(self, _event=None):
        if self._popup is None:
            self.open_dropdown()
        else:
            self.close_dropdown(restore_focus=True)
        return "break"

    def _open_key(self, _event=None):
        self.open_dropdown()
        return "break"

    def _escape(self, _event=None):
        if self._popup is not None:
            self.close_dropdown(restore_focus=True)
            return "break"

    def open_dropdown(self):
        if self._popup is not None or self.instate(["disabled"]) or not self.winfo_viewable():
            return
        values = tuple(self.cget("values"))
        if not values:
            return
        self.focus_set()
        self._popup = _DropdownPopup(self, values)
        self.state(["pressed"])
        self._popup.show()
        self.event_generate("<<DropdownOpened>>")

    def close_dropdown(self, restore_focus=False):
        popup, self._popup = self._popup, None
        if popup is None:
            return
        popup.dismiss()
        if self.winfo_exists():
            self.state(["!pressed"])
            if restore_focus and self.winfo_viewable():
                self.focus_set()
            self.event_generate("<<DropdownClosed>>")

    def _destroyed(self, event):
        if event.widget is self:
            self.close_dropdown()


class _DropdownHost:
    """One set of lifecycle bindings per owner, retained until that owner is destroyed."""

    def __init__(self, owner):
        self.owner = owner
        self.popup = None
        for sequence in ("<Configure>", "<Unmap>", "<Destroy>"):
            owner.bind(sequence, self._changed, add="+")

    def _changed(self, event):
        if event.widget is self.owner and self.popup is not None:
            self.popup.combo.close_dropdown()


class _DropdownPopup(tk.Toplevel):
    def __init__(self, combo, values):
        self.combo = combo
        self.values = values
        self.owner = combo.winfo_toplevel()
        super().__init__(self.owner)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(self.owner)
        self.attributes("-alpha", self.owner.attributes("-alpha"))
        if not hasattr(self.owner, "_rounded_dropdown_host"):
            self.owner._rounded_dropdown_host = _DropdownHost(self.owner)
        self._host = self.owner._rounded_dropdown_host
        if self._host.popup is not None:
            self._host.popup.combo.close_dropdown()
        self._previous_grab = self.grab_current()
        self._previous_grab_status = self._previous_grab.grab_status() if self._previous_grab else None
        self._host.popup = self
        self._focus_after = None
        self._dismissed = False
        self._font = tkfont.Font(master=self, font=FONT_BODY)
        self._selected_font = tkfont.Font(master=self, font=FONT_BODY_BOLD)
        self.padding = 8
        self.row_height = max(38, self._font.metrics("linespace") + 20)
        self.selected_index = combo.current()
        self.active_index = max(0, self.selected_index)
        self.first_index = 0
        self._background = "#FAFAFC"
        if self.tk.call("tk", "windowingsystem") == "win32":
            # A near-white transparency key avoids dark fringes when smoothing corners.
            self.attributes("-transparentcolor", self._background)
        self.configure(bg=self._background)
        self.canvas = tk.Canvas(self, bg=self._background, highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<ButtonPress-1>", self._click)
        self.bind("<ButtonPress-1>", self._outside_click)
        self.bind("<Escape>", self._escape)
        self.bind("<Up>", lambda _e: self.move(-1))
        self.bind("<Down>", lambda _e: self.move(1))
        self.bind("<Home>", lambda _e: self._jump(0))
        self.bind("<End>", lambda _e: self._jump(len(self.values) - 1))
        for key in ("<Return>", "<space>"):
            self.bind(key, lambda _e: self.choose(self.active_index))
        self.bind("<Tab>", lambda _e: self._traverse(False))
        self.bind("<Shift-Tab>", lambda _e: self._traverse(True))
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda _e: self._scroll(-1))
        self.bind("<Button-5>", lambda _e: self._scroll(1))

    def show(self):
        # The surrounding input surface is the visual anchor, including its padding.
        anchor = getattr(self.combo, "popup_anchor", self.combo)
        screen_x, screen_y = self.winfo_vrootx(), self.winfo_vrooty()
        screen_width, screen_height = self.winfo_vrootwidth(), self.winfo_vrootheight()
        left = screen_x + 8
        top = screen_y + 8
        right = screen_x + screen_width - 8
        bottom = screen_y + screen_height - 48
        preferred_height = min(7, len(self.values)) * self.row_height + self.padding * 2
        below_y = anchor.winfo_rooty() + anchor.winfo_height() + 5
        above = anchor.winfo_rooty() - top - 5
        below = bottom - below_y
        open_below = below >= preferred_height or below >= above
        room = max(1, below if open_below else above)
        self.visible_rows = max(1, min(7, len(self.values), (room - self.padding * 2) // self.row_height))
        height = self.visible_rows * self.row_height + self.padding * 2
        width = min(right - left, max(anchor.winfo_width(), self._font.measure(max(self.values, key=len)) + 64))
        x = max(left, min(anchor.winfo_rootx(), right - width))
        y = below_y if open_below else anchor.winfo_rooty() - height - 5
        y = max(top, min(y, bottom - height))
        self._width, self._height = width, height
        self.geometry(f"{width}x{height}{x:+d}{y:+d}")
        self._ensure_visible()
        self._draw()
        self.deiconify()
        self.lift()
        self.grab_set()
        self.focus_set()

    def _draw(self):
        width, height, scale = self._width, self._height, 3
        bitmap = Image.new("RGB", (width * scale, height * scale), self._background)
        draw = ImageDraw.Draw(bitmap)
        draw.rounded_rectangle((scale, 2 * scale, (width - 1) * scale, (height - 1) * scale),
                               radius=13 * scale, fill="#E8E5EF")
        draw.rounded_rectangle((scale, scale, (width - 1) * scale, (height - 3) * scale),
                               radius=12 * scale, fill=COLOR_CARD, outline=COLOR_BORDER, width=scale)
        for row in range(self.visible_rows):
            index = self.first_index + row
            y = self.padding + row * self.row_height
            selected = index == self.selected_index
            active = index == self.active_index
            if selected or active:
                fill = "#EDE9FE" if selected and active else ("#F5F3FF" if selected else "#F1F4F9")
                draw.rounded_rectangle((6 * scale, y * scale, (width - 6) * scale, (y + self.row_height - 2) * scale),
                                       radius=8 * scale, fill=fill)
            if selected:
                middle = y + self.row_height / 2 - 1
                draw.line([((width - 30) * scale, middle * scale),
                           ((width - 26) * scale, (middle + 4) * scale),
                           ((width - 19) * scale, (middle - 4) * scale)],
                          fill=COLOR_GENERATION_ACCENT, width=5, joint="curve")
        if self.visible_rows < len(self.values):
            track_height = height - self.padding * 2
            thumb_height = max(12, track_height * self.visible_rows / len(self.values))
            offset = (track_height - thumb_height) * self.first_index / max(1, len(self.values) - self.visible_rows)
            draw.rounded_rectangle(((width - 5) * scale, (self.padding + offset) * scale,
                                    (width - 3) * scale, (self.padding + offset + thumb_height) * scale),
                                   radius=scale, fill="#CBD5E1")
        self._image = ImageTk.PhotoImage(bitmap.resize((width, height), Image.Resampling.LANCZOS), master=self)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._image, anchor="nw")
        for row in range(self.visible_rows):
            index = self.first_index + row
            selected = index == self.selected_index
            self.canvas.create_text(18, self.padding + row * self.row_height + self.row_height / 2 - 1,
                                    text=self.values[index], anchor="w",
                                    font=self._selected_font if selected else self._font,
                                    fill=COLOR_GENERATION_ACCENT if selected else COLOR_TEXT_PRIMARY)

    def _index_at(self, event):
        x, y = event.x_root - self.winfo_rootx(), event.y_root - self.winfo_rooty()
        row = int((y - self.padding) // self.row_height)
        if 5 <= x < self._width - 5 and 0 <= row < self.visible_rows:
            return self.first_index + row
        return None

    def _hover(self, event):
        index = self._index_at(event)
        if index is not None and index != self.active_index:
            self.active_index = index
            self._draw()

    def _leave(self, _event=None):
        self.active_index = -1
        self._draw()

    def _click(self, event):
        index = self._index_at(event)
        if index is not None:
            self.choose(index)
        else:
            self._outside_click(event)
        return "break"

    def _outside_click(self, event):
        x, y = event.x_root, event.y_root
        if not (self.winfo_rootx() <= x < self.winfo_rootx() + self._width and
                self.winfo_rooty() <= y < self.winfo_rooty() + self._height):
            self.combo.close_dropdown()
        return "break"

    def _ensure_visible(self):
        self.first_index = min(self.first_index, self.active_index)
        self.first_index = max(self.first_index, self.active_index - self.visible_rows + 1, 0)

    def move(self, delta):
        self.active_index = max(0, min(len(self.values) - 1, self.active_index + delta))
        self._ensure_visible()
        self._draw()
        return "break"

    def _jump(self, index):
        self.active_index = index
        self._ensure_visible()
        self._draw()
        return "break"

    def choose(self, index):
        if not 0 <= index < len(self.values):
            return "break"
        combo = self.combo
        value = self.values[index]
        combo.close_dropdown(restore_focus=True)
        if combo.winfo_exists() and not combo.instate(["disabled"]):
            combo.set(value)
            combo.event_generate("<<ComboboxSelected>>")
        return "break"

    def _escape(self, _event=None):
        self.combo.close_dropdown(restore_focus=True)
        return "break"

    def _traverse(self, backwards):
        target = self.combo.tk_focusPrev() if backwards else self.combo.tk_focusNext()
        self.combo.close_dropdown()
        if target:
            target.focus_set()
        return "break"

    def _wheel(self, event):
        return self._scroll(-1 if event.delta > 0 else (1 if event.delta < 0 else 0))

    def _scroll(self, delta):
        self.first_index = max(0, min(len(self.values) - self.visible_rows, self.first_index + delta))
        self._draw()
        return "break"

    def _focus_out(self, _event=None):
        if self._focus_after is None:
            self._focus_after = self.after_idle(self._check_focus)

    def _check_focus(self):
        self._focus_after = None
        focus = self.focus_displayof()
        if focus is None or focus.winfo_toplevel() is not self:
            self.combo.close_dropdown()

    def dismiss(self):
        if self._dismissed:
            return
        self._dismissed = True
        if self._focus_after is not None:
            self.after_cancel(self._focus_after)
        if self._host.popup is self:
            self._host.popup = None
        if self.grab_current() is self:
            self.grab_release()
        previous = self._previous_grab
        if previous is not None and previous.winfo_exists() and previous.winfo_viewable():
            if self._previous_grab_status == "global":
                previous.grab_set_global()
            else:
                previous.grab_set()
        self.destroy()
