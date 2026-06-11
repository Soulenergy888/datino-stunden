#!/usr/bin/env python3
"""
DaTino Ristobar – Online Stundeneingabe
PostgreSQL (Railway) oder SQLite (lokal)
"""

import os, io, json
from datetime import date, datetime, timedelta
from flask import (Flask, request, redirect, url_for, render_template,
                   session, flash, send_file, jsonify)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'datino-geheim-2026')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'datino2026')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_PG = bool(DATABASE_URL)

MITARBEITER_INITIAL = [
    "Anxhela Kuci", "Parid Kuci", "Claudio Lorusso", "Alice Lumia",
    "Gayendra Kalhara Mcshane", "Hector Luis Nunez Pablo", "George Pavel",
    "Salvatore Petraroli", "Giuseppe Pilato", "Mihaela Plesa", "Ana-Maria Rus",
    "Ayad Ashraf Mahmoud Abdelghafar", "Anand Aditya Bhatt", "Salvatore Coluccio",
    "Jerome Gangabada Kanamge", "Georgiana Madalina Guta", "Obada Ioana-Veronica",
    "Achref Kadri", "Lennart Kramer",
]

# ── Datenbank ──────────────────────────────────────────────────────────────
def get_db():
    if USE_PG:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(os.environ.get('DB_PATH', 'stunden.db'))
        conn.row_factory = sqlite3.Row
        return conn

def db_execute(conn, sql, params=()):
    """Führt SQL aus (INSERT/UPDATE/DELETE/CREATE)."""
    if USE_PG:
        sql = sql.replace('?', '%s')
        sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        sql = sql.replace("datetime('now','localtime')", 'NOW()')
        sql = sql.replace('INSERT OR IGNORE', 'INSERT')
        # PostgreSQL: unique constraint verletzt → ignorieren
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e

def db_fetchall(conn, sql, params=()):
    """Gibt Liste von dicts zurück."""
    if USE_PG:
        import psycopg2.extras
        sql = sql.replace('?', '%s')
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def db_fetchone(conn, sql, params=()):
    rows = db_fetchall(conn, sql, params)
    return rows[0] if rows else None

def init_db():
    conn = get_db()
    try:
        if USE_PG:
            db_execute(conn, '''CREATE TABLE IF NOT EXISTS eintraege (
                id          SERIAL PRIMARY KEY,
                name        TEXT    NOT NULL,
                datum       TEXT    NOT NULL,
                beginn      TEXT    NOT NULL,
                ende        TEXT    NOT NULL,
                pause_min   INTEGER DEFAULT 0,
                bemerkungen TEXT    DEFAULT '',
                erstellt_am TIMESTAMP DEFAULT NOW()
            )''')
            db_execute(conn, '''CREATE TABLE IF NOT EXISTS mitarbeiter (
                id      SERIAL PRIMARY KEY,
                name    TEXT    NOT NULL UNIQUE,
                aktiv   INTEGER DEFAULT 1
            )''')
        else:
            db_execute(conn, '''CREATE TABLE IF NOT EXISTS eintraege (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                datum       TEXT    NOT NULL,
                beginn      TEXT    NOT NULL,
                ende        TEXT    NOT NULL,
                pause_min   INTEGER DEFAULT 0,
                bemerkungen TEXT    DEFAULT '',
                erstellt_am TEXT    DEFAULT (datetime('now','localtime'))
            )''')
            db_execute(conn, '''CREATE TABLE IF NOT EXISTS mitarbeiter (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL UNIQUE,
                aktiv   INTEGER DEFAULT 1
            )''')

        count = db_fetchone(conn, 'SELECT COUNT(*) as c FROM mitarbeiter')['c']
        if count == 0:
            for name in MITARBEITER_INITIAL:
                try:
                    db_execute(conn, 'INSERT INTO mitarbeiter (name) VALUES (?)', (name,))
                except Exception:
                    pass
    finally:
        conn.close()

init_db()

def get_mitarbeiter():
    conn = get_db()
    try:
        rows = db_fetchall(conn,
            "SELECT name FROM mitarbeiter WHERE aktiv=1 "
            "ORDER BY LOWER(TRIM(SUBSTRING(name FROM POSITION(' ' IN name)+1)))"
            if USE_PG else
            "SELECT name FROM mitarbeiter WHERE aktiv=1 "
            "ORDER BY LOWER(TRIM(SUBSTR(name, INSTR(name,' ')+1)))"
        )
        return [r['name'] for r in rows]
    finally:
        conn.close()

def netto_stunden(beginn, ende, pause_min):
    try:
        b = datetime.strptime(beginn, '%H:%M')
        e = datetime.strptime(ende,   '%H:%M')
        if e <= b: e += timedelta(hours=24)
        return round(max(0, (e-b).seconds/3600 - pause_min/60), 2)
    except Exception:
        return 0.0

