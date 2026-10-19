import csv
import hashlib
import os
import sqlite3
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from kivy.app import App
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
GROUPS = ["5", "9", "13", "14", "17", "18", "22", "23", "25", "71"]
MAX_USERS = 12
DATE_FMT = "%d.%m.%Y %H:%M"
ALL = "Hamısı"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def info(title, text):
    Popup(title=title, content=Label(text=text), size_hint=(0.85, 0.35)).open()


def btn(text, fn=None, **kw):
    b = Button(text=text, **kw)
    if fn:
        b.bind(on_release=fn)
    return b


def wrap(widget):
    widget.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
    return widget


def allowed_groups(user):
    # admin və ya "*" olan user hamısını görür
    if user["is_admin"] or user["groups"] == "*":
        return GROUPS
    return [g for g in user["groups"].split(",") if g]


def filter_groups(user, choice):
    allowed = allowed_groups(user)
    if choice == ALL or choice not in allowed:
        return allowed
    return [choice]


def make_docx(path, lines):
    # Word faylını əl ilə yaradırıq ki, Android-də ağır kitabxana lazım olmasın
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
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY, trainee_id INTEGER, trainee_name TEXT,
                grp TEXT, status TEXT, reason TEXT, saved_at TEXT,
                saved_by TEXT, edited INTEGER DEFAULT 0);
        """)
        self.con.commit()
        # ilk işə salanda admin yaradılır: şifrəni APK qurmazdan əvvəl dəyiş
        if not self.q("SELECT 1 FROM users"):
            self.add_user("admin", "admin", True, "*")
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

    def latest_records(self):
        rows = self.q("""SELECT r.* FROM records r
                         JOIN (SELECT trainee_id, MAX(id) AS mid FROM records
                               GROUP BY trainee_id) m ON r.id = m.mid""")
        return {r["trainee_id"]: r for r in rows}


class LoginScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        box = BoxLayout(orientation="vertical", padding=dp(30), spacing=dp(12))
        logo = os.path.join(HERE, "assets", "logo.png")
        if os.path.exists(logo):
            box.add_widget(Image(source=logo, size_hint_y=0.4))
        box.add_widget(Label(text="[b]Tel verən və verməyən[/b]", markup=True,
                             font_size=dp(22), size_hint_y=0.15))
        self.user_in = TextInput(hint_text="İstifadəçi adı", multiline=False,
                                 size_hint_y=None, height=dp(48))
        self.pwd_in = TextInput(hint_text="Şifrə", password=True, multiline=False,
                                size_hint_y=None, height=dp(48))
        box.add_widget(self.user_in)
        box.add_widget(self.pwd_in)
        box.add_widget(btn("Daxil ol", self.login, size_hint_y=None, height=dp(50)))
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


class MainScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows = {}
        self.last = {}
        box = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
        self.header = Label(size_hint_y=None, height=dp(28))
        self.spinner = Spinner(size_hint_y=None, height=dp(44))
        self.spinner.bind(text=lambda *a: self.build_list())
        self.list_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.list_box)
        bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        self.admin_btn = btn("Admin", lambda *a: self.open("admin"))
        bar.add_widget(btn("Yadda saxla", self.save))
        bar.add_widget(btn("Tarixçə", lambda *a: self.open("history")))
        bar.add_widget(self.admin_btn)
        bar.add_widget(btn("Çıxış", self.logout))
        box.add_widget(self.header)
        box.add_widget(self.spinner)
        box.add_widget(scroll)
        box.add_widget(bar)
        self.add_widget(box)

    def load(self):
        u = App.get_running_app().user
        self.header.text = "Daxil olub: %s" % u["username"]
        self.spinner.values = [ALL] + allowed_groups(u)
        self.spinner.text = ALL
        self.admin_btn.opacity = 1 if u["is_admin"] else 0
        self.admin_btn.disabled = not u["is_admin"]
        self.build_list()

    def build_list(self):
        app = App.get_running_app()
        self.list_box.clear_widgets()
        self.rows = {}
        groups = filter_groups(app.user, self.spinner.text)
        if not groups:
            return
        marks = ",".join("?" * len(groups))
        trainees = app.db.q(
            "SELECT * FROM trainees WHERE grp IN (%s) ORDER BY CAST(grp AS INTEGER), number" % marks,
            groups)
        self.last = app.db.latest_records()
        for t in trainees:
            self.add_row(t, self.last.get(t["id"]))

    def add_row(self, t, rec):
        app = App.get_running_app()
        tid = t["id"]
        status = rec["status"] if rec else None
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(48))
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(4))
        top.add_widget(wrap(Label(text="%d. %s" % (t["number"], t["name"]),
                                  halign="left", size_hint_x=0.46)))
        yes = ToggleButton(text="Bəli", group="t%d" % tid, size_hint_x=0.14,
                           state="down" if status == "Bəli" else "normal")
        no = ToggleButton(text="Xeyr", group="t%d" % tid, size_hint_x=0.14,
                          state="down" if status == "Xeyr" else "normal")
        top.add_widget(yes)
        top.add_widget(no)
        if app.user["is_admin"]:
            top.add_widget(btn("Sil", lambda *a, tid=tid: self.delete_trainee(tid),
                               size_hint_x=0.14))
        reason = TextInput(hint_text="Niyə telefonu verməyib?", multiline=False,
                           size_hint_y=None, height=0, opacity=0, disabled=True)
        if status == "Xeyr":
            reason.text = rec["reason"] or ""

        def toggle(*_):
            shown = no.state == "down"
            reason.opacity = 1 if shown else 0
            reason.disabled = not shown
            reason.height = dp(40) if shown else 0
            box.height = dp(88) if shown else dp(48)

        no.bind(state=toggle)
        box.add_widget(top)
        box.add_widget(reason)
        self.list_box.add_widget(box)
        self.rows[tid] = (yes, no, reason)
        toggle()

    def save(self, *_):
        app = App.get_running_app()
        todo = []
        for tid, (yes, no, reason) in self.rows.items():
            if yes.state == "down":
                status, why = "Bəli", ""
            elif no.state == "down":
                why = reason.text.strip()
                if not why:
                    return info("Diqqət", "Xeyr seçilən kursant üçün səbəb yazın")
                status = "Xeyr"
            else:
                continue
            prev = self.last.get(tid)
            # dəyişiklik olmayanı tarixçəyə yazmırıq
            if prev is not None and prev["status"] == status and (prev["reason"] or "") == why:
                continue
            todo.append((tid, status, why))
        if not todo:
            return info("Məlumat", "Dəyişiklik yoxdur")
        now = datetime.now().strftime(DATE_FMT)
        for tid, status, why in todo:
            t = app.db.q("SELECT * FROM trainees WHERE id=?", (tid,))[0]
            app.db.run("""INSERT INTO records (trainee_id, trainee_name, grp, status,
                          reason, saved_at, saved_by) VALUES (?,?,?,?,?,?,?)""",
                       (tid, t["name"], t["grp"], status, why, now, app.user["username"]))
        info("Yadda saxlandı", "%d qeyd tarixçəyə əlavə olundu" % len(todo))
        self.build_list()

    def delete_trainee(self, tid):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        p = Popup(title="Silinsin?", content=box, size_hint=(0.85, 0.35))
        box.add_widget(Label(text="Kursant siyahıdan silinsin?\n(tarixçə qalacaq)"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))

        def yes(*a):
            App.get_running_app().db.run("DELETE FROM trainees WHERE id=?", (tid,))
            p.dismiss()
            self.build_list()

        row.add_widget(btn("Bəli, sil", yes))
        row.add_widget(btn("Xeyr", lambda *a: p.dismiss()))
        box.add_widget(row)
        p.open()

    def open(self, name):
        self.manager.current = name
        self.manager.get_screen(name).load()

    def logout(self, *a):
        App.get_running_app().user = None
        self.manager.current = "login"


class AdminScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        scroll = ScrollView()
        self.box = GridLayout(cols=1, size_hint_y=None, spacing=dp(8), padding=dp(8))
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        self.add_widget(scroll)

    def load(self):
        app = App.get_running_app()
        self.box.clear_widgets()
        users = app.db.q("SELECT * FROM users ORDER BY id")
        self.box.add_widget(Label(text="İstifadəçilər (%d/%d)" % (len(users), MAX_USERS),
                                  size_hint_y=None, height=dp(30), bold=True))
        for u in users:
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
            tag = " (admin)" if u["is_admin"] else ""
            row.add_widget(Label(text=u["username"] + tag))
            if u["username"] != app.user["username"]:
                row.add_widget(btn("Sil", lambda *a, uid=u["id"]: self.del_user(uid),
                                   size_hint_x=0.3))
            self.box.add_widget(row)

        self.box.add_widget(Label(text="Yeni istifadəçi", size_hint_y=None,
                                  height=dp(30), bold=True))
        self.new_user = TextInput(hint_text="İstifadəçi adı", multiline=False,
                                  size_hint_y=None, height=dp(44))
        self.new_pwd = TextInput(hint_text="Şifrə", password=True, multiline=False,
                                 size_hint_y=None, height=dp(44))
        self.new_admin = ToggleButton(text="Admin olsun", size_hint_y=None, height=dp(44))
        self.box.add_widget(self.new_user)
        self.box.add_widget(self.new_pwd)
        self.box.add_widget(self.new_admin)
        self.box.add_widget(Label(text="Hansı qrupları görsün?", size_hint_y=None,
                                  height=dp(28)))
        grid = GridLayout(cols=4, size_hint_y=None, spacing=dp(4))
        grid.bind(minimum_height=grid.setter("height"))
        self.all_groups = ToggleButton(text="Bütün qruplar", size_hint_y=None, height=dp(44))
        grid.add_widget(self.all_groups)
        self.group_toggles = {}
        for g in GROUPS:
            tb = ToggleButton(text=g, size_hint_y=None, height=dp(44))
            self.group_toggles[g] = tb
            grid.add_widget(tb)
        self.box.add_widget(grid)
        self.box.add_widget(btn("İstifadəçi əlavə et", self.add_user,
                                size_hint_y=None, height=dp(48)))

        self.box.add_widget(Label(text="Yeni kursant", size_hint_y=None,
                                  height=dp(30), bold=True))
        self.new_trainee = TextInput(hint_text="Ad, soyad, ata adı", multiline=False,
                                     size_hint_y=None, height=dp(44))
        self.trainee_group = Spinner(text=GROUPS[0], values=GROUPS,
                                     size_hint_y=None, height=dp(44))
        self.box.add_widget(self.new_trainee)
        self.box.add_widget(self.trainee_group)
        self.box.add_widget(btn("Kursant əlavə et", self.add_trainee,
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
        number = app.db.q("SELECT COALESCE(MAX(number),0)+1 AS n FROM trainees")[0]["n"]
        app.db.run("INSERT INTO trainees (number, name, grp) VALUES (?,?,?)",
                   (number, name, self.trainee_group.text))
        self.new_trainee.text = ""
        info("Hazırdır", "Kursant əlavə olundu")


class HistoryScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows = []
        box = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(6))
        self.spinner = Spinner(size_hint_y=None, height=dp(44))
        self.spinner.bind(text=lambda *a: self.build())
        self.list_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.list_box)
        bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        bar.add_widget(btn("Xeyrləri Word-ə yüklə", self.export))
        bar.add_widget(btn("Geri", lambda *a: setattr(self.manager, "current", "main")))
        box.add_widget(self.spinner)
        box.add_widget(scroll)
        box.add_widget(bar)
        self.add_widget(box)

    def load(self):
        u = App.get_running_app().user
        self.spinner.values = [ALL] + allowed_groups(u)
        self.spinner.text = ALL
        self.build()

    def fetch(self):
        app = App.get_running_app()
        groups = filter_groups(app.user, self.spinner.text)
        if not groups:
            return []
        marks = ",".join("?" * len(groups))
        return app.db.q("SELECT * FROM records WHERE grp IN (%s) ORDER BY id DESC LIMIT 500" % marks,
                        groups)

    def build(self):
        self.list_box.clear_widgets()
        self.rows = self.fetch()
        is_admin = App.get_running_app().user["is_admin"]
        for r in self.rows:
            text = "%s | %s\n%s - %s" % (r["saved_at"], r["grp"], r["trainee_name"], r["status"])
            if r["reason"]:
                text += "\nSəbəb: " + r["reason"]
            if r["edited"]:
                text += "\n(dəyişdirilib)"
            b = wrap(Button(text=text, size_hint_y=None, height=dp(72), halign="left"))
            if is_admin:
                b.bind(on_release=lambda *a, rid=r["id"]: self.edit(rid))
            self.list_box.add_widget(b)

    def edit(self, rid):
        app = App.get_running_app()
        r = app.db.q("SELECT * FROM records WHERE id=?", (rid,))[0]
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        status = Spinner(text=r["status"], values=["Bəli", "Xeyr"],
                         size_hint_y=None, height=dp(44))
        reason = TextInput(text=r["reason"] or "", hint_text="Səbəb",
                           size_hint_y=None, height=dp(44))
        p = Popup(title="Qeydi dəyiş", content=box, size_hint=(0.9, 0.5))

        def save(*a):
            app.db.run("UPDATE records SET status=?, reason=?, edited=1 WHERE id=?",
                       (status.text, reason.text.strip(), rid))
            p.dismiss()
            self.build()

        box.add_widget(status)
        box.add_widget(reason)
        box.add_widget(btn("Yadda saxla", save, size_hint_y=None, height=dp(44)))
        p.open()

    def export(self, *a):
        app = App.get_running_app()
        lines = ["Tel verməyənlər siyahısı", "Tarix | Qrup | Ad, soyad, ata adı | Səbəb | Qeyd edən", ""]
        for r in self.rows:
            if r["status"] != "Xeyr":
                continue
            lines.append(" | ".join([r["saved_at"], r["grp"], r["trainee_name"],
                                     r["reason"] or "", r["saved_by"]]))
        folder = "/sdcard/Download"
        if not os.path.isdir(folder):
            folder = app.user_data_dir
        path = os.path.join(folder, "xeyr_siyahisi.docx")
        try:
            make_docx(path, lines)
        except OSError as e:
            return info("Xəta", str(e))
        info("Hazırdır", "Fayl yadda saxlanıldı:\n" + path)


class TelApp(App):
    title = "Tel verən və verməyən"

    def build(self):
        self.db = DB(os.path.join(self.user_data_dir, "data.db"))
        self.user = None
        sm = ScreenManager()
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(MainScreen(name="main"))
        sm.add_widget(HistoryScreen(name="history"))
        sm.add_widget(AdminScreen(name="admin"))
        return sm


if __name__ == "__main__":
    TelApp().run()
