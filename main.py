import csv
import hashlib
import os
import sqlite3
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
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
DB_NAME = "tel_veren_v2.db"
GROUPS = ["5", "9", "13", "14", "17", "18", "22", "23", "25", "71"]
MAX_USERS = 12
DATE_FMT = "%d.%m.%Y %H:%M"

BG = (0.06, 0.08, 0.11, 1)
CARD = (0.11, 0.14, 0.19, 1)
ACCENT = (0.16, 0.5, 0.85, 1)
GREEN = (0.18, 0.62, 0.35, 1)
RED = (0.78, 0.24, 0.24, 1)
GREY = (0.26, 0.3, 0.36, 1)
TEXT = (0.93, 0.95, 0.97, 1)
MUTED = (0.6, 0.66, 0.73, 1)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def info(title, text):
    Popup(title=title, title_color=ACCENT,
          content=Label(text=text, color=TEXT),
          size_hint=(0.85, 0.35)).open()


def lbl(text, **kw):
    kw.setdefault("color", TEXT)
    return Label(text=text, **kw)


def btn(text, fn=None, color=ACCENT, **kw):
    b = Button(text=text, color=TEXT, background_normal="",
               background_color=color, **kw)
    if fn:
        b.bind(on_release=fn)
    return b


def field(hint, password=False):
    return TextInput(hint_text=hint, password=password, multiline=False,
                     size_hint_y=None, height=dp(46), foreground_color=TEXT,
                     hint_text_color=MUTED, background_color=CARD)


def wrap(widget):
    widget.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
    return widget


def style_toggle(tb, on_color):
    def upd(*_):
        tb.background_color = on_color if tb.state == "down" else GREY
    tb.background_normal = ""
    tb.bind(state=upd)
    upd()


def panel(**kw):
    box = BoxLayout(**kw)
    with box.canvas.before:
        Color(*CARD)
        rect = Rectangle(pos=box.pos, size=box.size)
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


def allowed_groups(user):
    if user["is_admin"] or user["groups"] == "*":
        return GROUPS
    return [g for g in user["groups"].split(",") if g]


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