# ── Mitarbeiter-Seite ──────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def eingabe():
    success = error = None
    if request.method == 'POST':
        name      = request.form.get('name','').strip()
        datum     = request.form.get('datum','')
        beginn    = request.form.get('beginn','')
        ende      = request.form.get('ende','')
        pause_min = int(request.form.get('pause_min',0) or 0)
        bemerk    = request.form.get('bemerkungen','').strip()
        if not all([name,datum,beginn,ende]):
            error = 'Bitte alle Pflichtfelder ausfüllen.'
        else:
            conn = get_db()
            try:
                db_execute(conn,
                    'INSERT INTO eintraege (name,datum,beginn,ende,pause_min,bemerkungen) VALUES (?,?,?,?,?,?)',
                    (name,datum,beginn,ende,pause_min,bemerk))
                netto = netto_stunden(beginn,ende,pause_min)
                success = f'✅ Gespeichert: {name}, {datum}, {beginn}–{ende} ({netto:.2f}h)'
            finally:
                conn.close()
    return render_template('eingabe.html', mitarbeiter=get_mitarbeiter(),
                           today=date.today().isoformat(), success=success, error=error)

# ── Admin Login ────────────────────────────────────────────────────────────
@app.route('/admin', methods=['GET','POST'])
def admin_login():
    if session.get('admin'): return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Falsches Passwort.')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# ── Admin Dashboard ────────────────────────────────────────────────────────
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    monat = request.args.get('monat', date.today().strftime('%Y-%m'))
    name  = request.args.get('name','')
    von   = monat+'-01'; bis = monat+'-31'
    conn  = get_db()
    try:
        if name:
            rows = db_fetchall(conn,
                'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? AND name=? ORDER BY datum,beginn',
                (von,bis,name))
        else:
            rows = db_fetchall(conn,
                'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? ORDER BY name,datum,beginn',
                (von,bis))
        monate = [r['substr'] if 'substr' in r else list(r.values())[0]
                  for r in db_fetchall(conn,
                    "SELECT DISTINCT SUBSTRING(datum,1,7) as substr FROM eintraege ORDER BY datum DESC"
                    if USE_PG else
                    "SELECT DISTINCT substr(datum,1,7) as substr FROM eintraege ORDER BY datum DESC")]
    finally:
        conn.close()
    eintraege = [{**r, 'netto': netto_stunden(r['beginn'],r['ende'],r['pause_min'])} for r in rows]
    return render_template('admin_dashboard.html',
                           eintraege=eintraege, gesamt=round(sum(e['netto'] for e in eintraege),2),
                           monat=monat, name_filter=name,
                           mitarbeiter=get_mitarbeiter(), monate=monate)

# ── Admin Edit ─────────────────────────────────────────────────────────────
@app.route('/admin/edit/<int:eid>', methods=['GET','POST'])
def admin_edit(eid):
    if not session.get('admin'): return redirect(url_for('admin_login'))
    conn = get_db()
    try:
        eintrag = db_fetchone(conn,'SELECT * FROM eintraege WHERE id=?',(eid,))
        if not eintrag:
            flash('Nicht gefunden.'); return redirect(url_for('admin_dashboard'))
        if request.method == 'POST':
            db_execute(conn,
                'UPDATE eintraege SET name=?,datum=?,beginn=?,ende=?,pause_min=?,bemerkungen=? WHERE id=?',
                (request.form.get('name'), request.form.get('datum'),
                 request.form.get('beginn'), request.form.get('ende'),
                 int(request.form.get('pause_min',0) or 0),
                 request.form.get('bemerkungen',''), eid))
            flash('✅ Gespeichert.')
            return redirect(url_for('admin_dashboard'))
    finally:
        conn.close()
    return render_template('admin_edit.html', e=eintrag, mitarbeiter=get_mitarbeiter())

# ── Admin Delete ───────────────────────────────────────────────────────────
@app.route('/admin/delete/<int:eid>', methods=['POST'])
def admin_delete(eid):
    if not session.get('admin'): return redirect(url_for('admin_login'))
    conn = get_db()
    try:
        db_execute(conn,'DELETE FROM eintraege WHERE id=?',(eid,))
    finally:
        conn.close()
    flash('Gelöscht.')
    return redirect(request.referrer or url_for('admin_dashboard'))

