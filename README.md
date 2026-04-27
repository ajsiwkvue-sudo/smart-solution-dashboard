# Smart Solution Dashboard

> 병동 민원 접수 및 관리 대시보드  
> Repository: https://github.com/ajsiwkvue-sudo/smart-solution-dashboard

---

## 프로젝트 개요

스마트솔루션별 병동 민원 접수 및 처리 현황 관리 웹 애플리케이션.  
간호사(병동별 계정)가 민원을 접수하면 관리자 페이지에 **3초 이내 실시간 알림**이 전달되고, 관리자가 처리 상태를 업데이트하는 구조.

같은 브라우저에서 관리자 탭 + 여러 병동 탭을 동시에 열어도 세션이 충돌하지 않습니다.

**역할:**
- `nurse` — 병동별 계정. 민원 접수 및 본인 병동 현황 조회
- `admin` — 전체 민원 현황 조회, 상태 변경, 계정 관리

---

## Tech Stack

| Layer      | Technology                                          |
|------------|-----------------------------------------------------|
| Backend    | Python 3.x + Flask                                  |
| Database   | PostgreSQL (psycopg2-binary)                        |
| Auth-Admin | Flask-Login (서버 세션 쿠키, 7일 유지)               |
| Auth-Nurse | itsdangerous 서명 쿠키 `ward_session_{병동명}` (7일) |
| Password   | `werkzeug.security` (PBKDF2 hashing)                |
| Frontend   | Jinja2 + Vanilla JS + Fetch API                     |
| Charts     | Chart.js (월별 bar chart)                           |
| Styling    | CSS Grid / Flexbox (외부 라이브러리 없음)             |
| WSGI       | Gunicorn                                            |
| Proxy      | Nginx                                               |

---

## 설치 & 실행

### Windows PC에서 테스트 실행

병동/관리자 PC에서 직접 설치해서 테스트할 때 사용합니다.

#### 1. 필수 프로그램 설치

| 프로그램 | 다운로드 |
|----------|----------|
| Python 3.8+ | https://python.org → Downloads → Windows |
| Git | https://git-scm.com → Downloads → Windows |
| PostgreSQL 15 | https://postgresql.org → Downloads → Windows |

> Python 설치 시 **"Add Python to PATH"** 반드시 체크

#### 2. 저장소 클론

CMD(명령 프롬프트)를 열고:

```cmd
git clone https://github.com/ajsiwkvue-sudo/smart-solution-dashboard.git
cd smart-solution-dashboard
```

#### 3. 의존성 설치

```cmd
pip install -r requirements.txt
```

#### 4. PostgreSQL 데이터베이스 생성

PostgreSQL 설치 시 설정한 postgres 비밀번호로 접속:

```cmd
psql -U postgres
```

```sql
CREATE DATABASE smartsolution OWNER postgres;
\q
```

#### 5. .env 파일 생성

프로젝트 폴더 안에 `.env` 파일을 메모장으로 생성:

```env
SECRET_KEY=랜덤문자열아무거나32자이상
DATABASE_URL=postgresql://postgres:postgres비밀번호@localhost:5432/smartsolution
ADMIN_PASSWORD=관리자비밀번호
```

`SECRET_KEY` 생성하려면 CMD에서:
```cmd
python -c "import secrets; print(secrets.token_hex(32))"
```

#### 6. 실행

```cmd
python app.py
```

실행 시 콘솔에 두 개의 주소가 출력됩니다:

```
로컬:       http://127.0.0.1:5001
같은 네트워크: http://192.168.x.x:5001   ← 같은 와이파이/망에서 접속 가능
```

같은 PC: `http://127.0.0.1:5001`
다른 PC(같은 네트워크): 출력된 `http://192.168.x.x:5001` 주소로 접속

> Windows 방화벽이 켜져 있으면 최초 실행 시 Python의 수신 연결 허용 창이 뜹니다 — "허용" 선택

---

### Mac / Linux에서 개발 실행

#### 요구사항

```
Python 3.8+
PostgreSQL 14+
```

#### 1. 저장소 클론

```bash
git clone https://github.com/ajsiwkvue-sudo/smart-solution-dashboard.git
cd smart-solution-dashboard
```

#### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

#### 3. PostgreSQL 데이터베이스 생성

```bash
psql postgres
```

```sql
CREATE USER smartuser WITH PASSWORD '비밀번호';
CREATE DATABASE smartsolution OWNER smartuser;
\q
```

#### 4. 환경변수 설정

`.env` 파일 생성:

```env
SECRET_KEY=랜덤32자이상문자열
DATABASE_URL=postgresql://smartuser:비밀번호@localhost:5432/smartsolution
ADMIN_PASSWORD=관리자비밀번호
```

