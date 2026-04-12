from flask import Flask, render_template, request, jsonify, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
import sqlite3, secrets

app = Flask(__name__)

# ──────────────────────────────────────────────
# DB
# ──────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect('db.sqlite3')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ward        TEXT,
            solution    TEXT,
            issue       TEXT,
            description TEXT,
            status      TEXT DEFAULT '접수대기',
            created_at  TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE complaints ADD COLUMN status TEXT DEFAULT '접수대기'")
    except:
        pass
    c.execute("UPDATE complaints SET status='접수대기' WHERE status='접수됨' OR status IS NULL")

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'nurse',
            access_key    TEXT UNIQUE,
            created_at    TEXT
        )
    ''')
    # access_key 컬럼이 없는 기존 DB 대응
    try:
        c.execute("ALTER TABLE users ADD COLUMN access_key TEXT UNIQUE")
    except:
        pass

    # 기존 계정에 access_key 없으면 발급
    c.execute("SELECT id FROM users WHERE access_key IS NULL")
    for row in c.fetchall():
        c.execute("UPDATE users SET access_key=? WHERE id=?",
                  (secrets.token_urlsafe(24), row['id']))

    # 기본 관리자 계정
    c.execute("SELECT id FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute('''
            INSERT INTO users (username, password_hash, role, access_key, created_at)
            VALUES (?, ?, 'admin', ?, ?)
        ''', ('admin', generate_password_hash('admin1234'),
              secrets.token_urlsafe(24),
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    conn.commit()
    conn.close()

init_db()

# ──────────────────────────────────────────────
# 키 기반 인증 헬퍼
# ──────────────────────────────────────────────

def get_user_by_key(key):
    """URL ?key= 또는 X-Access-Key 헤더로 사용자 조회"""
    if not key:
        return None
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE access_key=?", (key,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_request_key():
    return (request.args.get('key', '')
            or request.form.get('key', '')
            or request.headers.get('X-Access-Key', ''))

def require_role(role):
    """데코레이터: 특정 role 필요"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            key  = get_request_key()
            user = get_user_by_key(key)
            if not user:
                return redirect(url_for('login'))
            if user['role'] != role:
                # 잘못된 role → 로그인 페이지로
                return redirect(url_for('login',
                    hint='admin' if role == 'admin' else 'nurse'))
            # 현재 사용자를 함수에 주입
            kwargs['_user'] = user
            return f(*args, **kwargs)
        return decorated
    return decorator

def require_any_login(f):
    """데코레이터: 로그인만 되어 있으면 통과"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key  = get_request_key()
        user = get_user_by_key(key)
        if not user:
            return redirect(url_for('login'))
        kwargs['_user'] = user
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────────────────────────
# 공통
# ──────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    hint  = request.args.get('hint', '')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            key = user['access_key']
            if not key:
                # key 없으면 새로 발급
                key = secrets.token_urlsafe(24)
                conn = get_db()
                conn.execute("UPDATE users SET access_key=? WHERE id=?", (key, user['id']))
                conn.commit()
                conn.close()

            if user['role'] == 'admin':
                return redirect(f"/admin?key={key}")
            return redirect(f"/ward?key={key}")
        else:
            error = '아이디 또는 비밀번호가 올바르지 않습니다'

    return render_template('login.html', error=error, hint=hint)

# ──────────────────────────────────────────────
# 간호사 영역
# ──────────────────────────────────────────────

@app.route('/ward')
@require_role('nurse')
def ward_view(_user=None):
    key  = get_request_key()
    ward = _user['username']

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT id, ward, solution, issue, description, status, created_at
        FROM complaints WHERE ward=?
        ORDER BY id DESC
    ''', (ward,))
    complaints = [dict(row) for row in c.fetchall()]
    conn.close()

    solution_count = {}
    monthly_count  = {}
    status_count   = {'접수대기': 0, '처리중': 0, '완료': 0}
    for comp in complaints:
        sol  = comp['solution']
        st   = comp['status'] or '접수대기'
        date = (comp['created_at'] or '')[:7]
        solution_count[sol] = solution_count.get(sol, 0) + 1
        if date:
            monthly_count[date] = monthly_count.get(date, 0) + 1
        if st in status_count:
            status_count[st] += 1

    solution_count = dict(sorted(solution_count.items(), key=lambda x: x[1], reverse=True))

    return render_template('ward.html',
                           ward=ward, key=key,
                           complaints=complaints,
                           solution_count=solution_count,
                           monthly_count=monthly_count,
                           status_count=status_count)