# ── Admin Mitarbeiter ──────────────────────────────────────────────────────
@app.route('/admin/mitarbeiter', methods=['GET','POST'])
def admin_mitarbeiter():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    if request.method == 'POST':
        aktion = request.form.get('aktion')
        conn = get_db()
        try:
            if aktion == 'add':
                name = request.form.get('name','').strip()
                if name:
                    try:
                        db_execute(conn,'INSERT INTO mitarbeiter (name) VALUES (?)',(name,))
                        flash(f'✅ {name} hinzugefügt.')
                    except Exception:
                        flash(f'⚠️ {name} existiert bereits.')
            elif aktion == 'toggle':
                db_execute(conn,'UPDATE mitarbeiter SET aktiv=1-aktiv WHERE id=?',(request.form.get('mid'),))
                flash('Aktualisiert.')
            elif aktion == 'delete':
                db_execute(conn,'DELETE FROM mitarbeiter WHERE id=?',(request.form.get('mid'),))
                flash('Gelöscht.')
        finally:
            conn.close()
        return redirect(url_for('admin_mitarbeiter'))

    conn = get_db()
    try:
        alle = db_fetchall(conn,
            "SELECT * FROM mitarbeiter ORDER BY LOWER(TRIM(SUBSTRING(name FROM POSITION(' ' IN name)+1)))"
            if USE_PG else
            "SELECT * FROM mitarbeiter ORDER BY LOWER(TRIM(SUBSTR(name, INSTR(name,' ')+1)))")
    finally:
        conn.close()
    return render_template('admin_mitarbeiter.html', mitarbeiter=alle)

# ── Admin Export ───────────────────────────────────────────────────────────
@app.route('/admin/export')
def admin_export():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    monat = request.args.get('monat', date.today().strftime('%Y-%m'))
    name  = request.args.get('name','')
    von   = monat+'-01'; bis = monat+'-31'
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        conn = get_db()
        try:
            if name:
                rows = db_fetchall(conn,'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? AND name=? ORDER BY datum',(von,bis,name))
            else:
                rows = db_fetchall(conn,'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? ORDER BY name,datum',(von,bis))
        finally:
            conn.close()

        wb = openpyxl.Workbook(); ws = wb.active; ws.title='Stunden'
        monat_name = datetime.strptime(monat+'-01','%Y-%m-%d').strftime('%B %Y')
        ws['A1'] = f'DaTino Ristobar – Stunden {monat_name}' + (f' – {name}' if name else '')
        ws['A1'].font = Font(bold=True, size=13)
        ws.merge_cells('A1:H1')
        headers = ['Name','Datum','Tag','Beginn','Ende','Pause (Min)','Netto-Std','Bemerkungen']
        WD = ['Mo','Di','Mi','Do','Fr','Sa','So']
        for col,h in enumerate(headers,1):
            c = ws.cell(row=3,column=col,value=h)
            c.font = Font(bold=True,color='FFFFFF')
            c.fill = PatternFill('solid',fgColor='1A3A5C')
            c.alignment = Alignment(horizontal='center')
        gesamt = 0
        for i,r in enumerate(rows,4):
            netto = netto_stunden(r['beginn'],r['ende'],r['pause_min'])
            gesamt += netto
            d = datetime.strptime(r['datum'],'%Y-%m-%d')
            ws.cell(row=i,column=1,value=r['name'])
            ws.cell(row=i,column=2,value=d.strftime('%d.%m.%Y'))
            ws.cell(row=i,column=3,value=WD[d.weekday()])
            ws.cell(row=i,column=4,value=r['beginn'])
            ws.cell(row=i,column=5,value=r['ende'])
            ws.cell(row=i,column=6,value=r['pause_min'])
            ws.cell(row=i,column=7,value=round(netto,2))
            ws.cell(row=i,column=8,value=r.get('bemerkungen','') or '')
        row_sum = len(rows)+4
        ws.cell(row=row_sum+1,column=6,value='Gesamt:').font=Font(bold=True)
        ws.cell(row=row_sum+1,column=7,value=round(gesamt,2)).font=Font(bold=True)
        for col,w in zip('ABCDEFGH',[22,14,6,8,8,12,12,25]):
            ws.column_dimensions[col].width=w
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        fname = f'DaTino_Stunden_{monat}{"_"+name.replace(" ","_") if name else ""}.xlsx'
        return send_file(buf,as_attachment=True,download_name=fname,
                        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f'Fehler: {e}'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/json')
def admin_json():
    if not session.get('admin'): return jsonify({'error':'Nicht angemeldet'}),401
    monat = request.args.get('monat',date.today().strftime('%Y-%m'))
    name  = request.args.get('name','')
    von   = monat+'-01'; bis = monat+'-31'
    conn  = get_db()
    try:
        q = 'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ?'
        p = [von,bis]
        if name: q+=' AND name=?'; p.append(name)
        rows = db_fetchall(conn,q+' ORDER BY name,datum',p)
    finally:
        conn.close()
    for r in rows:
        r['netto'] = netto_stunden(r['beginn'],r['ende'],r['pause_min'])
        if isinstance(r.get('erstellt_am'), datetime):
            r['erstellt_am'] = r['erstellt_am'].isoformat()
    return jsonify(rows)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
