import csv
import hashlib
import os
import sqlite3
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from kivy.app import App
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
DB_NAME = "tel_veren_v2.db"
GROUPS = ["5", "9", "13", "14", "17", "18", "22", "23", "25", "71"]
MAX_USERS = 20

BG = (0.03, 0.03, 0.04, 1)
CARD = (0.11, 0.11, 0.13, 1)
CARD2 = (0.18, 0.18, 0.21, 1)
PINK = (0.996, 0.173, 0.333, 1)
CYAN = (0.145, 0.957, 0.933, 1)
GREEN = (0.19, 0.82, 0.55, 1)
TEXT = (1, 1, 1, 1)
MUTED = (0.62, 0.62, 0.67, 1)


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
            CREATE TABLE IF NOT EXISTS day_records (
                id INTEGER PRIMARY KEY, day TEXT, trainee_id INTEGER,
                number INTEGER, name TEXT, grp TEXT, status TEXT, reason TEXT,
                saved_by TEXT, edited INTEGER DEFAULT 0,
                UNIQUE(day, trainee_id));
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

    def latest_status(self):
        rows = self.q("""SELECT d.* FROM day_records d JOIN
                         (SELECT trainee_id, MAX(day) AS md FROM day_records
                          GROUP BY trainee_id) m
                         ON d.trainee_id = m.trainee_id AND d.day = m.md""")
        return {r["trainee_id"]: r for r in rows}

    def upsert_day(self, day, user, items):
        for tid, status, reason, t in items:
            self.con.execute("""INSERT INTO day_records
                (day, trainee_id, number, name, grp, status, reason, saved_by, edited)
                VALUES (?,?,?,?,?,?,?,?,0)
                ON CONFLICT(day, trainee_id) DO UPDATE SET
                    status=excluded.status, reason=excluded.reason,
                    saved_by=excluded.saved_by, edited=0""",
                (day, tid, t["number"], t["name"], t["grp"], status, reason, user))
        self.con.commit()

    def days_for(self, groups):
        marks = ",".join("?" * len(groups))
        return self.q(f"""SELECT day, COUNT(*) AS cnt,
                          SUM(CASE WHEN status='Xeyr' THEN 1 ELSE 0 END) AS xeyr
                          FROM day_records WHERE grp IN ({marks})
                          GROUP BY day ORDER BY day DESC""", groups)

    def day_rows(self, day, groups):
        marks = ",".join("?" * len(groups))
        return self.q(f"""SELECT * FROM day_records WHERE day=? AND grp IN ({marks})
                          ORDER BY number""", [day] + list(groups))

    def xeyr_rows(self, groups):
        marks = ",".join("?" * len(groups))
        return self.q(f"""SELECT day, grp, number, name, reason, saved_by
                          FROM day_records WHERE status='Xeyr' AND grp IN ({marks})
                          ORDER BY day DESC, number""", groups)


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
        self.header.text = "Salam, %s" % u["username"]
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
        self.last = app.db.latest_status()
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

        card = panel(orientation="vertical", size_hint_y=None, height=dp(62),
                     padding=dp(8), spacing=dp(6))
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        top.add_widget(lbl(str(t["number"]), size_hint_x=0.12, bold=True, color=CYAN))
        top.add_widget(wrap(lbl(t["name"], halign="left", size_hint_x=0.4)))
        yes = RToggle(text="Bəli", group="t%d" % tid, on=GREEN, size_hint_x=0.16,
                      state="down" if status == "Bəli" else "normal")
        no = RToggle(text="Xeyr", group="t%d" % tid, on=PINK, size_hint_x=0.16,
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
            t = app.db.q("SELECT * FROM trainees WHERE id=?", (tid,))[0]
            items.append((tid, status, why, t))
        if not items:
            return info("Məlumat", "Dəyişiklik yoxdur")
        day = today_key()
        app.db.upsert_day(day, app.user["username"], items)
        self.pending = {}
        info("Yadda saxlandı",
             "%d kursant bu günün (%s) tarixçəsinə əlavə olundu"
             % (len(items), show_day(day)))
        self.build_list()

    def delete_trainee(self, tid):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        p = Popup(title="Silinsin?", title_color=CYAN, separator_color=PINK,
                  content=box, size_hint=(0.85, 0.35))
        box.add_widget(lbl("Kursant siyahıdan silinsin?\nTarixçə qalacaq."))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))

        def yes(*a):
            App.get_running_app().db.run("DELETE FROM trainees WHERE id=?", (tid,))
            self.pending.pop(tid, None)
            p.dismiss()
            self.build_list()

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
        app = App.get_running_app()
        self.box.clear_widgets()
        users = app.db.q("SELECT * FROM users ORDER BY id")
        self.box.add_widget(lbl("İstifadəçilər (%d/%d)" % (len(users), MAX_USERS),
                                size_hint_y=None, height=dp(30), bold=True, color=CYAN))
        for u in users:
            row = panel(size_hint_y=None, height=dp(54), padding=dp(8), spacing=dp(8))
            tag = "  · admin" if u["is_admin"] else ""
            row.add_widget(wrap(lbl(u["username"] + tag, halign="left")))
            if u["username"] != app.user["username"]:
                row.add_widget(btn("Sil", lambda *a, uid=u["id"]: self.del_user(uid),
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
        app = App.get_running_app()
        self.list_box.clear_widgets()
        for d in app.db.days_for(allowed_groups(app.user)):
            text = "%s\n%d kursant · %d Xeyr" % (show_day(d["day"]), d["cnt"], d["xeyr"] or 0)
            b = wrap(btn(text, lambda *a, day=d["day"]: self.detail(day),
                         CARD2, size_hint_y=None, height=dp(70)))
            b.halign = "left"
            self.list_box.add_widget(b)

    def detail(self, day):
        app = App.get_running_app()
        u = app.user
        rows = app.db.day_rows(day, allowed_groups(u))
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grid.bind(minimum_height=grid.setter("height"))
        for r in rows:
            text = "%d. %s — %s" % (r["number"], r["name"], r["status"])
            if r["reason"]:
                text += "\nSəbəb: " + r["reason"]
            if r["edited"]:
                text += "\n(dəyişdirilib)"
            color = GREEN if r["status"] == "Bəli" else PINK
            b = wrap(btn(text, None, color, size_hint_y=None, height=dp(66)))
            b.halign = "left"
            if u["is_admin"]:
                b.bind(on_release=lambda *a, rid=r["id"]: self.edit(rid, day))
            grid.add_widget(b)
        scroll = ScrollView()
        scroll.add_widget(grid)
        box.add_widget(scroll)
        p = Popup(title="%s tarixçəsi" % show_day(day), title_color=CYAN,
                  separator_color=PINK, content=box, size_hint=(0.95, 0.9))
        box.add_widget(btn("← Geri", p.dismiss, CARD2, size_hint_y=None, height=dp(48)))
        p.open()

    def edit(self, rid, day):
        app = App.get_running_app()
        r = app.db.q("SELECT * FROM day_records WHERE id=?", (rid,))[0]
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        status = Spinner(text=r["status"], values=["Bəli", "Xeyr"], size_hint_y=None,
                         height=dp(46), background_normal="", background_color=CARD2)
        reason = field("Səbəb")
        reason.text = r["reason"] or ""
        p = Popup(title="Qeydi dəyiş", title_color=CYAN, separator_color=PINK,
                  content=box, size_hint=(0.9, 0.5))

        def save(*a):
            app.db.run("UPDATE day_records SET status=?, reason=?, edited=1 WHERE id=?",
                       (status.text, reason.text.strip(), rid))
            p.dismiss()
            self.detail(day)

        box.add_widget(status)
        box.add_widget(reason)
        box.add_widget(btn("Yadda saxla", save, GREEN, size_hint_y=None, height=dp(48)))
        p.open()

    def export(self, *a):
        app = App.get_running_app()
        lines = ["Tel verməyənlər siyahısı", ""]
        for r in app.db.xeyr_rows(allowed_groups(app.user)):
            lines.append(" | ".join([show_day(r["day"]), r["grp"], str(r["number"]),
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
