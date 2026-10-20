import csv
import hashlib
import os
import threading
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = "tel-veren"
BASE = "https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents" % PROJECT
DOC_PREFIX = "projects/%s/databases/(default)/documents/" % PROJECT
GROUPS = ["5", "9", "13", "14", "17", "18", "22", "23", "25", "71"]
MAX_USERS = 20
DATE_FMT = "%d.%m.%Y"

BG = (0.03, 0.03, 0.04, 1)
CARD = (0.11, 0.11, 0.13, 1)
CARD2 = (0.18, 0.18, 0.21, 1)
PINK = (0.996, 0.173, 0.333, 1)
CYAN = (0.145, 0.957, 0.933, 1)
GREEN = (0.19, 0.82, 0.55, 1)
TEXT = (1, 1, 1, 1)
MUTED = (0.62, 0.62, 0.67, 1)


# ---------- Firestore (REST) ----------

def enc(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    return {"stringValue": str(v)}


def dec(v):
    if "integerValue" in v:
        return int(v["integerValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    return v.get("stringValue", "")


def fields_of(data):
    return {k: enc(v) for k, v in data.items()}


def doc_data(doc):
    out = {k: dec(v) for k, v in doc.get("fields", {}).items()}
    out["_id"] = doc["name"].split("/")[-1]
    return out


class Cloud:
    def __init__(self):
        self.s = requests.Session()

    def get(self, path):
        r = self.s.get(BASE + "/" + path, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return doc_data(r.json())

    def list(self, path):
        out, token = [], None
        while True:
            params = {"pageSize": 300}
            if token:
                params["pageToken"] = token
            r = self.s.get(BASE + "/" + path, params=params, timeout=20)
            if r.status_code == 404:
                return out
            r.raise_for_status()
            data = r.json()
            for doc in data.get("documents", []):
                out.append(doc_data(doc))
            token = data.get("nextPageToken")
            if not token:
                return out

    def set(self, path, data):
        # yalnız göndərilən sahələr yenilənir, qalanları qalır
        params = [("updateMask.fieldPaths", k) for k in data]
        r = self.s.patch(BASE + "/" + path, params=params,
                         json={"fields": fields_of(data)}, timeout=20)
        r.raise_for_status()

    def delete(self, path):
        r = self.s.delete(BASE + "/" + path, timeout=20)
        if r.status_code != 404:
            r.raise_for_status()

    def seed(self, docs):
        for i in range(0, len(docs), 300):
            writes = []
            for path, data in docs[i:i + 300]:
                writes.append({"update": {"name": DOC_PREFIX + path,
                                          "fields": fields_of(data)}})
            r = self.s.post(BASE + ":batchWrite", json={"writes": writes}, timeout=60)
            r.raise_for_status()


CLOUD = Cloud()


def bg(work, done=None):
    # şəbəkə işi arxa planda gedir, ekran donmur
    def run():
        result, err = None, None
        try:
            result = work()
        except Exception as e:
            err = e

        def finish(dt):
            if err is not None:
                info("Xəta", "İnternet və ya server problemi:\n%s" % err)
            elif done:
                done(result)

        Clock.schedule_once(finish, 0)

    threading.Thread(target=run, daemon=True).start()


# ---------- yardımçılar ----------

def today_key():
    return datetime.now().strftime("%Y-%m-%d")


def show_day(key):
    y, m, d = key.split("-")
    return "%s.%s.%s" % (d, m, y)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def info(title, text):
    Popup(title=title, title_color=CYAN, separator_color=PINK,
          content=Label(text=text, color=TEXT),
          size_hint=(0.85, 0.35)).open()


def lbl(text, **kw):
    kw.setdefault("color", TEXT)
    return Label(text=text, **kw)


def wrap(widget):
    widget.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
    return widget


def allowed_groups(user):
    if user["is_admin"] or user["groups"] == "*":
        return GROUPS
    return [g for g in user["groups"].split(",") if g]


def seed_docs():
    docs = []
    with open(os.path.join(HERE, "trainees.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n = int(row["number"])
            docs.append(("trainees/k%d" % n, {
                "number": n, "name": row["name"], "grp": row["group"],
                "last_status": "", "last_reason": ""}))
    return docs


def make_docx(path, lines):
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(line)
        for line in lines)
    document = (head +
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + body + '</w:body></w:document>')
    content_types = (head +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')
    rels = (head +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)


# ---------- görünüş ----------

class RBtn(Button):
    def __init__(self, bg=CARD2, radius=16, **kw):
        kw.setdefault("color", TEXT)
        super().__init__(**kw)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self._base = bg
        with self.canvas.before:
            self._col = Color(*bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync, state=self._paint)

    def _sync(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _paint(self, *a):
        if self.state == "down":
            b = self._base
            self._col.rgba = (b[0] * 0.75, b[1] * 0.75, b[2] * 0.75, 1)
        else:
            self._col.rgba = self._base


class RToggle(ToggleButton):
    def __init__(self, on=GREEN, off=CARD2, radius=14, **kw):
        kw.setdefault("color", TEXT)
        super().__init__(**kw)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self._on = on
        self._off = off
        with self.canvas.before:
            self._col = Color(*off)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync, state=self._paint)
        self._paint()

    def _sync(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _paint(self, *a):
        self._col.rgba = self._on if self.state == "down" else self._off


def btn(text, fn=None, bg=PINK, **kw):
    b = RBtn(text=text, bg=bg, **kw)
    if fn:
        b.bind(on_release=fn)
    return b


def field(hint, password=False):
    return TextInput(hint_text=hint, password=password, multiline=False,
                     size_hint_y=None, height=dp(48), foreground_color=TEXT,
                     hint_text_color=MUTED, background_normal="",
                     background_active="", background_color=CARD2,
                     cursor_color=CYAN, padding=[dp(14), dp(14)])


def panel(radius=18, **kw):
    box = BoxLayout(**kw)
    with box.canvas.before:
        Color(*CARD)
        rect = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(radius)])
    box.bind(pos=lambda w, p: setattr(rect, "pos", p),
             size=lambda w, s: setattr(rect, "size", s))
    return box


class BaseScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._move_bg, size=self._move_bg)

    def _move_bg(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size


# ---------- ekranlar ----------

class LoadingScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(28))
        box.add_widget(lbl("Tel verən və verməyən", font_size=dp(24), bold=True,
                           color=CYAN))
        box.add_widget(lbl("Məlumat yüklənir...", color=MUTED))
        self.add_widget(box)

    def start(self):
        bg(self.work, self.finish)

    def work(self):
        users = CLOUD.list("users")
        if not CLOUD.list("trainees"):
            CLOUD.seed(seed_docs())
        return len(users) > 0

    def finish(self, has_users):
        self.manager.current = "login" if has_users else "setup"


class SetupScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(28), spacing=dp(14))
        box.add_widget(lbl("İlk quraşdırma", font_size=dp(24), bold=True,
                           color=CYAN, size_hint_y=None, height=dp(40)))
        box.add_widget(lbl("Admin hesabı yaradın", color=MUTED,
                           size_hint_y=None, height=dp(28)))
        self.user_in = field("Admin istifadəçi adı")
        self.pwd_in = field("Şifrə (ən azı 4 simvol)", password=True)
        self.pwd2_in = field("Şifrəni təkrar yazın", password=True)
        box.add_widget(self.user_in)
        box.add_widget(self.pwd_in)
        box.add_widget(self.pwd2_in)
        box.add_widget(btn("Admin yarat", self.create, PINK,
                           size_hint_y=None, height=dp(52)))
        box.add_widget(lbl(""))
        self.add_widget(box)

    def create(self, *a):
        name = self.user_in.text.strip()
        pwd = self.pwd_in.text
        if not name or "/" in name or len(pwd) < 4:
            return info("Xəta", "Ad yazın (/ işarəsi olmadan) və ən azı 4 simvollu şifrə seçin")
        if pwd != self.pwd2_in.text:
            return info("Xəta", "Şifrələr uyğun gəlmir")

        def work():
            if CLOUD.get("users/%s" % name) is not None:
                return False
            CLOUD.set("users/%s" % name, {"pwd": sha(pwd), "is_admin": True, "groups": "*"})
            return True

        def done(ok):
            if not ok:
                return info("Xəta", "Bu ad artıq var")
            self.pwd_in.text = ""
            self.pwd2_in.text = ""
            self.manager.current = "login"

        bg(work, done)


class LoginScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(28), spacing=dp(14))
        logo = os.path.join(HERE, "assets", "logo.png")
        if os.path.exists(logo):
            box.add_widget(Image(source=logo, size_hint_y=0.45))
        box.add_widget(lbl("Tel verən və verməyən", font_size=dp(24), bold=True,
                           color=CYAN, size_hint_y=None, height=dp(44)))
        self.user_in = field("İstifadəçi adı")
        self.pwd_in = field("Şifrə", password=True)
        box.add_widget(self.user_in)
        box.add_widget(self.pwd_in)
        box.add_widget(btn("Daxil ol", self.login, PINK,
                           size_hint_y=None, height=dp(52)))
        box.add_widget(lbl(""))
        self.add_widget(box)

    def login(self, *a):
        app = App.get_running_app()
        name = self.user_in.text.strip()
        pwd = sha(self.pwd_in.text)
        if not name or "/" in name:
            return info("Xəta", "İstifadəçi adını yazın")

        def work():
            return CLOUD.get("users/%s" % name)

        def done(doc):
            if not doc or doc.get("pwd") != pwd:
                return info("Xəta", "İstifadəçi adı və ya şifrə yanlışdır")
            app.user = {"username": name,
                        "is_admin": bool(doc.get("is_admin")),
                        "groups": doc.get("groups", "*")}
            self.pwd_in.text = ""
            self.manager.current = "main"
            self.manager.get_screen("main").load()

        bg(work, done)


class MainScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.all = []
        self.by_id = {}
        self.pending = {}
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        self.header = lbl("", size_hint_y=None, height=dp(30), bold=True,
                          color=CYAN, halign="left")
        self.spinner = Spinner(size_hint_y=None, height=dp(46), background_normal="",
                               background_color=CARD2, color=TEXT)
        self.spinner.bind(text=lambda *a: self.build_list())
        self.list_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.list_box)
        bar = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        self.admin_btn = btn("Admin", lambda *a: self.open("admin"), CARD2)
        bar.add_widget(btn("Yadda saxla", self.save, GREEN))
        bar.add_widget(btn("Tarixçə", lambda *a: self.open("history"), CARD2))
        bar.add_widget(self.admin_btn)
        bar.add_widget(btn("Çıxış", self.logout, PINK))
        for w in (self.header, self.spinner, scroll, bar):
            box.add_widget(w)
        self.add_widget(box)

    def load(self):
        u = App.get_running_app().user
        groups = allowed_groups(u)
        self.pending = {}
        self.header.text = "Salam, %s · yüklənir..." % u["username"]
        self.spinner.values = groups
        self.spinner.text = groups[0]
        self.admin_btn.opacity = 1 if u["is_admin"] else 0
        self.admin_btn.disabled = not u["is_admin"]
        bg(lambda: CLOUD.list("trainees"), self.loaded)

    def loaded(self, trainees):
        self.all = sorted(trainees, key=lambda t: t["number"])
        self.by_id = {t["_id"]: t for t in self.all}
        self.header.text = "Salam, %s" % App.get_running_app().user["username"]
        self.build_list()

    def build_list(self):
        app = App.get_running_app()
        self.list_box.clear_widgets()
        group = self.spinner.text
        if not app.user or group not in allowed_groups(app.user):
            return
        for t in self.all:
            if t["grp"] == group:
                self.add_row(t)

    def add_row(self, t):
        app = App.get_running_app()
        tid = t["_id"]
        if tid in self.pending:
            status, reason = self.pending[tid]
        else:
            status = t.get("last_status") or None
            reason = t.get("last_reason") or ""

        card = panel(orientation="vertical", size_hint_y=None, height=dp(62),
                     padding=dp(8), spacing=dp(6))
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        top.add_widget(lbl(str(t["number"]), size_hint_x=0.12, bold=True, color=CYAN))
        top.add_widget(wrap(lbl(t["name"], halign="left", size_hint_x=0.4)))
        yes = RToggle(text="Bəli", group="t%s" % tid, on=GREEN, size_hint_x=0.16,
                      state="down" if status == "Bəli" else "normal")
        no = RToggle(text="Xeyr", group="t%s" % tid, on=PINK, size_hint_x=0.16,
                     state="down" if status == "Xeyr" else "normal")
        top.add_widget(yes)
        top.add_widget(no)
        if app.user["is_admin"]:
            top.add_widget(btn("Sil", lambda *a, tid=tid: self.delete_trainee(tid),
                               CARD2, size_hint_x=0.16))
        reason_in = field("Niyə telefonu verməyib?")
        reason_in.height = 0
        reason_in.opacity = 0
        reason_in.disabled = True
        if status == "Xeyr":
            reason_in.text = reason
        card.add_widget(top)
        card.add_widget(reason_in)

        def show_reason():
            shown = no.state == "down"
            reason_in.opacity = 1 if shown else 0
            reason_in.disabled = not shown
            reason_in.height = dp(48) if shown else 0
            card.height = dp(116) if shown else dp(62)

        def sync(*_):
            if yes.state == "down":
                self.pending[tid] = ("Bəli", "")
            elif no.state == "down":
                self.pending[tid] = ("Xeyr", reason_in.text.strip())
            show_reason()

        yes.bind(state=sync)
        no.bind(state=sync)
        reason_in.bind(text=sync)
        show_reason()
        self.list_box.add_widget(card)

    def save(self, *_):
        app = App.get_running_app()
        items = []
        for tid, (status, why) in self.pending.items():
            if status == "Xeyr" and not why:
                return info("Diqqət", "Xeyr seçilən hər kursant üçün səbəb yazın")
            t = self.by_id.get(tid)
            if t is None:
                continue
            if t.get("last_status") == status and (t.get("last_reason") or "") == why:
                continue
            items.append((dict(t), status, why))
        if not items:
            return info("Məlumat", "Dəyişiklik yoxdur")
        day = today_key()
        user = app.user["username"]

        def work():
            CLOUD.set("days/%s" % day, {"day": day})
            for t, status, why in items:
                CLOUD.set("days/%s/trainees/%s" % (day, t["_id"]), {
                    "number": t["number"], "name": t["name"], "grp": t["grp"],
                    "status": status, "reason": why, "saved_by": user, "edited": False})
                CLOUD.set("trainees/%s" % t["_id"], {
                    "last_status": status, "last_reason": why})
            return len(items)

        def done(n):
            for t, status, why in items:
                cached = self.by_id.get(t["_id"])
                if cached is not None:
                    cached["last_status"] = status
                    cached["last_reason"] = why
            self.pending = {}
            info("Yadda saxlandı",
                 "%d kursant bu günün (%s) tarixçəsinə əlavə olundu" % (n, show_day(day)))
            self.build_list()

        bg(work, done)

    def delete_trainee(self, tid):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        p = Popup(title="Silinsin?", title_color=CYAN, separator_color=PINK,
                  content=box, size_hint=(0.85, 0.35))
        box.add_widget(lbl("Kursant siyahıdan silinsin?\nTarixçə qalacaq."))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))

        def yes(*a):
            p.dismiss()

            def done(_):
                self.pending.pop(tid, None)
                self.all = [t for t in self.all if t["_id"] != tid]
                self.by_id.pop(tid, None)
                self.build_list()

            bg(lambda: CLOUD.delete("trainees/%s" % tid), done)

        row.add_widget(btn("Bəli, sil", yes, PINK))
        row.add_widget(btn("Xeyr", lambda *a: p.dismiss(), CARD2))
        box.add_widget(row)
        p.open()

    def open(self, name):
        self.manager.current = name
        self.manager.get_screen(name).load()

    def logout(self, *a):
        App.get_running_app().user = None
        self.pending = {}
        self.manager.current = "login"


class AdminScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.user_count = 0
        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        top = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        top.add_widget(btn("← Geri", lambda *a: setattr(self.manager, "current", "main"),
                           CARD2, size_hint_x=0.32))
        top.add_widget(lbl("Admin paneli", bold=True, color=CYAN, font_size=dp(18)))
        scroll = ScrollView()
        self.box = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=dp(4))
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        root.add_widget(top)
        root.add_widget(scroll)
        self.add_widget(root)

    def load(self):
        bg(lambda: CLOUD.list("users"), self.render)

    def render(self, users):
        app = App.get_running_app()
        self.user_count = len(users)
        self.box.clear_widgets()
        self.box.add_widget(lbl("İstifadəçilər (%d/%d)" % (len(users), MAX_USERS),
                                size_hint_y=None, height=dp(30), bold=True, color=CYAN))
        for u in users:
            row = panel(size_hint_y=None, height=dp(54), padding=dp(8), spacing=dp(8))
            tag = "  · admin" if u.get("is_admin") else ""
            row.add_widget(wrap(lbl(u["_id"] + tag, halign="left")))
            if u["_id"] != app.user["username"]:
                row.add_widget(btn("Sil", lambda *a, name=u["_id"]: self.del_user(name),
                                   PINK, size_hint_x=0.3))
            self.box.add_widget(row)

        self.box.add_widget(lbl("Yeni istifadəçi", size_hint_y=None, height=dp(30),
                                bold=True, color=CYAN))
        self.new_user = field("İstifadəçi adı")
        self.new_pwd = field("Şifrə", password=True)
        self.new_admin = RToggle(text="Admin olsun", on=GREEN, size_hint_y=None,
                                 height=dp(48))
        self.box.add_widget(self.new_user)
        self.box.add_widget(self.new_pwd)
        self.box.add_widget(self.new_admin)
        self.box.add_widget(lbl("Hansı qrupları görsün?", size_hint_y=None, height=dp(28),
                                color=MUTED))
        grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        self.all_groups = RToggle(text="Hamısı", on=GREEN, size_hint_y=None, height=dp(48))
        grid.add_widget(self.all_groups)
        self.group_toggles = {}
        for g in GROUPS:
            tb = RToggle(text=g, on=CYAN, size_hint_y=None, height=dp(48))
            self.group_toggles[g] = tb
            grid.add_widget(tb)
        self.box.add_widget(grid)
        self.box.add_widget(btn("İstifadəçi əlavə et", self.add_user, GREEN,
                                size_hint_y=None, height=dp(52)))

        self.box.add_widget(lbl("Yeni kursant", size_hint_y=None, height=dp(30),
                                bold=True, color=CYAN))
        self.new_trainee = field("Ad, soyad, ata adı")
        self.trainee_group = Spinner(text=GROUPS[0], values=GROUPS, size_hint_y=None,
                                     height=dp(46), background_normal="",
                                     background_color=CARD2)
        self.box.add_widget(self.new_trainee)
        self.box.add_widget(self.trainee_group)
        self.box.add_widget(btn("Kursant əlavə et", self.add_trainee, GREEN,
                                size_hint_y=None, height=dp(52)))

    def add_user(self, *a):
        name = self.new_user.text.strip()
        pwd = self.new_pwd.text
        if not name or "/" in name or not pwd:
            return info("Xəta", "Ad (/ olmadan) və şifrə yazın")
        if self.all_groups.state == "down":
            groups = "*"
        else:
            groups = ",".join(g for g, tb in self.group_toggles.items() if tb.state == "down")
        if not groups:
            return info("Xəta", "Ən azı bir qrup seçin")
        is_admin = self.new_admin.state == "down"

        def work():
            users = CLOUD.list("users")
            if len(users) >= MAX_USERS:
                return "full"
            if any(u["_id"] == name for u in users):
                return "exists"
            CLOUD.set("users/%s" % name, {"pwd": sha(pwd), "is_admin": is_admin,
                                          "groups": groups})
            return "ok"

        def done(res):
            if res == "full":
                info("Xəta", "Ən çox %d istifadəçi ola bilər" % MAX_USERS)
            elif res == "exists":
                info("Xəta", "Bu ad artıq var")
            else:
                self.new_user.text = ""
                self.new_pwd.text = ""
                self.load()

        bg(work, done)

    def del_user(self, name):
        bg(lambda: CLOUD.delete("users/%s" % name), lambda _: self.load())

    def add_trainee(self, *a):
        name = self.new_trainee.text.strip()
        grp = self.trainee_group.text
        if not name:
            return info("Xəta", "Kursantın adını yazın")

        def work():
            trainees = CLOUD.list("trainees")
            n = max([t["number"] for t in trainees] or [0]) + 1
            CLOUD.set("trainees/k%d" % n, {"number": n, "name": name, "grp": grp,
                                           "last_status": "", "last_reason": ""})
            return n

        def done(n):
            self.new_trainee.text = ""
            info("Hazırdır", "Kursant əlavə olundu (№%d)" % n)

        bg(work, done)


class HistoryScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        box.add_widget(lbl("Tarixçə", size_hint_y=None, height=dp(34),
                           bold=True, color=CYAN, font_size=dp(20)))
        self.list_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.list_box)
        bar = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        bar.add_widget(btn("Word-ə yüklə", self.export, GREEN))
        bar.add_widget(btn("← Geri", lambda *a: setattr(self.manager, "current", "main"),
                           CARD2))
        box.add_widget(scroll)
        box.add_widget(bar)
        self.add_widget(box)

    def load(self):
        bg(lambda: sorted(CLOUD.list("days"), key=lambda d: d["_id"], reverse=True),
           self.render)

    def render(self, days):
        self.list_box.clear_widgets()
        for d in days:
            day = d["_id"]
            b = wrap(btn(show_day(day), lambda *a, day=day: self.detail(day),
                         CARD2, size_hint_y=None, height=dp(60)))
            b.halign = "left"
            self.list_box.add_widget(b)

    def detail(self, day):
        app = App.get_running_app()
        groups = allowed_groups(app.user)
        is_admin = app.user["is_admin"]

        def done(rows):
            rows = [r for r in rows if r.get("grp") in groups]
            rows.sort(key=lambda r: r["number"])
            self.show_day_popup(day, rows, is_admin)

        bg(lambda: CLOUD.list("days/%s/trainees" % day), done)

    def show_day_popup(self, day, rows, is_admin):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        for r in rows:
            text = "%d. %s — %s" % (r["number"], r["name"], r.get("status") or "")
            if r.get("reason"):
                text += "\nSəbəb: " + r["reason"]
            if r.get("edited"):
                text += "\n(dəyişdirilib)"
            color = GREEN if r.get("status") == "Bəli" else PINK
            b = wrap(btn(text, None, color, size_hint_y=None, height=dp(66)))
            b.halign = "left"
            if is_admin:
                b.bind(on_release=lambda *a, row=r: self.edit(day, row))
            grid.add_widget(b)
        scroll = ScrollView()
        scroll.add_widget(grid)
        box.add_widget(scroll)
        p = Popup(title="%s tarixçəsi" % show_day(day), title_color=CYAN,
                  separator_color=PINK, content=box, size_hint=(0.95, 0.9))
        box.add_widget(btn("← Geri", p.dismiss, CARD2, size_hint_y=None, height=dp(48)))
        p.open()

    def edit(self, day, row):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        status = Spinner(text=row.get("status") or "Bəli", values=["Bəli", "Xeyr"],
                         size_hint_y=None, height=dp(46), background_normal="",
                         background_color=CARD2)
        reason = field("Səbəb")
        reason.text = row.get("reason") or ""
        p = Popup(title="Qeydi dəyiş", title_color=CYAN, separator_color=PINK,
                  content=box, size_hint=(0.9, 0.5))

        def save(*a):
            new_status = status.text
            new_reason = reason.text.strip()
            if new_status == "Xeyr" and not new_reason:
                return info("Diqqət", "Xeyr üçün səbəb yazın")
            p.dismiss()

            def work():
                CLOUD.set("days/%s/trainees/%s" % (day, row["_id"]), {
                    "status": new_status, "reason": new_reason, "edited": True})
                CLOUD.set("trainees/%s" % row["_id"], {
                    "last_status": new_status, "last_reason": new_reason})
                return True

            bg(work, lambda _: self.detail(day))

        box.add_widget(status)
        box.add_widget(reason)
        box.add_widget(btn("Yadda saxla", save, GREEN, size_hint_y=None, height=dp(48)))
        p.open()

    def export(self, *a):
        app = App.get_running_app()
        groups = allowed_groups(app.user)

        def work():
            lines = ["Tel verməyənlər siyahısı", ""]
            for d in sorted(CLOUD.list("days"), key=lambda x: x["_id"], reverse=True):
                for r in CLOUD.list("days/%s/trainees" % d["_id"]):
                    if r.get("status") == "Xeyr" and r.get("grp") in groups:
                        lines.append(" | ".join([
                            show_day(d["_id"]), r["grp"], str(r["number"]),
                            r["name"], r.get("reason") or "", r.get("saved_by") or ""]))
            for folder in ("/sdcard/Download", App.get_running_app().user_data_dir):
                try:
                    path = os.path.join(folder, "xeyr_siyahisi.docx")
                    make_docx(path, lines)
                    return path
                except OSError:
                    pass
            return None

        def done(path):
            if path is None:
                info("Xəta", "Fayl yazıla bilmədi")
            else:
                info("Hazırdır", "Fayl yadda saxlanıldı:\n" + path)

        bg(work, done)


class TelApp(App):
    title = "Tel verən və verməyən"

    def build(self):
        Window.clearcolor = BG
        self.user = None
        self.sm = ScreenManager()
        for screen in (LoadingScreen(name="loading"), SetupScreen(name="setup"),
                       LoginScreen(name="login"), MainScreen(name="main"),
                       HistoryScreen(name="history"), AdminScreen(name="admin")):
            self.sm.add_widget(screen)
        return self.sm

    def on_start(self):
        self.sm.get_screen("loading").start()


if __name__ == "__main__":
    TelApp().run()
