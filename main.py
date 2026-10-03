"""Free Offline SMS Sender - sends bulk SMS from the phone's own SIM credit. No internet needed."""
import math
import re
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.utils import platform

ANDROID = platform == "android"
if ANDROID:
    from jnius import autoclass
    from android.permissions import Permission, check_permission, request_permissions


def normalize(tok):
    """Return a clean phone number, or None if the text is not a number (names are skipped)."""
    if not re.fullmatch(r"\+?[\d\-\(\)\.]+", tok):
        return None
    plus = tok.startswith("+")
    d = re.sub(r"\D", "", tok)
    if len(d) == 9 and not plus:      # leading 0 lost (Excel), e.g. 241234567 -> 0241234567
        d = "0" + d
    return ("+" if plus else "") + d if 9 <= len(d) <= 15 else None


def parse_numbers(text):
    seen, out = set(), []
    for tok in re.split(r"[,\s;]+", text):
        n = normalize(tok) if tok else None
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def parts_of(m):
    single, multi = (70, 67) if any(ord(c) > 127 for c in m) else (160, 153)
    return 1 if len(m) <= single else math.ceil(len(m) / multi)


def send_sms(number, text):
    if not ANDROID:
        print("TEST (not on a phone):", number, text)
        return
    mgr = autoclass("android.telephony.SmsManager").getDefault()
    parts = mgr.divideMessage(text)
    if parts.size() > 1:
        mgr.sendMultipartTextMessage(number, None, parts, None, None)
    else:
        mgr.sendTextMessage(number, None, text, None, None)


class Root(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=10, spacing=8, **kw)
        self.stop = False
        self.numbers = TextInput(hint_text="Paste phone numbers here (commas, spaces or new lines)", size_hint_y=0.55)
        self.add_widget(self.numbers)
        row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        b1, b2 = Button(text="Load file (CSV/TXT)"), Button(text="Clear numbers")
        b1.bind(on_release=self.pick)
        b2.bind(on_release=lambda *_: setattr(self.numbers, "text", ""))
        row.add_widget(b1)
        row.add_widget(b2)
        self.add_widget(row)
        self.msg = TextInput(hint_text="Type your message", size_hint_y=0.45)
        self.add_widget(self.msg)
        row2 = BoxLayout(size_hint_y=None, height=44, spacing=8)
        self.avail = TextInput(hint_text="SMS I have (optional)", input_filter="int", multiline=False)
        self.delay = TextInput(text="3", hint_text="Seconds between texts", input_filter="float", multiline=False)
        row2.add_widget(self.avail)
        row2.add_widget(self.delay)
        self.add_widget(row2)
        self.info = Label(text="", size_hint_y=None, height=50)
        self.add_widget(self.info)
        row3 = BoxLayout(size_hint_y=None, height=52, spacing=8)
        self.go = Button(text="SEND", background_color=(0.1, 0.6, 0.25, 1))
        stop = Button(text="STOP", background_color=(0.8, 0.15, 0.1, 1))
        self.go.bind(on_release=self.start)
        stop.bind(on_release=lambda *_: setattr(self, "stop", True))
        row3.add_widget(self.go)
        row3.add_widget(stop)
        self.add_widget(row3)
        self.status = Label(text="Free app. Messages are paid from your own SMS credit / airtime.", size_hint_y=None, height=50)
        self.add_widget(self.status)
        self.numbers.bind(text=self.refresh)
        self.msg.bind(text=self.refresh)
        self.refresh()
        if ANDROID:
            request_permissions([Permission.SEND_SMS])

    def say(self, t):
        Clock.schedule_once(lambda dt: setattr(self.status, "text", t))

    def refresh(self, *_):
        n, p = len(parse_numbers(self.numbers.text)), parts_of(self.msg.text) if self.msg.text.strip() else 0
        self.info.text = f"{n} numbers | {p} SMS each | {n * p} SMS will be used from your credit"

    def pick(self, *_):
        try:
            from plyer import filechooser
            filechooser.open_file(on_selection=lambda s: Clock.schedule_once(lambda dt: self.loaded(s)), filters=["*.csv", "*.txt"])
        except Exception:
            self.say("File picker not available. Please paste the numbers instead.")

    def loaded(self, sel):
        if not sel:
            return
        try:
            with open(sel[0], encoding="utf-8-sig", errors="ignore") as f:
                self.numbers.text = (self.numbers.text + "\n" + f.read()).strip()
        except Exception:
            self.say("Could not read that file. Please paste the numbers instead.")

    def start(self, *_):
        nums, msg = parse_numbers(self.numbers.text), self.msg.text.strip()
        if not nums or not msg:
            return self.say("Add numbers and type a message first.")
        if ANDROID and not check_permission(Permission.SEND_SMS):
            request_permissions([Permission.SEND_SMS])
            return self.say("Tap ALLOW for SMS permission, then press SEND again.")
        p = parts_of(msg)
        if self.avail.text.strip() and int(self.avail.text) // p < len(nums):
            nums = nums[: int(self.avail.text) // p]
            if not nums:
                return self.say("You do not have enough SMS for even one number.")
        try:
            delay = max(1.0, float(self.delay.text or 3))
        except ValueError:
            delay = 3.0
        box = BoxLayout(orientation="vertical", spacing=10, padding=10)
        box.add_widget(Label(text=f"Send to {len(nums)} numbers?\nThis uses about {len(nums) * p} SMS from your own credit."))
        yn = BoxLayout(size_hint_y=None, height=50, spacing=10)
        yes, no = Button(text="Yes, send"), Button(text="Cancel")
        yn.add_widget(yes)
        yn.add_widget(no)
        box.add_widget(yn)
        pop = Popup(title="Confirm", content=box, size_hint=(0.9, 0.4))
        no.bind(on_release=pop.dismiss)
        yes.bind(on_release=lambda *_: (pop.dismiss(), self.begin(nums, msg, delay)))
        pop.open()

    def begin(self, nums, msg, delay):
        self.stop = False
        self.go.disabled = True
        threading.Thread(target=self.run, args=(nums, msg, delay), daemon=True).start()

    def run(self, nums, msg, delay):
        sent = failed = 0
        for n in nums:
            if self.stop:
                break
            try:
                send_sms(n, msg)
                sent += 1
            except Exception:
                failed += 1
            self.say(f"Handed to phone: {sent} of {len(nums)}  |  errors {failed}")
            time.sleep(delay)
        self.say(f"Finished. {sent} sent to your phone's SMS system, {failed} errors." + (" (stopped)" if self.stop else ""))
        Clock.schedule_once(lambda dt: setattr(self.go, "disabled", False))


class SMSApp(App):
    def build(self):
        return Root()


if __name__ == "__main__":
    SMSApp().run()
