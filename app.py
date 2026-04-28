from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from datetime import datetime
from functools import wraps
import psycopg2
import psycopg2.extras
import os
import secrets
import socket
from dotenv import load_dotenv

load_dotenv()

# COOKIE_SECURE=true 인 경우에만 쿠키에 Secure 플래그 부여 (HTTPS 운영 시)
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'false').lower() == 'true'

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7일
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = COOKIE_SECURE

# ──────────────────────────────────────────────
# Flask-Login 설정
# ──────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요합니다.'

# ──────────────────────────────────────────────
# 병동(nurse) 전용 쿠키 인증 (ward_session)
# 관리자 Flask-Login 세션과 완전히 분리되어
# 같은 브라우저에서 동시에 admin + nurse 사용 가능
# ──────────────────────────────────────────────

_ward_serializer = URLSafeTimedSerializer(
    app.secret_key, salt='ward-session-salt'
)

def _cookie_name(ward_name):
    """병동별 고유 쿠키 이름 반환 — ward_session_병동명"""
    return f'ward_session_{ward_name}'

def _set_ward_cookie(response, username, user_id, ward, csrf_token):
    """ward 기준 쿠키 이름으로 서명 토큰 설정.
    토큰에 사번(u)·id(i)·병동(w)·CSRF 토큰(c) 포함."""
    token = _ward_serializer.dumps({
        'u': username, 'i': user_id, 'w': ward, 'c': csrf_token
    })
    response.set_cookie(
        _cookie_name(ward), token,
        max_age=86400 * 7,
        httponly=True,
        samesite='Lax',
        secure=COOKIE_SECURE
    )
    return response

def _get_ward_user(ward_name):
    """ward_session_<ward_name> 쿠키를 검증해 사용자 정보를 반환.
    반환값: {'username': 사번, 'id': DB id, 'ward': 소속병동, 'csrf': CSRF 토큰}"""
    token = request.cookies.get(_cookie_name(ward_name))
    if not token:
        return None
    try:
        data = _ward_serializer.loads(token, max_age=86400 * 7)
        return {
            'username': data['u'],
            'id':       data['i'],
            'ward':     data.get('w', ward_name),  # 구버전 쿠키 호환
            'csrf':     data.get('c', '')          # 구버전 쿠키엔 없음
        }
    except (BadSignature, SignatureExpired):
        return None