@app.route('/api/submit', methods=['POST'])
@require_role('nurse')
def api_submit(_user=None):
    ward        = _user['username']
    solution    = request.form.get('solution', '')
    issue       = request.form.get('issue', '')
    description = request.form.get('description', '')

    if not solution or not issue:
        return jsonify({'success': False, 'error': '솔루션과 문제 유형은 필수입니다'}), 400

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO complaints (ward, solution, issue, description, status, created_at)
        VALUES (?, ?, ?, ?, '접수대기', ?)
    ''', (ward, solution, issue, description, now))
    conn.commit()
    complaint_id = c.lastrowid
    conn.close()

    return jsonify({'success': True, 'id': complaint_id,
                    'ward': ward, 'solution': solution,
                    'issue': issue, 'created_at': now[:16]})

# ──────────────────────────────────────────────
# 관리자 영역
# ──────────────────────────────────────────────

@app.route('/admin')
@require_role('admin')
def admin(_user=None):
    key = get_request_key()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints ORDER BY id DESC")
    data = [dict(row) for row in c.fetchall()]

    c.execute("SELECT id, username, access_key, created_at FROM users WHERE role='nurse' ORDER BY id DESC")
    accounts = [dict(row) for row in c.fetchall()]
    conn.close()

    total          = len(data)
    solution_count = {}
    monthly_count  = {}
    status_count   = {'접수대기': 0, '처리중': 0, '완료': 0}
    current_month  = datetime.now().strftime('%Y-%m')
    latest_month_count = 0

    ward_count = {}
    for row in data:
        sol    = row['solution']
        status = row['status'] or '접수대기'
        date   = (row['created_at'] or '')[:7]
        ward   = row['ward'] or '미지정'
        solution_count[sol]  = solution_count.get(sol, 0) + 1
        ward_count[ward]     = ward_count.get(ward, 0) + 1
        if date:
            monthly_count[date] = monthly_count.get(date, 0) + 1
        if status in status_count:
            status_count[status] += 1
        if date == current_month:
            latest_month_count += 1

    # 솔루션/병동 정렬 (많은 순)
    solution_count = dict(sorted(solution_count.items(), key=lambda x: x[1], reverse=True))
    ward_count     = dict(sorted(ward_count.items(),     key=lambda x: x[1], reverse=True))
    top_solution   = next(iter(solution_count), '-')

    return render_template('admin.html',
                           key=key,
                           data=data, total=total,
                           solution_count=solution_count,
                           monthly_count=monthly_count,
                           ward_count=ward_count,
                           top_solution=top_solution,
                           latest_month_count=latest_month_count,
                           status_count=status_count,
                           accounts=accounts)

@app.route('/action', methods=['POST'])
@require_role('admin')
def action(_user=None):
    complaint_id = request.form.get('id')
    act          = request.form.get('action')
    status_map   = {'accept': '처리중', 'complete': '완료'}
    new_status   = status_map.get(act)
    if not new_status:
        return jsonify({'success': False, 'error': 'invalid action'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE complaints SET status=? WHERE id=?", (new_status, complaint_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': complaint_id, 'status': new_status})

@app.route('/api/poll')
@require_role('admin')
def poll(_user=None):
    since = request.args.get('since', '')
    conn = get_db()
    c = conn.cursor()

    new_complaints = []
    if since:
        c.execute('''
            SELECT id, ward, solution, issue, created_at
            FROM complaints WHERE created_at > ?
            ORDER BY id DESC
        ''', (since,))
        new_complaints = [dict(row) for row in c.fetchall()]

    c.execute("SELECT status, COUNT(*) as cnt FROM complaints GROUP BY status")
    status_counts = {'접수대기': 0, '처리중': 0, '완료': 0}
    for row in c.fetchall():
        if row['status'] in status_counts:
            status_counts[row['status']] = row['cnt']

    c.execute("SELECT COUNT(*) as cnt FROM complaints")
    total = c.fetchone()['cnt']

    c.execute("SELECT created_at FROM complaints ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    latest_time = row['created_at'] if row else ''

    conn.close()
    return jsonify({'new_complaints': new_complaints,
                    'new_count': len(new_complaints),
                    'status_counts': status_counts,
                    'total': total,
                    'latest_time': latest_time})

# ──────────────────────────────────────────────
# 계정 관리 (admin)
# ──────────────────────────────────────────────

@app.route('/admin/accounts/add', methods=['POST'])
@require_role('admin')
def add_account(_user=None):
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        return jsonify({'success': False, 'error': '병동명과 비밀번호를 입력해주세요'}), 400

    new_key = secrets.token_urlsafe(24)
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (username, password_hash, role, access_key, created_at)
            VALUES (?, ?, 'nurse', ?, ?)
        ''', (username, generate_password_hash(password), new_key,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return jsonify({'success': True, 'id': user_id,
                        'username': username, 'access_key': new_key})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': '이미 존재하는 병동명입니다'}), 409

@app.route('/admin/accounts/delete', methods=['POST'])
@require_role('admin')
def delete_account(_user=None):
    user_id = request.form.get('id')
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=? AND role='nurse'", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/admin/accounts/reset', methods=['POST'])
@require_role('admin')
def reset_password(_user=None):
    user_id      = request.form.get('id')
    new_password = request.form.get('password', '').strip()
    if not new_password:
        return jsonify({'success': False, 'error': '새 비밀번호를 입력해주세요'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE id=? AND role='nurse'",
              (generate_password_hash(new_password), user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, port=5001)
