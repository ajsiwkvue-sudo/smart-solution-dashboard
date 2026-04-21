# CHANGELOG — Smart Solution Dashboard

> 병동 민원 접수 및 관리 대시보드  
> Repository: https://github.com/ajsiwkvue-sudo/smart-solution-dashboard

---

## Table of Contents

- [Project Overview](#project-overview)
- [Tech Stack](#tech-stack)
- [Version History](#version-history)
- [Architecture Decisions](#architecture-decisions)
- [Known Issues & Fixes](#known-issues--fixes)
- [Installation & Setup](#installation--setup)
- [File Structure](#file-structure)

---

## Project Overview

스마트솔루션별 병동 민원 접수 및 처리 현황 관리 웹 애플리케이션.  
간호사(병동별 계정)가 민원을 접수하면 관리자 페이지에 실시간 알림이 전달되고, 관리자가 처리 상태를 업데이트하는 구조.

**Primary roles:**
- `nurse` — 병동별 계정. 민원 접수 및 본인 병동 현황 조회
- `admin` — 전체 민원 현황 조회, 상태 변경, 계정 관리

---

## Tech Stack

| Layer      | Technology                              |
|------------|-----------------------------------------|
| Backend    | Python 3.x + Flask                      |
| Database   | SQLite3 (단일 파일 `db.sqlite3`)          |
| Auth       | URL 기반 Access Key (`secrets.token_urlsafe`) |
| Password   | `werkzeug.security` (PBKDF2 hashing)    |
| Frontend   | Jinja2 템플릿 + Vanilla JS + Fetch API   |
| Charts     | Chart.js (월별 bar chart)               |
| Styling    | CSS Grid / Flexbox (외부 라이브러리 없음)  |

---

## Version History

---

### v0.1 — 초기 단일 페이지 민원 접수 폼

**기능:**
- 기본 민원 접수 폼 (솔루션 선택 → 문제 유형 → 설명)
- 접수 완료 후 `submitted.html` 리다이렉트
- 민원 조회 페이지 (`track.html`)
- SQLite `complaints` 테이블 (ward, solution, issue, description, created_at)

**한계:**
- 단일 페이지로 누가 접수했는지 구분 없음
- 관리자 기능 없음

---

### v0.2 — 관리자 페이지 추가 + 기본 계정 시스템

**추가된 기능:**
- `/admin` 라우트 — 전체 민원 목록 테이블 뷰
- Flask 세션 기반 로그인 (`session['user']`)
- `users` 테이블 (username, password_hash, role)
- 기본 admin 계정 자동 생성 (`admin` / `admin1234`)
- `/action` POST — 민원 상태 변경 (`처리중` / `완료`)
- `status` 컬럼 추가 (`접수대기` → `처리중` → `완료`)

**한계:**
- 병동별 계정 구분 없음 (모든 간호사가 같은 페이지 사용)
- 브라우저 탭 간 세션 공유 문제 (쿠키 기반)

---

### v0.3 — 병동별 계정 + 간호사 전용 페이지

**요구사항 (사용자):**
> "각 병동별로 관리하는 페이지에서 접수하는 프로세스여야 할 것 같아. 그럼 각자 계정이 있어야 해"

**추가된 기능:**
- `role` 컬럼 (`admin` / `nurse`) 분리
- `/ward` 라우트 — 간호사 전용 페이지 (본인 병동 민원만 조회)
- `ward` = `username` 구조 (병동명 = 로그인 ID)
- FAB(Floating Action Button) 모달 — 민원 접수 팝업
- `/api/submit` POST — AJAX 비동기 민원 접수
- 접수 후 즉시 카드 목록에 추가 (페이지 리로드 없음)
- 관리자 계정 관리 탭 — 병동 계정 추가/삭제/비밀번호 재설정

**DB 변경:**
```sql
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'nurse';
```

---

### v0.4 — URL 기반 Access Key 인증 (핵심 아키텍처 변경)

**문제 (사용자):**
> "크롬에서 탭으로 각각 로그인된 화면을 보고 싶은데 그게 안되네? 이미 로그인된 화면밖에 안떠"

**원인 분석:**
- Flask 세션은 브라우저 쿠키 기반 → 모든 탭이 동일한 세션 공유
- 탭마다 다른 계정(병동)을 동시에 열 수 없음
- 관리자와 간호사가 같은 브라우저에서 동시 접속 불가

**해결 (아키텍처 결정):**
- Flask 세션 완전 제거
- 각 사용자에게 고유한 `access_key` 발급 (`secrets.token_urlsafe(24)`)
- 모든 인증을 URL 파라미터로 처리: `?key=ACCESS_KEY`
- 로그인 성공 시 해당 키가 포함된 URL로 리다이렉트

```python
# 로그인 성공 처리
if user['role'] == 'admin':
    return redirect(f"/admin?key={key}")
return redirect(f"/ward?key={key}")
```

**DB 변경:**
```sql
ALTER TABLE users ADD COLUMN access_key TEXT UNIQUE;
```

**인증 헬퍼:**
```python
def get_user_by_key(key):
    # URL ?key= 또는 X-Access-Key 헤더로 사용자 조회

def require_role(role):
    # 데코레이터: 특정 role 필요

def require_any_login(f):
    # 데코레이터: 로그인만 되어 있으면 통과
```

**관리자 페이지 기능:**
- 각 병동 계정 옆 URL 복사 버튼 — 병동에게 바로 공유 가능한 링크 제공
- `/admin/accounts/add`, `/admin/accounts/delete`, `/admin/accounts/reset` 엔드포인트

---

### v0.5 — 실시간 알림 + 폴링

**요구사항 (사용자):**
> "간호사 페이지에서 민원을 접수했으면 관리자 페이지에 알람이 뜨고"

**추가된 기능:**
- `/api/poll` GET — 관리자 페이지에서 10초마다 호출
  - `since` 파라미터: 마지막 확인 이후 신규 민원만 반환
  - `status_counts`, `total`, `latest_time` 함께 반환
- 관리자 페이지 벨 아이콘 — 신규 민원 개수 뱃지 표시
- 벨 클릭 시 드롭다운 패널 — 신규 민원 목록 (병동, 솔루션, 접수시각)
- 브라우저 알림(Notification API) 지원 (권한 허용 시)
- KPI 카드 숫자 실시간 업데이트 (페이지 리로드 없이)

**버그 수정:**
- **알람 미작동 문제**: 초기 민원이 없을 때 `lastKnownTime = ''`로 설정되고 `doPoll`에서 `if (!lastKnownTime) return` 조건에 걸려 폴링이 동작하지 않음
  - 수정: `latest_time`이 비어 있을 경우 현재 시각으로 초기화

```javascript
// 수정 전
let lastKnownTime = '{{ complaints[0].created_at if complaints else "" }}';

// 수정 후
let lastKnownTime = '{{ complaints[0].created_at if complaints else "" }}';
if (!lastKnownTime) {
    lastKnownTime = new Date().toISOString().slice(0, 19).replace('T', ' ');
}
```

---

### v0.6 — 새로고침 버그 수정 + 자동 동기화

**문제:**
> "새로고침하면 현황이 리셋되네"

**원인:** `location.reload()`가 key 파라미터 없이 `/ward`로 이동하면서 인증 실패

**수정:**
```javascript
// 수정 전
location.reload();

// 수정 후
window.location.href = '/ward?key=' + MY_KEY;
```

**추가된 기능 (자동 동기화):**
- 상단 바에 카운트다운 타이머 표시 (60초)
- 0초 도달 시 key 보존 상태로 페이지 자동 리로드
- 간호사/관리자 페이지 모두 적용

---

### v0.7 — 차트 및 시각화 개선

**요구사항 (사용자):**
> "각 현황에 차트는 시인성 좋게 바꿔줘. 전체, 월별 KPI를 볼 수 있는 차트를 의료진이나 관리자가 쉽게 볼 수 있는 다양한 차트로 구성해서 누가봐도 빠르게 정보를 읽을 수 있도록"

**추가된 기능:**
- 관리자 페이지: KPI 카드 5개 (전체, 접수대기, 처리중, 완료, 이달 접수)
- 간호사 페이지: KPI 카드 4개 (전체, 접수대기, 처리중, 완료)
- Chart.js 월별 bar chart (전체 추이)
- 처리현황 도넛 차트
- 솔루션별 / 병동별 순위 bar 차트

**후속 피드백 (사용자):**
> "처리현황과 솔루션별 민원건수, 병동별 민원건수는 단순 숫자로만 표시하자"

→ 도넛 차트 및 솔루션/병동 bar 차트를 숫자 랭킹 카드로 교체 (월별 bar 차트만 유지)

---

### v0.8 — 필터링 기능

**요구사항 (사용자):**
> "관리자 페이지에선 솔루션별, 병동별 데이터는 필터링 기능을 추가해서 해당 솔루션과 병동만 볼 수 있도록 / 간호사 페이지에선 솔루션별 필터링도 함께 추가해줘"

**초기 구현 (잘못된 방향):**
- 별도 필터 블록을 페이지에 추가

**사용자 수정 요청:**
> "별도의 필터링 블록을 넣으라는게 아니고. 기존 그 차트에서 필터 버튼을 누르면 솔루션 리스트가 나오고 그거를 누르면 sorting되도록"

**최종 구현:**
- 각 랭킹 카드 헤더 우측에 드롭다운 버튼 내장
- 클릭 시 솔루션 또는 병동 목록 팝업
- 선택 시 해당 카드 내부 행만 하이라이트 (다른 섹션에 영향 없음)

---

### v0.9 — 필터 독립성 수정 (중요 버그 수정)

**문제 (사용자):**
> "지금 페이지마다 차트에 필터링이 적용되어있는데 그거를 눌렀을 때 밑에 현황 바뀌고 다른 차트도 영향을 받는 것 같은데 독립적으로 움직이도록 해줘"

**원인 분석:**
1. `applyDD()` 함수가 테이블 필터 입력값을 변경하고 `applyFilter()`를 호출
2. `applyFilter()`가 내부에서 `updateMonthlyChart()`를 호출
3. 결과: 랭킹 카드 드롭다운 → 테이블 + 월별 차트 동시 변경

**수정 원칙:**
- 랭킹 카드 필터: 해당 카드 내부 행만 하이라이트, 다른 섹션 일절 건드리지 않음
- 테이블 필터: 테이블/카드 목록에만 적용
- 월별 차트: 항상 전체 데이터 기준으로 독립 렌더링

**각 섹션 독립성 구조:**

```
[랭킹 카드 드롭다운] ─→ 카드 내 행 하이라이트만
[테이블 필터 바]    ─→ 민원 테이블/카드 목록만
[월별 바 차트]      ─→ 항상 전체 데이터, 필터 영향 없음
```

---

### v1.0 — 현재 안정 버전

**최종 기능 목록:**

**공통:**
- URL Access Key 기반 인증 (탭별 다중 계정 동시 접속 가능)
- 60초 자동 동기화 타이머

**관리자 페이지 (`/admin?key=...`):**
- 2탭 레이아웃: 민원 관리 / 계정 관리
- KPI 카드 5개 (전체 / 접수대기 / 처리중 / 완료 / 이달 접수)
- 솔루션별 랭킹 (드롭다운 필터)
- 병동별 랭킹 (드롭다운 필터)
- 월별 접수 추이 바 차트
- 민원 테이블 (상태별 필터, 처리중/완료 버튼)
- 실시간 벨 알림 패널 (10초 폴링)
- 병동 계정 추가 / 삭제 / 비밀번호 재설정
- 병동별 접속 URL 복사 버튼

**간호사 페이지 (`/ward?key=...`):**
- KPI 카드 4개
- 솔루션별 랭킹 (드롭다운 필터, 카드 내부만 반응)
- 월별 접수 추이 바 차트 (필터 영향 없음)
- 민원 카드 타임라인 (상태 배지 포함)
- FAB 버튼 모달 → 민원 접수 (AJAX, 즉시 반영)

---

## Architecture Decisions

### 1. URL Key 인증 vs 세션 쿠키

| 항목 | 세션 쿠키 | URL Key |
|------|-----------|---------|
| 탭별 독립 계정 | ❌ 불가 | ✅ 가능 |
| 링크 공유 | ❌ | ✅ URL만 전달하면 접속 |
| 보안 | 세션 하이재킹 위험 | Key 노출 시 접근 가능 |
| 구현 복잡도 | 낮음 | 중간 |

**결정 이유:** 병동 PC에서 관리자가 동시에 다른 탭으로 여러 병동 화면을 모니터링해야 하는 실제 사용 시나리오에서 쿠키 방식은 근본적으로 불가능. URL Key 방식으로 각 탭이 완전히 독립적으로 동작.

> **주의:** 프로덕션 환경에서는 HTTPS 필수. HTTP에서는 URL Key가 네트워크에 노출됨.

### 2. ward = username 구조

병동명을 곧 username으로 사용하는 단순 구조.  
별도 ward 테이블 없이 `complaints.ward` = `users.username` 으로 관계 유지.  
병동 계정 삭제 시 해당 민원 기록은 보존 (ward 컬럼에 병동명 문자열로 남음).

### 3. 실시간성: 폴링 vs WebSocket

WebSocket 대신 10초 인터벌 HTTP 폴링 선택.  
이유: 의존성 없음, Flask 기본 기능만으로 구현 가능, 소규모 내부망 환경에서 충분한 실시간성.

---

## Known Issues & Fixes

| 이슈 | 원인 | 해결 |
|------|------|------|
| 멀티탭 로그인 불가 | Flask 쿠키 세션 공유 | URL Access Key로 전환 |
| 알람 미작동 (민원 0건 시) | `lastKnownTime=''` + early return 조건 충돌 | 빈 경우 현재 시각으로 초기화 |
| 새로고침 시 로그아웃 | `location.reload()` 가 key 없이 이동 | `window.location.href = '/ward?key=' + MY_KEY` |
| 필터가 다른 섹션에 영향 | `applyDD` → `applyFilter` → `updateMonthlyChart` 체인 호출 | 각 섹션 함수 완전 독립화 |
| `latest_month_count` 미정의 | admin 라우트에서 계산 누락 | admin() 함수에 계산 로직 추가 |
| 기존 DB 컬럼 없음 오류 | ALTER TABLE 중복 실행 | try/except 로 무시 처리 |

---

## Installation & Setup

### 요구사항

```
Python 3.8+
Flask
Werkzeug
```

### 설치

```bash
# 저장소 클론
git clone https://github.com/ajsiwkvue-sudo/crate_dashboard.git
cd crate_dashboard

# 의존성 설치
pip install flask werkzeug

# 실행
python app.py
```

서버 실행 후 http://127.0.0.1:5001 접속

### 기본 관리자 계정

| 항목 | 값 |
|------|-----|
| ID | `admin` |
| PW | `admin1234` |

> **최초 로그인 후 반드시 비밀번호 변경 권장**

### 병동 계정 추가 방법

1. admin 계정으로 로그인
2. 상단 `계정 관리` 탭 클릭
3. 병동명(ID) + 초기 비밀번호 입력 후 추가
4. 생성된 계정의 URL 복사 버튼으로 해당 병동에 링크 전달

### Windows 이식

Python + pip이 설치된 환경이라면 동일하게 동작.  
`db.sqlite3` 파일을 함께 복사하면 기존 데이터 유지.

---

## File Structure

```
crate_dashboard/
├── app.py                   # Flask 애플리케이션 (라우트, DB, 인증)
├── db.sqlite3               # SQLite 데이터베이스 (자동 생성)
├── templates/
│   ├── login.html           # 로그인 페이지
│   ├── admin.html           # 관리자 대시보드
│   ├── ward.html            # 간호사(병동) 대시보드
│   ├── submitted.html       # (레거시) 접수 완료 페이지
│   ├── index.html           # (레거시) 초기 인덱스
│   └── track.html           # (레거시) 민원 조회
├── CHANGELOG.md             # 이 파일
└── README.md                # (선택) 프로젝트 개요
```

---

## API Reference

| Method | Endpoint | Auth | 설명 |
|--------|----------|------|------|
| GET | `/` | — | 로그인 페이지로 리다이렉트 |
| GET/POST | `/login` | — | 로그인 |
| GET | `/ward?key=KEY` | nurse | 간호사 대시보드 |
| POST | `/api/submit?key=KEY` | nurse | 민원 접수 |
| GET | `/admin?key=KEY` | admin | 관리자 대시보드 |
| POST | `/action?key=KEY` | admin | 민원 상태 변경 |
| GET | `/api/poll?key=KEY&since=DATETIME` | admin | 신규 민원 폴링 |
| POST | `/admin/accounts/add?key=KEY` | admin | 병동 계정 추가 |
| POST | `/admin/accounts/delete?key=KEY` | admin | 병동 계정 삭제 |
| POST | `/admin/accounts/reset?key=KEY` | admin | 비밀번호 재설정 |

---

*Last updated: 2026-04-12*

---

## Security Issues

> 현재 코드는 **파일럿 검증 전용**입니다. 실제 환자 데이터가 포함되는 환경에는 아래 이슈를 반드시 해결한 후 배포해야 합니다.

### 🔴 치명적 — 배포 전 필수 수정

**1. URL에 인증키 평문 노출** — `?key=abc123` 형태로 브라우저 히스토리, 서버 로그에 기록됨. HTTP 환경에서는 네트워크 스니핑으로 탈취 가능.

**2. HTTPS 미적용** — 폐쇄망이라도 내부 패킷 감청 가능. 병원 보안 감사 지적 사항. 최소 nginx + self-signed cert 필요.

**3. 기본 관리자 계정 하드코딩** — `admin / admin1234`가 GitHub 공개 저장소에 노출. 최초 실행 즉시 변경 필수.

### 🟡 중요 — 프로덕션 전 수정

**4. 세션(Key) 만료 없음** — 한 번 발급된 key 영구 유효. PC 자리 비워도 URL만 알면 접속 가능.

**5. 입력값 검증 미흡** — XSS, SQL Injection 방어 코드 없음.

**6. 감사 로그(Audit Log) 없음** — 의료법상 접근 기록 보관 의무. 관리자 행동 로깅 필요.

| 규정 | 요구사항 | 현재 상태 |
|------|----------|-----------|
| 개인정보보호법 | 접근통제, 암호화 전송 | ❌ 미충족 |
| 의료법 | 의료정보 보호, 접근 로그 | ❌ 미충족 |
| 원내 보안정책 | IT팀 코드 리뷰 및 승인 | 미확인 |

> 파일럿 운영 시 실제 환자 데이터 절대 입력 금지. 더미 데이터로만 워크플로우 검증할 것.

---

## Roadmap

| 항목 | 현재 (파일럿) | 단기 보강 | 중장기 목표 |
|------|--------------|-----------|-------------|
| **DB** | SQLite | SQLite 유지 | PostgreSQL |
| **인증** | URL access_key | Flask-Session + 만료 | 병원 SSO / LDAP |
| **통신** | HTTP | HTTPS (self-signed) | 원내 공인 인증서 |
| **앱 구조** | Flask 단일 파일 | 유지 | 모듈화 / API 분리 |
| **EMR 연계** | ❌ | ❌ | HL7 / FHIR |
| **배포** | python app.py | Gunicorn + nginx | Docker / WAS |
| **감사 로그** | ❌ | 기본 로깅 추가 | 전체 행동 로깅 |
| **고가용성** | ❌ | ❌ | Active-Standby 이중화 |

### 단계별 실행 계획

- **Step 1** — 파일럿 운영 (현재, 4~8주): 더미 데이터로 1~2개 병동 워크플로우 검증
- **Step 2** — 피드백 수집: 현장 직원 인터뷰, 개선 요구사항 정리
- **Step 3** — IT팀 / 정보보안팀 협의: 원내 서버 환경, 보안 요구사항, 승인 프로세스
- **Step 4** — 정식 개발 (재설계): PostgreSQL 전환, 인증 교체, EMR 연계 설계
- **Step 5** — 보안 점검 후 전체 배포

---

*Last updated: 2026-04-14*

---

---

### v1.1 — PostgreSQL 전환 + Flask-Login 세션 인증 (아키텍처 재설계)

**배경:**
> 온프레미스 병원 서버 배포를 위한 프로덕션 준비. URL Key 방식의 보안 취약점 제거 필요.

**변경 내용:**

- **DB**: SQLite3 → PostgreSQL (psycopg2-binary)
  - 플레이스홀더 `?` → `%s`
  - `db.sqlite3` 파일 의존성 제거
  - `DATABASE_URL` 환경변수로 연결 설정
- **인증**: URL access_key 완전 제거 → Flask-Login 세션 쿠키
  - `access_key` 컬럼 제거
  - `login_user()` / `logout_user()` / `@login_required`
  - 세션 7일 유지 (`SESSION_PERMANENT`, `PERMANENT_SESSION_LIFETIME`, `session.permanent = True`, `login_user(remember=True)`)
- **보안**: 하드코딩 계정 정보 제거, `.env` 기반 `ADMIN_PASSWORD` / `SECRET_KEY`
- **배포 파일 추가**: `wsgi.py`, `deploy/nginx.conf`, `deploy/smartsolution.service`
- **레거시 파일 삭제**: `templates/index.html`, `submitted.html`, `track.html`

**버그 수정:**

| 이슈 | 원인 | 해결 |
|------|------|------|
| `load_user` DB 오류 시 세션 초기화 | 예외 처리 없어 Flask-Login이 anonymous 반환 | `try/except` 추가, 오류 시 `None` 반환 |
| API 경로에서 HTML redirect 반환 | `require_role`이 모든 경로에서 302 반환 | `/api/`, `/action`, `/admin/accounts/` 경로는 JSON 401/403 반환 |
| 계정 전환 시 이전 세션 잔류 | `login_user()` 전 `logout_user()` 미호출 | 로그인 전 `logout_user()` 명시 호출 |
| 알람 폴링 속도 | 10초 간격으로 알람 지연 | 3초로 단축 |

---

### v1.2 — 동일 브라우저 admin + nurse 동시 세션 지원

**문제 (사용자):**
> "아니 같은 크롬에서 테스트될 수 있도록 해야지"

**원인 분석:**
- Flask-Login은 브라우저당 세션 쿠키 하나
- 간호사로 로그인하면 `logout_user()` → `login_user()` 순서로 관리자 세션이 파괴됨
- 같은 브라우저에서 admin 탭 + ward 탭 동시 유지 불가

**해결 (아키텍처 결정):**
- 관리자: 기존 Flask-Login 세션 쿠키 유지
- 간호사: `itsdangerous.URLSafeTimedSerializer`로 서명된 **별도 `ward_session` 쿠키** 사용
- 로그인 시 role에 따라 분기:
  - `admin` → `login_user()` (Flask-Login)
  - `nurse` → `response.set_cookie('ward_session', signed_token)` (Flask-Login 건드리지 않음)

```python
# 간호사 로그인 처리
resp = make_response(redirect(url_for('ward_view', ward_name=username)))
resp.set_cookie('ward_session', token, max_age=86400*7, httponly=True, samesite='Lax')
return resp
```

- `/ward/logout` → `resp.delete_cookie('ward_session')` (관리자 세션 영향 없음)
- `require_ward` 데코레이터 추가: `ward_session` 쿠키 검증

**결과:** admin 탭 + ward 탭이 같은 Chrome에서 독립적으로 공존

---

### v1.3 — 병동별 독립 쿠키로 다중 병동 동시 로그인

**문제 (사용자):**
> "다른 병동 로그인도 여러 개를 창 띄우려고 하는데 간호사 세션이 하나니까 하나밖에 로그인이 안되네"

**원인:** `ward_session` 쿠키가 하나이므로 병동 B 로그인 시 병동 A 쿠키를 덮어씀

**해결:**
- 쿠키명을 `ward_session_{병동명}`으로 변경 → 병동마다 독립 쿠키
- 라우트를 `/ward` → `/ward/<ward_name>`으로 변경 (URL로 어느 병동 탭인지 구분)
- `/ward/<ward_name>/logout` → 해당 병동 쿠키만 삭제, 나머지 세션 무영향
- `/api/submit` 폼에 `ward` 필드 추가 → 서버에서 어느 병동 쿠키를 검증할지 결정

```
브라우저 쿠키 상태 (동시 로그인 예시):
  session          → admin Flask-Login
  ward_session_A병동 → A병동 서명 토큰
  ward_session_B병동 → B병동 서명 토큰
  ward_session_C병동 → C병동 서명 토큰
```

**현재 Roadmap 업데이트:**

| 항목 | 파일럿 v1.0 | 현재 v1.3 | 중장기 목표 |
|------|------------|-----------|-------------|
| **DB** | SQLite | PostgreSQL ✅ | PostgreSQL 유지 |
| **인증** | URL access_key | Flask-Login + ward cookie ✅ | 병원 SSO / LDAP |
| **멀티탭** | ✅ (URL key) | ✅ (독립 쿠키) | 유지 |
| **통신** | HTTP | HTTP | HTTPS (원내 인증서) |
| **배포** | python app.py | Gunicorn + nginx ✅ | Docker / WAS |
| **감사 로그** | ❌ | ❌ | 전체 행동 로깅 |

---

---

### v1.4 — 관리자→병동 메시지 기능 + 전체 코드 감사 수정

**새 기능: 담당자 메시지**

> 관리자가 접수/완료 처리 시 병동에 메시지를 남길 수 있음

- `/action` POST: 선택적 `message` 필드 추가, `complaints.message` 컬럼에 저장
- 관리자 UI: "접수하기" / "완료" 클릭 시 메시지 모달 팝업 (Ctrl+Enter 단축키 지원)
- `/api/ward_poll/<ward_name>`: 상태와 함께 메시지도 반환 (`messages` 필드)
- 병동 페이지: 각 민원 카드에 담당자 메시지 영역 추가 (3초 폴링으로 실시간 표시)

**버그 수정 (코드 감사)**

| 파일 | 이슈 | 수정 |
|------|------|------|
| `app.py` | `ward_view` / `ward_poll`에서 `['username']` 사용 — 사번 ≠ 병동명 혼동 | `['ward']`로 변경 |
| `app.py` | `/api/poll` NULL status 처리 누락 | `st = row['status'] or '접수대기'` |
| `app.py` | `complaints` 테이블 `message` 컬럼 누락 | `ADD COLUMN IF NOT EXISTS message TEXT` 마이그레이션 추가 |
| `admin.html` | `allNewComplaints` 배열 메모리 누수 | 최대 50건으로 캡 |
| `admin.html` | `insertAdjacentHTML`에 사용자 입력 직접 삽입 (HTML injection) | `esc()` 이스케이프 함수 적용 |
| `admin.html` | `updateKpiLive()` 이번달 KPI 미업데이트 | month 카드 업데이트 로직 추가 |
| `login.html` | 라벨 "아이디 (병동명)" — EMR 사번 로그인 반영 안됨 | "아이디 (사번 또는 병동명)"으로 변경 |
| `CHANGELOG.md` | 제목 "Crate Dashboard" | "Smart Solution Dashboard"로 수정 |

*Last updated: 2026-04-21*