def require_ward(f):
    """병동 전용 라우트 보호 데코레이터.
    URL 파라미터 ward_name 또는 폼 필드 ward 로 어느 병동 쿠키를 확인할지 결정."""
    @wraps(f)
    def decorated(*args, **kwargs):
        ward_name = kwargs.get('ward_name') or request.form.get('ward', '')
        is_api = request.path.startswith('/api/')
        if not ward_name:
            if is_api:
                return jsonify({'success': False, 'error': '병동 정보가 없습니다.'}), 400
            return redirect(url_for('login'))
        ward_user = _get_ward_user(ward_name)
        if not ward_user:
            if is_api:
                return jsonify({'success': False,
                                'error': '로그인이 필요합니다. 페이지를 새로고침해주세요.'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = get_db()
        try:
            with conn.cursor() as c:
                c.execute("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
                row = c.fetchone()
            return User(row['id'], row['username'], row['role']) if row else None
        finally:
            conn.close()
    except Exception:
        return None

# ──────────────────────────────────────────────
# DB (PostgreSQL)
# ──────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(
        os.environ.get('DATABASE_URL'),
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    return conn

def init_db():
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute('''
                CREATE TABLE IF NOT EXISTS complaints (
                    id           SERIAL PRIMARY KEY,
                    ward         TEXT,
                    solution     TEXT,
                    issue        TEXT,
                    description  TEXT,
                    status       TEXT DEFAULT '접수대기',
                    submitted_by TEXT,
                    message      TEXT,
                    created_at   TEXT
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'nurse',
                    ward          TEXT,
                    created_at    TEXT
                )
            ''')
            # 기존 DB 컬럼 추가 (이미 있으면 무시)
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ward TEXT")
            c.execute("ALTER TABLE complaints ADD COLUMN IF NOT EXISTS submitted_by TEXT")
            c.execute("ALTER TABLE complaints ADD COLUMN IF NOT EXISTS message TEXT")
            # 기존 nurse 계정 마이그레이션: ward = username (병동명이 곧 ID였던 구조)
            c.execute("""
                UPDATE users SET ward = username
                WHERE role = 'nurse' AND ward IS NULL
            """)
            # 기본 관리자 계정
            c.execute("SELECT id FROM users WHERE username='admin'")
            if not c.fetchone():
                c.execute('''
                    INSERT INTO users (username, password_hash, role, created_at)
                    VALUES (%s, %s, 'admin', %s)
                ''', ('admin',
                       generate_password_hash(os.environ['ADMIN_PASSWORD']),
                       datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    finally:
        conn.close()

init_db()

# ──────────────────────────────────────────────
# CSRF 보호
#   - admin: Flask 세션에 토큰 보관
#   - ward : 서명된 ward 쿠키 페이로드에 토큰 포함
#   - 검증: X-CSRF-Token 헤더 또는 _csrf 폼 필드
# ──────────────────────────────────────────────

def _ensure_admin_csrf():
    """관리자 세션에 CSRF 토큰이 없으면 생성."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def _request_csrf_token():
    return request.headers.get('X-CSRF-Token', '') or request.form.get('_csrf', '')

def csrf_protect(scope):
    """scope: 'admin' 또는 'ward'."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            submitted = _request_csrf_token()
            if scope == 'admin':
                expected = session.get('csrf_token', '')
            else:  # ward
                ward_name = kwargs.get('ward_name') or request.form.get('ward', '')
                ward_user = _get_ward_user(ward_name) if ward_name else None
                expected = (ward_user or {}).get('csrf', '')
            if not expected or not submitted or not secrets.compare_digest(submitted, expected):
                return jsonify({'success': False,
                                'error': '세션이 만료되었습니다. 페이지를 새로고침해주세요.'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

# ──────────────────────────────────────────────
# Role 체크 데코레이터
# ──────────────────────────────────────────────

def require_role(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            is_api = (request.path.startswith('/api/') or
                      request.path == '/action' or
                      request.path.startswith('/admin/accounts/'))
            if not current_user.is_authenticated:
                if is_api:
                    return jsonify({'success': False, 'error': '로그인이 필요합니다. 페이지를 새로고침해주세요.'}), 401
                return redirect(url_for('login'))
            if current_user.role != role:
                if is_api:
                    return jsonify({'success': False, 'error': f'{role} 권한이 필요합니다. 올바른 계정으로 로그인해주세요.'}), 403
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ──────────────────────────────────────────────
# 공통
# ──────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # 이미 로그인 중이어도 항상 로그인 폼 표시 (계정 전환 가능)
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db()
        try:
            with conn.cursor() as c:
                c.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = c.fetchone()
        finally:
            conn.close()

        if user and check_password_hash(user['password_hash'], password):
            if user['role'] == 'admin':
                # 관리자: Flask-Login 세션 사용 (기존 방식 유지)
                logout_user()
                user_obj = User(user['id'], user['username'], user['role'])
                login_user(user_obj, remember=True)
                session.permanent = True
                session['csrf_token'] = secrets.token_hex(32)
                return redirect(url_for('admin'))
            else:
                # 간호사: 병동별 쿠키 사용 (Flask-Login 세션에 영향 없음)
                # ward 컬럼 = 소속 병동 (EMR 연동 시 EMR에서 받아온 값으로 대체)
                ward = user['ward'] or user['username']  # 마이그레이션 전 계정 fallback
                csrf_token = secrets.token_hex(32)
                resp = make_response(redirect(url_for('ward_view', ward_name=ward)))
                _set_ward_cookie(resp, user['username'], user['id'], ward, csrf_token)
                return resp
        else:
            error = '아이디 또는 비밀번호가 올바르지 않습니다'

    return render_template('login.html', error=error)

@app.route('/logout')
@login_required
def logout():
    """관리자(Flask-Login) 로그아웃"""
    logout_user()
    return redirect(url_for('login'))

@app.route('/ward/<ward_name>/logout')
def ward_logout(ward_name):
    """해당 병동 쿠키만 삭제 — 다른 병동·관리자 세션에 영향 없음"""
    resp = make_response(redirect(url_for('login')))
    resp.delete_cookie(_cookie_name(ward_name))
    return resp

# ──────────────────────────────────────────────
# 간호사 영역
# ──────────────────────────────────────────────

@app.route('/ward/<ward_name>')
@require_ward
def ward_view(ward_name):
    ward_user = _get_ward_user(ward_name)
    ward = ward_user['ward']                   # ← ['ward'] 사용 (사번 ≠ 병동명)

    # 구버전 쿠키(CSRF 토큰 없음) 자동 업그레이드
    csrf_token = ward_user['csrf']
    needs_refresh = not csrf_token
    if needs_refresh:
        csrf_token = secrets.token_hex(32)

    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute('''
                SELECT id, ward, solution, issue, description, status, message, created_at
                FROM complaints WHERE ward=%s ORDER BY id DESC
            ''', (ward,))
            complaints = [dict(r) for r in c.fetchall()]
    finally:
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

    resp = make_response(render_template('ward.html',
                           ward=ward,
                           complaints=complaints,
                           solution_count=solution_count,
                           monthly_count=monthly_count,
                           status_count=status_count,
                           csrf_token=csrf_token))
    if needs_refresh:
        _set_ward_cookie(resp, ward_user['username'], ward_user['id'], ward, csrf_token)
    return resp

@app.route('/api/ward_poll/<ward_name>')
@require_ward
def ward_poll(ward_name):
    """병동 페이지 전용 폴링 — 상태 + 담당자 메시지 반환 (3초 간격)"""
    ward = _get_ward_user(ward_name)['ward']   # ← ['ward'] 사용
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(
                "SELECT id, status, message FROM complaints WHERE ward=%s",
                (ward,)
            )
            rows = c.fetchall()
            statuses = {str(r['id']): (r['status'] or '접수대기') for r in rows}
            messages = {str(r['id']): r['message']
                        for r in rows if r['message']}
    finally:
        conn.close()
    return jsonify({'statuses': statuses, 'messages': messages})

@app.route('/api/submit', methods=['POST'])
@require_ward
@csrf_protect('ward')
def api_submit():
    ward_name    = request.form.get('ward', '')
    ward_user    = _get_ward_user(ward_name)
    ward         = ward_user['ward']          # 소속 병동 (complaints.ward)
    submitted_by = ward_user['username']      # 접수한 개인 계정 (사번 또는 병동명)
    solution     = request.form.get('solution', '')
    issue        = request.form.get('issue', '')
    description  = request.form.get('description', '')

    if not solution or not issue:
        return jsonify({'success': False, 'error': '솔루션과 문제 유형은 필수입니다'}), 400

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute('''
                INSERT INTO complaints (ward, solution, issue, description, status, submitted_by, created_at)
                VALUES (%s, %s, %s, %s, '접수대기', %s, %s) RETURNING id
            ''', (ward, solution, issue, description, submitted_by, now))
            complaint_id = c.fetchone()['id']
        conn.commit()
    finally:
        conn.close()

    return jsonify({'success': True, 'id': complaint_id,
                    'ward': ward, 'solution': solution,
                    'issue': issue, 'created_at': now[:16]})

# ──────────────────────────────────────────────
# 관리자 영역
# ──────────────────────────────────────────────

@app.route('/admin')
@require_role('admin')
def admin():
    _ensure_admin_csrf()  # 구세션 호환: 토큰 없으면 발급
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM complaints ORDER BY id DESC")
            data = [dict(r) for r in c.fetchall()]
            c.execute("SELECT id, username, ward, created_at FROM users WHERE role='nurse' ORDER BY id DESC")
            accounts = [dict(r) for r in c.fetchall()]
    finally:
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

    solution_count = dict(sorted(solution_count.items(), key=lambda x: x[1], reverse=True))
    ward_count     = dict(sorted(ward_count.items(),     key=lambda x: x[1], reverse=True))
    top_solution   = next(iter(solution_count), '-')

    return render_template('admin.html',
                           data=data, total=total,
                           solution_count=solution_count,
                           monthly_count=monthly_count,
                           ward_count=ward_count,
                           top_solution=top_solution,
                           latest_month_count=latest_month_count,
                           status_count=status_count,
                           accounts=accounts,
                           csrf_token=session['csrf_token'])

@app.route('/action', methods=['POST'])
@require_role('admin')
@csrf_protect('admin')
def action():
    complaint_id = request.form.get('id')
    act          = request.form.get('action')
    message      = request.form.get('message', '').strip()  # 관리자 → 병동 메시지 (선택)
    status_map   = {'accept': '처리중', 'complete': '완료'}
    new_status   = status_map.get(act)
    if not new_status:
        return jsonify({'success': False, 'error': 'invalid action'}), 400

    conn = get_db()
    try:
        with conn.cursor() as c:
            if message:
                c.execute("UPDATE complaints SET status=%s, message=%s WHERE id=%s",
                          (new_status, message, complaint_id))
            else:
                c.execute("UPDATE complaints SET status=%s WHERE id=%s",
                          (new_status, complaint_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True, 'id': complaint_id,
                    'status': new_status, 'message': message})

@app.route('/api/poll')
@require_role('admin')
def poll():
    since = request.args.get('since', '')
    conn = get_db()
    try:
        with conn.cursor() as c:
            new_complaints = []
            if since:
                c.execute('''
                    SELECT id, ward, solution, issue, created_at
                    FROM complaints WHERE created_at > %s ORDER BY id DESC
                ''', (since,))
                new_complaints = [dict(r) for r in c.fetchall()]

            c.execute("SELECT status, COUNT(*) as cnt FROM complaints GROUP BY status")
            status_counts = {'접수대기': 0, '처리중': 0, '완료': 0}
            for row in c.fetchall():
                st = row['status'] or '접수대기'  # NULL → 접수대기로 취급
                if st in status_counts:
                    status_counts[st] += row['cnt']

            c.execute("SELECT COUNT(*) as cnt FROM complaints")
            total = c.fetchone()['cnt']

            c.execute("SELECT created_at FROM complaints ORDER BY id DESC LIMIT 1")
            row = c.fetchone()
            latest_time = row['created_at'] if row else ''
    finally:
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
@csrf_protect('admin')
def add_account():
    username = request.form.get('username', '').strip()  # 사번 또는 병동명
    ward     = request.form.get('ward', '').strip()      # 소속 병동 (비어있으면 username과 동일)
    password = request.form.get('password', '').strip()

    if not username or not password:
        return jsonify({'success': False, 'error': '아이디와 비밀번호를 입력해주세요'}), 400

    if not ward:
        ward = username  # 병동 계정 방식 호환: ward 미입력 시 username = ward

    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute('''
                INSERT INTO users (username, password_hash, role, ward, created_at)
                VALUES (%s, %s, 'nurse', %s, %s) RETURNING id
            ''', (username, generate_password_hash(password), ward,
                   datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            user_id = c.fetchone()['id']
        conn.commit()
        return jsonify({'success': True, 'id': user_id, 'username': username, 'ward': ward})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'success': False, 'error': '이미 존재하는 병동명입니다'}), 409
    finally:
        conn.close()

@app.route('/admin/accounts/delete', methods=['POST'])
@require_role('admin')
@csrf_protect('admin')
def delete_account():
    user_id = request.form.get('id')
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM users WHERE id=%s AND role='nurse'", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/admin/accounts/reset', methods=['POST'])
@require_role('admin')
@csrf_protect('admin')
def reset_password():
    user_id      = request.form.get('id')
    new_password = request.form.get('password', '').strip()
    if not new_password:
        return jsonify({'success': False, 'error': '새 비밀번호를 입력해주세요'}), 400

    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("UPDATE users SET password_hash=%s WHERE id=%s AND role='nurse'",
                      (generate_password_hash(new_password), user_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'success': True})

def _get_lan_ip():
    """같은 네트워크에서 접속할 때 쓸 LAN IP 주소 반환. 실패 시 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()

if __name__ == '__main__':
    port = 5001
    lan_ip = _get_lan_ip()
    print('\n' + '=' * 50)
    print(' Smart Solution Dashboard 실행 중')
    print('=' * 50)
    print(f'  로컬:       http://127.0.0.1:{port}')
    print(f'  같은 네트워크: http://{lan_ip}:{port}')
    print('=' * 50 + '\n')
    app.run(host='0.0.0.0', debug=False, port=port)
