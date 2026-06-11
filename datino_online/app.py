#!/usr/bin/env python3
"""
DaTino Ristobar – Online Stundeneingabe
Mitarbeiter tragen Schichten online ein, Manager sieht und exportiert alles.
"""

import os, sqlite3, io, json
from datetime import date, datetime, timedelta
from flask import (Flask, request, redirect, url_for, render_template,
                   session, flash, send_file, jsonify)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'datino-geheim-2026')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'datino2026')
DB_PATH = os.environ.get('DB_PATH', 'stunden.db')

# ── Mitarbeiter-Liste ───────────────────────────────────────────────────────
MITARBEITER = [
    "Arand", "Anxhela Kuci", "Claudio Dorozzo", "DPAGO",
    "George Pavel", "Hector Luis", "Kuci Parid", "Max McShein",
    "Plesa Michaela", "Salvatore", "Salvatore Colucci", "Veronica",
    "Ana Rus", "Ache",
]

# ── Datenbank ───────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS eintraege (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            datum       TEXT    NOT NULL,
            beginn      TEXT    NOT NULL,
            ende        TEXT    NOT NULL,
            pause_min   INTEGER DEFAULT 0,
            bemerkungen TEXT    DEFAULT '',
            erstellt_am TEXT    DEFAULT (datetime('now','localtime'))
        )''')
        conn.commit()

init_db()

def netto_stunden(beginn, ende, pause_min):
    try:
        b = datetime.strptime(beginn, '%H:%M')
        e = datetime.strptime(ende,   '%H:%M')
        if e <= b: e += timedelta(hours=24)
        netto = (e - b).seconds / 3600 - pause_min / 60
        return round(max(0, netto), 2)
    except Exception:
        return 0.0

# ── Mitarbeiter-Seite ────────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def eingabe():
    success = None
    error   = None

    if request.method == 'POST':
        name      = request.form.get('name', '').strip()
        datum     = request.form.get('datum', '')
        beginn    = request.form.get('beginn', '')
        ende      = request.form.get('ende', '')
        pause_min = int(request.form.get('pause_min', 0) or 0)
        bemerk    = request.form.get('bemerkungen', '').strip()

        if not all([name, datum, beginn, ende]):
            error = 'Bitte alle Pflichtfelder ausfüllen.'
        else:
            with get_db() as conn:
                conn.execute(
                    'INSERT INTO eintraege (name,datum,beginn,ende,pause_min,bemerkungen) '
                    'VALUES (?,?,?,?,?,?)',
                    (name, datum, beginn, ende, pause_min, bemerk)
                )
                conn.commit()
            netto = netto_stunden(beginn, ende, pause_min)
            success = f'✅ Eintrag gespeichert: {name}, {datum}, {beginn}–{ende} ({netto:.2f}h)'

    today = date.today().isoformat()
    return render_template('eingabe.html',
                           mitarbeiter=MITARBEITER,
                           today=today,
                           success=success,
                           error=error)

# ── Admin: Login ─────────────────────────────────────────────────────────────
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin'):
        return redirect(url_for('admin_dashboard'))
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

# ── Admin: Dashboard ──────────────────────────────────────────────────────────
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    monat  = request.args.get('monat', date.today().strftime('%Y-%m'))
    name   = request.args.get('name', '')
    von    = monat + '-01'
    bis    = monat + '-31'

    with get_db() as conn:
        if name:
            rows = conn.execute(
                'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? AND name=? ORDER BY datum,beginn',
                (von, bis, name)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? ORDER BY name,datum,beginn',
                (von, bis)
            ).fetchall()

    eintraege = []
    for r in rows:
        netto = netto_stunden(r['beginn'], r['ende'], r['pause_min'])
        eintraege.append({**dict(r), 'netto': netto})

    gesamt = round(sum(e['netto'] for e in eintraege), 2)

    # Alle Monate mit Daten
    with get_db() as conn:
        monate = [r[0] for r in conn.execute(
            "SELECT DISTINCT substr(datum,1,7) FROM eintraege ORDER BY datum DESC"
        ).fetchall()]

    return render_template('admin_dashboard.html',
                           eintraege=eintraege,
                           gesamt=gesamt,
                           monat=monat,
                           name_filter=name,
                           mitarbeiter=MITARBEITER,
                           monate=monate)

# ── Admin: Eintrag löschen ────────────────────────────────────────────────────
@app.route('/admin/delete/<int:eid>', methods=['POST'])
def admin_delete(eid):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    with get_db() as conn:
        conn.execute('DELETE FROM eintraege WHERE id=?', (eid,))
        conn.commit()
    flash('Eintrag gelöscht.')
    return redirect(request.referrer or url_for('admin_dashboard'))

# ── Admin: Excel-Export (Stundenliste) ────────────────────────────────────────
@app.route('/admin/export')
def admin_export():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    monat = request.args.get('monat', date.today().strftime('%Y-%m'))
    name  = request.args.get('name', '')
    von   = monat + '-01'
    bis   = monat + '-31'

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        with get_db() as conn:
            if name:
                rows = conn.execute(
                    'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? AND name=? ORDER BY datum',
                    (von, bis, name)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ? ORDER BY name,datum',
                    (von, bis)
                ).fetchall()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Stunden'

        # Header
        monat_name = datetime.strptime(monat + '-01', '%Y-%m-%d').strftime('%B %Y')
        titel = f'DaTino Ristobar – Stunden {monat_name}'
        if name: titel += f' – {name}'
        ws['A1'] = titel
        ws['A1'].font = Font(bold=True, size=13)
        ws.merge_cells('A1:H1')

        headers = ['Name','Datum','Tag','Beginn','Ende','Pause (Min)','Netto-Std','Bemerkungen']
        WOCHENTAGE = ['Mo','Di','Mi','Do','Fr','Sa','So']
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=h)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='1A3A5C')
            cell.alignment = Alignment(horizontal='center')

        row_nr = 4
        gesamt = 0
        for r in rows:
            netto = netto_stunden(r['beginn'], r['ende'], r['pause_min'])
            gesamt += netto
            datum_obj = datetime.strptime(r['datum'], '%Y-%m-%d')
            ws.cell(row=row_nr, column=1, value=r['name'])
            ws.cell(row=row_nr, column=2, value=datum_obj.strftime('%d.%m.%Y'))
            ws.cell(row=row_nr, column=3, value=WOCHENTAGE[datum_obj.weekday()])
            ws.cell(row=row_nr, column=4, value=r['beginn'])
            ws.cell(row=row_nr, column=5, value=r['ende'])
            ws.cell(row=row_nr, column=6, value=r['pause_min'])
            ws.cell(row=row_nr, column=7, value=round(netto, 2))
            ws.cell(row=row_nr, column=8, value=r['bemerkungen'] or '')
            row_nr += 1

        # Summe
        ws.cell(row=row_nr+1, column=6, value='Gesamt:').font = Font(bold=True)
        ws.cell(row=row_nr+1, column=7, value=round(gesamt, 2)).font = Font(bold=True)

        # Spaltenbreiten
        for col, w in zip('ABCDEFGH', [22,14,6,8,8,12,12,25]):
            ws.column_dimensions[col].width = w

        buf = io.BytesIO()
        wb.save(buf); buf.seek(0)
        fname = f'DaTino_Stunden_{monat}{"_"+name.replace(" ","_") if name else ""}.xlsx'
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        flash(f'Export-Fehler: {e}')
        return redirect(url_for('admin_dashboard'))

# ── Admin: JSON-Export (für Weiterverarbeitung) ───────────────────────────────
@app.route('/admin/json')
def admin_json():
    if not session.get('admin'):
        return jsonify({'error': 'Nicht angemeldet'}), 401
    monat = request.args.get('monat', date.today().strftime('%Y-%m'))
    name  = request.args.get('name', '')
    von = monat+'-01'; bis = monat+'-31'
    with get_db() as conn:
        q = 'SELECT * FROM eintraege WHERE datum BETWEEN ? AND ?'
        params = [von, bis]
        if name: q += ' AND name=?'; params.append(name)
        rows = conn.execute(q + ' ORDER BY name,datum', params).fetchall()
    data = [dict(r) for r in rows]
    for d in data:
        d['netto'] = netto_stunden(d['beginn'], d['ende'], d['pause_min'])
    return jsonify(data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