`SECRET_KEY` 생성:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

#### 5. 실행

개발:
```bash
python app.py
```

프로덕션 (Gunicorn):
```bash
gunicorn -w 2 -b 0.0.0.0:5001 wsgi:app
```

`python app.py` 실행 시 콘솔에 로컬/네트워크 주소가 출력됩니다:

```
로컬:       http://127.0.0.1:5001
같은 네트워크: http://192.168.x.x:5001
```

- 같은 PC: `http://127.0.0.1:5001`
- 같은 와이파이/망의 다른 기기: 출력된 `http://192.168.x.x:5001`
- macOS는 최초 실행 시 방화벽이 수신 연결 허용을 묻습니다 → "허용"

---

## 기본 관리자 계정

| 항목 | 값 |
|------|-----|
| ID | `admin` |
| PW | `.env`의 `ADMIN_PASSWORD` 값 (필수 — 미설정 시 서버 시작 실패) |

> **최초 로그인 후 반드시 비밀번호 변경 권장**

---

## 병동 계정 추가 방법

1. admin 계정으로 로그인
2. 관리자 페이지 → `계정 관리` 탭
3. 병동명(ID) + 초기 비밀번호 입력 후 추가
4. 해당 병동 PC에서 `/login` 접속 후 로그인

---

## 다중 계정 동시 접속

같은 Chrome 브라우저에서 admin + 복수의 병동 탭을 동시에 열 수 있습니다.

- **관리자**: Flask-Login 세션 쿠키 사용
- **병동 A**: `ward_session_병동A` 쿠키 사용
- **병동 B**: `ward_session_병동B` 쿠키 사용

쿠키 이름이 각각 달라 서로 덮어쓰지 않습니다.

---

## API 엔드포인트

| Method | Endpoint | Auth | 설명 |
|--------|----------|------|------|
| GET | `/` | — | 로그인 페이지로 리다이렉트 |
| GET/POST | `/login` | — | 로그인 |
| GET | `/ward/<ward_name>` | nurse | 간호사 대시보드 |
| GET | `/ward/<ward_name>/logout` | nurse | 병동 로그아웃 |
| POST | `/api/submit` | nurse | 민원 접수 (폼: solution, issue, description, ward) |
| GET | `/admin` | admin | 관리자 대시보드 |
| GET | `/logout` | admin | 관리자 로그아웃 |
| POST | `/action` | admin | 민원 상태 변경 |
| GET | `/api/poll` | admin | 신규 민원 폴링 (3초 간격) |
| POST | `/admin/accounts/add` | admin | 병동 계정 추가 |
| POST | `/admin/accounts/delete` | admin | 병동 계정 삭제 |
| POST | `/admin/accounts/reset` | admin | 비밀번호 재설정 |

---

## 파일 구조

```
smart-solution-dashboard/
├── app.py                   # Flask 애플리케이션 (라우트, DB, 인증)
├── wsgi.py                  # Gunicorn 진입점
├── requirements.txt
├── .env.example             # 환경변수 템플릿 (`.env`로 복사 후 값 입력)
├── templates/
│   ├── login.html           # 로그인 페이지
│   ├── admin.html           # 관리자 대시보드
│   └── ward.html            # 간호사(병동) 대시보드
├── deploy/
│   ├── nginx.conf           # Nginx 리버스 프록시 설정
│   └── smartsolution.service # systemd 서비스 파일
├── CHANGELOG.md
└── README.md
```

---

## 온프레미스 배포 (Linux)

```bash
# 1. 서비스 파일 복사
sudo cp deploy/smartsolution.service /etc/systemd/system/

# 2. Nginx 설정 복사
sudo cp deploy/nginx.conf /etc/nginx/sites-available/smartsolution
sudo ln -s /etc/nginx/sites-available/smartsolution /etc/nginx/sites-enabled/

# 3. 서비스 시작
sudo systemctl daemon-reload
sudo systemctl enable smartsolution
sudo systemctl start smartsolution
sudo systemctl restart nginx

# 4. 업데이트 배포
git pull
sudo systemctl restart smartsolution
```

---

## 보안 주의사항

> 현재 코드는 **원내 폐쇄망 파일럿 검증용**입니다.

- HTTPS 미적용 시 쿠키 탈취 위험 → Nginx SSL 설정 권장
- 실제 환자 데이터 입력 금지 (파일럿 단계에서는 더미 데이터만 사용)
- `ADMIN_PASSWORD`는 `.env`에서 반드시 변경
- `SECRET_KEY`는 32자 이상 랜덤 값 사용

---

*Last updated: 2026-04-27*