class DB:
    def __init__(self, path):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE, pwd TEXT,
                is_admin INTEGER DEFAULT 0, groups TEXT DEFAULT '*');
            CREATE TABLE IF NOT EXISTS trainees (
                id INTEGER PRIMARY KEY, number INTEGER, name TEXT, grp TEXT);
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, saved_at TEXT, saved_by TEXT);
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY, session_id INTEGER, trainee_id INTEGER,
                number INTEGER, name TEXT, grp TEXT, status TEXT, reason TEXT,
                edited INTEGER DEFAULT 0);
        """)
        self.con.commit()
        if not self.q("SELECT 1 FROM trainees"):
            self.load_csv()

    def q(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def run(self, sql, args=()):
        self.con.execute(sql, args)
        self.con.commit()

    def add_user(self, username, password, is_admin, groups):
        try:
            self.run("INSERT INTO users (username, pwd, is_admin, groups) VALUES (?,?,?,?)",
                     (username, sha(password), int(is_admin), groups))
            return True
        except sqlite3.IntegrityError:
            return False

    def load_csv(self):
        with open(os.path.join(HERE, "trainees.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.run("INSERT INTO trainees (number, name, grp) VALUES (?,?,?)",
                         (int(row["number"]), row["name"], row["group"]))

    def add_trainee(self, name, grp):
        number = self.q("SELECT COALESCE(MAX(number),0)+1 AS n FROM trainees")[0]["n"]
        self.run("INSERT INTO trainees (number, name, grp) VALUES (?,?,?)",
                 (number, name, grp))

    def trainees_in(self, grp):
        return self.q("SELECT * FROM trainees WHERE grp=? ORDER BY number", (grp,))

    def latest_records(self):
        rows = self.q("""SELECT * FROM records WHERE id IN
                         (SELECT MAX(id) FROM records GROUP BY trainee_id)""")
        return {r["trainee_id"]: r for r in rows}

    def save_session(self, user, changes, now):
        cur = self.con.execute("INSERT INTO sessions (saved_at, saved_by) VALUES (?,?)",
                               (now, user))
        sid = cur.lastrowid
        for tid, status, reason, t in changes:
            self.con.execute("""INSERT INTO records
                                (session_id, trainee_id, number, name, grp, status, reason)
                                VALUES (?,?,?,?,?,?,?)""",
                             (sid, tid, t["number"], t["name"], t["grp"], status, reason))
        self.con.commit()

    def sessions_for(self, groups):
        marks = ",".join("?" * len(groups))
        return self.q(f"""SELECT s.id, s.saved_at, s.saved_by, COUNT(r.id) AS cnt
                          FROM sessions s JOIN records r ON r.session_id = s.id
                          WHERE r.grp IN ({marks})
                          GROUP BY s.id ORDER BY s.id DESC LIMIT 200""", groups)

    def session_records(self, sid, groups):
        marks = ",".join("?" * len(groups))
        return self.q(f"""SELECT * FROM records WHERE session_id = ? AND grp IN ({marks})
                          ORDER BY number""", [sid] + list(groups))

    def xeyr_rows(self, groups):
        marks = ",".join("?" * len(groups))
        return self.q(f"""SELECT s.saved_at, s.saved_by, r.grp, r.number, r.name, r.reason
                          FROM records r JOIN sessions s ON s.id = r.session_id
                          WHERE r.status = 'Xeyr' AND r.grp IN ({marks})
                          ORDER BY s.id DESC, r.number""", groups)


class SetupScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(30), spacing=dp(12))
        box.add_widget(lbl("İlk quraşdırma\nAdmin hesabı yaradın", markup=False,
                           font_size=dp(20), bold=True, size_hint_y=0.25))
        self.user_in = field("Admin istifadəçi adı")
        self.pwd_in = field("Şifrə (ən azı 4 simvol)", password=True)
        self.pwd2_in = field("Şifrəni təkrar yazın", password=True)
        box.add_widget(self.user_in)
        box.add_widget(self.pwd_in)
        box.add_widget(self.pwd2_in)
        box.add_widget(btn("Admin yarat", self.create, GREEN,
                           size_hint_y=None, height=dp(50)))
        self.add_widget(box)

    def create(self, *a):
        app = App.get_running_app()
        name = self.user_in.text.strip()
        pwd = self.pwd_in.text
        if not name or len(pwd) < 4:
            return info("Xəta", "Ad yazın və ən azı 4 simvollu şifrə seçin")
        if pwd != self.pwd2_in.text:
            return info("Xəta", "Şifrələr uyğun gəlmir")
        app.db.add_user(name, pwd, True, "*")
        self.pwd_in.text = ""
        self.pwd2_in.text = ""
        self.manager.current = "login"


class LoginScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(30), spacing=dp(12))
        logo = os.path.join(HERE, "assets", "logo.png")
        if os.path.exists(logo):
            box.add_widget(Image(source=logo, size_hint_y=0.45))
        box.add_widget(lbl("Tel verən və verməyən", font_size=dp(22),
                           bold=True, size_hint_y=0.12))
        self.user_in = field("İstifadəçi adı")
        self.pwd_in = field("Şifrə", password=True)
        box.add_widget(self.user_in)
        box.add_widget(self.pwd_in)
        box.add_widget(btn("Daxil ol", self.login, ACCENT,
                           size_hint_y=None, height=dp(50)))
        self.add_widget(box)

    def login(self, *a):
        app = App.get_running_app()
        rows = app.db.q("SELECT * FROM users WHERE username=? AND pwd=?",
                        (self.user_in.text.strip(), sha(self.pwd_in.text)))
        if not rows:
            return info("Xəta", "İstifadəçi adı və ya şifrə yanlışdır")
        app.user = dict(rows[0])
        self.pwd_in.text = ""
        self.manager.current = "main"
        self.manager.get_screen("main").load()


class MainScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows = {}
        self.last = {}
        self.pending = {}
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        self.header = lbl("", size_hint_y=None, height=dp(32), bold=True, color=ACCENT)
        self.spinner = Spinner(size_hint_y=None, height=dp(46), background_normal="",
                               background_color=ACCENT, color=TEXT)
        self.spinner.bind(text=lambda *a: self.build_list())
        self.list_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.list_box)
        bar = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(6))
        self.admin_btn = btn("Admin", lambda *a: self.open("admin"), GREY)
        bar.add_widget(btn("Yadda saxla", self.save, GREEN))
        bar.add_widget(btn("Tarixçə", lambda *a: self.open("history"), ACCENT))
        bar.add_widget(self.admin_btn)
        bar.add_widget(btn("Çıxış", self.logout, RED))
        for w in (self.header, self.spinner, scroll, bar):
            box.add_widget(w)
        self.add_widget(box)

    def load(self):
        u = App.get_running_app().user
        groups = allowed_groups(u)
        self.pending = {}
        self.header.text = "Daxil olub: %s" % u["username"]
        self.spinner.values = groups
        self.spinner.text = groups[0]
        self.admin_btn.opacity = 1 if u["is_admin"] else 0
        self.admin_btn.disabled = not u["is_admin"]
        self.build_list()

    def build_list(self):
        app = App.get_running_app()
        self.list_box.clear_widgets()
        self.rows = {}
        group = self.spinner.text
        if group not in allowed_groups(app.user):
            return
        self.last = app.db.latest_records()
        for t in app.db.trainees_in(group):
            self.add_row(t)

    def add_row(self, t):
        app = App.get_running_app()
        tid = t["id"]
        if tid in self.pending:
            status, reason = self.pending[tid]
        elif tid in self.last:
            status, reason = self.last[tid]["status"], self.last[tid]["reason"] or ""
        else:
            status, reason = None, ""

        card = panel(orientation="vertical", size_hint_y=None, height=dp(56),
                     padding=dp(6), spacing=dp(4))
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
        top.add_widget(lbl(str(t["number"]), size_hint_x=0.12, bold=True, color=ACCENT))
        top.add_widget(wrap(lbl(t["name"], halign="left", size_hint_x=0.4)))
        yes = ToggleButton(text="Bəli", group="t%d" % tid, size_hint_x=0.16,
                           state="down" if status == "Bəli" else "normal")
        no = ToggleButton(text="Xeyr", group="t%d" % tid, size_hint_x=0.16,
                          state="down" if status == "Xeyr" else "normal")
        style_toggle(yes, GREEN)
        style_toggle(no, RED)
        top.add_widget(yes)
        top.add_widget(no)
        if app.user["is_admin"]:
            top.add_widget(btn("Sil", lambda *a, tid=tid: self.delete_trainee(tid),
                               RED, size_hint_x=0.16))
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
            reason_in.height = dp(46) if shown else 0
            card.height = dp(104) if shown else dp(56)

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
        changes = []
        for tid, (status, why) in self.pending.items():
            if status == "Xeyr" and not why:
                return info("Diqqət", "Xeyr seçilən hər kursant üçün səbəb yazın")
            prev = self.last.get(tid)
            if prev is not None and prev["status"] == status and (prev["reason"] or "") == why:
                continue
            t = app.db.q("SELECT * FROM trainees WHERE id=?", (tid,))[0]
            changes.append((tid, status, why, t))
        if not changes:
            return info("Məlumat", "Dəyişiklik yoxdur")
        now = datetime.now().strftime(DATE_FMT)
        app.db.save_session(app.user["username"], changes, now)
        self.pending = {}
        info("Yadda saxlandı", "%d kursant üçün tarixçəyə bir qeyd əlavə olundu" % len(changes))
        self.build_list()

    def delete_trainee(self, tid):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        p = Popup(title="Silinsin?", title_color=ACCENT, content=box,
                  size_hint=(0.85, 0.35))
        box.add_widget(lbl("Kursant siyahıdan silinsin?\nTarixçə qalacaq."))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))

        def yes(*a):
            App.get_running_app().db.run("DELETE FROM trainees WHERE id=?", (tid,))
            self.pending.pop(tid, None)
            p.dismiss()
            self.build_list()

        row.add_widget(btn("Bəli, sil", yes, RED))
        row.add_widget(btn("Xeyr", lambda *a: p.dismiss(), GREY))
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
        scroll = ScrollView()
        self.box = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=dp(10))
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        self.add_widget(scroll)

    def load(self):
        app = App.get_running_app()
        self.box.clear_widgets()
        users = app.db.q("SELECT * FROM users ORDER BY id")
        self.box.add_widget(lbl("İstifadəçilər (%d/%d)" % (len(users), MAX_USERS),
                                size_hint_y=None, height=dp(32), bold=True, color=ACCENT))
        for u in users:
            row = panel(size_hint_y=None, height=dp(50), padding=dp(6), spacing=dp(6))
            tag = "  (admin)" if u["is_admin"] else ""
            row.add_widget(wrap(lbl(u["username"] + tag, halign="left")))
            if u["username"] != app.user["username"]:
                row.add_widget(btn("Sil", lambda *a, uid=u["id"]: self.del_user(uid),
                                   RED, size_hint_x=0.3))
            self.box.add_widget(row)

        self.box.add_widget(lbl("Yeni istifadəçi", size_hint_y=None, height=dp(32),
                                bold=True, color=ACCENT))
        self.new_user = field("İstifadəçi adı")
        self.new_pwd = field("Şifrə", password=True)
        self.new_admin = ToggleButton(text="Admin olsun", size_hint_y=None, height=dp(46))
        style_toggle(self.new_admin, GREEN)
        self.box.add_widget(self.new_user)
        self.box.add_widget(self.new_pwd)
        self.box.add_widget(self.new_admin)
        self.box.add_widget(lbl("Hansı qrupları görsün?", size_hint_y=None, height=dp(28)))
        grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        self.all_groups = ToggleButton(text="Hamısı", size_hint_y=None, height=dp(46))
        style_toggle(self.all_groups, GREEN)
        grid.add_widget(self.all_groups)
        self.group_toggles = {}
        for g in GROUPS:
            tb = ToggleButton(text=g, size_hint_y=None, height=dp(46))
            style_toggle(tb, ACCENT)
            self.group_toggles[g] = tb
            grid.add_widget(tb)
        self.box.add_widget(grid)
        self.box.add_widget(btn("İstifadəçi əlavə et", self.add_user, GREEN,
                                size_hint_y=None, height=dp(48)))

        self.box.add_widget(lbl("Yeni kursant", size_hint_y=None, height=dp(32),
                                bold=True, color=ACCENT))
        self.new_trainee = field("Ad, soyad, ata adı")
        self.trainee_group = Spinner(text=GROUPS[0], values=GROUPS, size_hint_y=None,
                                     height=dp(46), background_normal="",
                                     background_color=ACCENT)
        self.box.add_widget(self.new_trainee)
        self.box.add_widget(self.trainee_group)
        self.box.add_widget(btn("Kursant əlavə et", self.add_trainee, GREEN,
                                size_hint_y=None, height=dp(48)))

    def add_user(self, *a):
        app = App.get_running_app()
        name = self.new_user.text.strip()
        pwd = self.new_pwd.text
        if len(app.db.q("SELECT id FROM users")) >= MAX_USERS:
            return info("Xəta", "Ən çox %d istifadəçi ola bilər" % MAX_USERS)
        if not name or not pwd:
            return info("Xəta", "Ad və şifrə yazın")
        if self.all_groups.state == "down":
            groups = "*"
        else:
            groups = ",".join(g for g, tb in self.group_toggles.items() if tb.state == "down")
        if not groups:
            return info("Xəta", "Ən azı bir qrup seçin")
        if not app.db.add_user(name, pwd, self.new_admin.state == "down", groups):
            return info("Xəta", "Bu ad artıq var")
        self.load()

    def del_user(self, uid):
        App.get_running_app().db.run("DELETE FROM users WHERE id=?", (uid,))
        self.load()

    def add_trainee(self, *a):
        app = App.get_running_app()
        name = self.new_trainee.text.strip()
        if not name:
            return info("Xəta", "Kursantın adını yazın")
        app.db.add_trainee(name, self.trainee_group.text)
        self.new_trainee.text = ""
        info("Hazırdır", "Kursant əlavə olundu")
        self.load()


class HistoryScreen(BaseScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        box.add_widget(lbl("Tarixçə", size_hint_y=None, height=dp(32),
                           bold=True, color=ACCENT))
        self.list_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(8))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.list_box)
        bar = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(6))
        bar.add_widget(btn("Xeyrləri Word-ə yüklə", self.export, GREEN))
        bar.add_widget(btn("Geri", lambda *a: setattr(self.manager, "current", "main"), GREY))
        box.add_widget(scroll)
        box.add_widget(bar)
        self.add_widget(box)

    def load(self):
        app = App.get_running_app()
        self.list_box.clear_widgets()
        for s in app.db.sessions_for(allowed_groups(app.user)):
            text = "%s\n%s · %d kursant dəyişib" % (s["saved_at"], s["saved_by"], s["cnt"])
            b = wrap(btn(text, lambda *a, sid=s["id"]: self.detail(sid),
                         CARD, size_hint_y=None, height=dp(66)))
            b.halign = "left"
            self.list_box.add_widget(b)

    def detail(self, sid):
        app = App.get_running_app()
        u = app.user
        rows = app.db.session_records(sid, allowed_groups(u))
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        for r in rows:
            text = "%d. %s — %s" % (r["number"], r["name"], r["status"])
            if r["reason"]:
                text += "\nSəbəb: " + r["reason"]
            if r["edited"]:
                text += "\n(dəyişdirilib)"
            color = GREEN if r["status"] == "Bəli" else RED
            b = wrap(btn(text, None, color, size_hint_y=None, height=dp(66)))
            b.halign = "left"
            if u["is_admin"]:
                b.bind(on_release=lambda *a, rid=r["id"]: self.edit(rid))
            grid.add_widget(b)
        scroll = ScrollView()
        scroll.add_widget(grid)
        box.add_widget(scroll)
        p = Popup(title="Qeyd: %s" % rows[0]["number"] if False else "Tarixçə qeydi",
                  title_color=ACCENT, content=box, size_hint=(0.95, 0.9))
        box.add_widget(btn("Bağla", p.dismiss, GREY, size_hint_y=None, height=dp(46)))
        p.open()

    def edit(self, rid):
        app = App.get_running_app()
        r = app.db.q("SELECT * FROM records WHERE id=?", (rid,))[0]
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        status = Spinner(text=r["status"], values=["Bəli", "Xeyr"], size_hint_y=None,
                         height=dp(46), background_normal="", background_color=ACCENT)
        reason = field("Səbəb")
        reason.text = r["reason"] or ""
        p = Popup(title="Qeydi dəyiş", title_color=ACCENT, content=box,
                  size_hint=(0.9, 0.5))

        def save(*a):
            app.db.run("UPDATE records SET status=?, reason=?, edited=1 WHERE id=?",
                       (status.text, reason.text.strip(), rid))
            p.dismiss()
            info("Hazırdır", "Dəyişiklik yadda saxlandı. Qeydi yenidən açın.")

        box.add_widget(status)
        box.add_widget(reason)
        box.add_widget(btn("Yadda saxla", save, GREEN, size_hint_y=None, height=dp(46)))
        p.open()

    def export(self, *a):
        app = App.get_running_app()
        lines = ["Tel verməyənlər siyahısı", ""]
        for r in app.db.xeyr_rows(allowed_groups(app.user)):
            lines.append(" | ".join([r["saved_at"], r["grp"], str(r["number"]),
                                     r["name"], r["reason"] or "", r["saved_by"]]))
        path = None
        for folder in ("/sdcard/Download", app.user_data_dir):
            try:
                path = os.path.join(folder, "xeyr_siyahisi.docx")
                make_docx(path, lines)
                break
            except OSError:
                path = None
        if path is None:
            return info("Xəta", "Fayl yazıla bilmədi")
        info("Hazırdır", "Fayl yadda saxlanıldı:\n" + path)


class TelApp(App):
    title = "Tel verən və verməyən"

    def build(self):
        Window.clearcolor = BG
        self.db = DB(os.path.join(self.user_data_dir, DB_NAME))
        self.user = None
        sm = ScreenManager()
        for screen in (SetupScreen(name="setup"), LoginScreen(name="login"),
                       MainScreen(name="main"), HistoryScreen(name="history"),
                       AdminScreen(name="admin")):
            sm.add_widget(screen)
        sm.current = "login" if self.db.q("SELECT 1 FROM users") else "setup"
        return sm


if __name__ == "__main__":
    TelApp().run()
