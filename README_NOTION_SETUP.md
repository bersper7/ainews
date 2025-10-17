# GeekNews → Notion 자동 수집 (설치 가이드)

아래 순서대로 진행하면, GeekNews 새 글이 자동으로 요약되어 Notion DB에 쌓입니다.

## 1) 준비물 (3가지)
- Notion 계정과 데이터베이스(표) 1개
- Notion Integration Token (권한 키)
- 이 폴더의 4개 파일: `geeknews_to_notion.py`, `requirements.txt`, `.env.example`, `README_NOTION_SETUP.md`

---

## 2) 노션 데이터베이스 만들기
1. 노션에서 `/table` 입력 → “데이터베이스 - 표 보기”를 선택하여 새 DB 생성
2. 아래와 같이 속성(컬럼) 구성
   - Name: 제목 (title)
   - Summary: 텍스트 (rich text)
   - Tags: 다중 선택 (multi-select)
   - Source: 선택 (select)
   - URL: URL (url)
   - Published: 날짜 (date)
3. 데이터베이스 URL에서 DB ID를 복사해둡니다. (예: `https://www.notion.so/workspace/이부분이_ID?v=...`)

---

## 3) Notion Integration 만들기
1. Notion Integrations 페이지 열기 → `New Integration`
2. 이름 지정 후 생성 → `Internal Integration Token` 복사
3. 방금 만든 데이터베이스 오른쪽 상단 `공유(Share)` → 해당 Integration 을 초대(Add connections)

---

## 4) 환경변수 파일(.env) 설정
1. `.env.example` 파일을 복사해 `.env` 로 이름 변경합니다.
2. 아래 2개는 필수로 채웁니다.
   - `NOTION_TOKEN=` (위에서 복사한 Integration Token)
   - `NOTION_DATABASE_ID=` (DB ID)
3. 선택 사항
   - `OPENAI_API_KEY=` 자동 요약을 쓰려면 입력 (없으면 요약 없이 제목만 저장)
   - `FEED_URL=` 기본값은 `https://news.hada.io/rss`
   - `SUMMARY_LANGUAGE=ko` 요약 언어 (ko/en 등)

---

## 5) 설치 및 실행
파이썬 3.10+ 권장

- (한 번만) 의존성 설치
```
pip install -r requirements.txt
```

- 수동 실행
```
python geeknews_to_notion.py
```

성공하면 터미널에 `Notion page created` 로그가 보이고, 노션 DB에 항목이 생성됩니다.

---

## 6) 자동 실행(선택)
- macOS: `cron` 또는 `launchd` 사용 (예: 30분 간격)
```
*/30 * * * * cd /path/to/folder && /usr/bin/env -S bash -lc "python geeknews_to_notion.py >> run.log 2>&1"
```
- Windows: 작업 스케줄러에서 `python geeknews_to_notion.py` 주기 실행 등록
- GitHub Actions 사용도 가능 (`schedule` 크론으로 실행)

---

## 문제 해결 팁
- 404/권한오류: 노션 DB에 Integration 이 연결(초대)되어 있는지 확인
- 속성명 불일치: DB 컬럼명이 스크립트의 `Name`, `Summary`, `Tags`, `Source`, `URL`, `Published` 와 정확히 같은지 확인
- 요약 미생성: `.env` 에 `OPENAI_API_KEY` 가 비어있으면 요약 없이 등록됩니다

---

## 커스터마이즈
- 태그: RSS 에 태그가 있으면 `Tags` 로 매핑합니다.
- 소스: `Source` 는 기본 `GeekNews` 로 저장됩니다.
- 요약 모델: `.env` 의 `OPENAI_MODEL` 로 변경 가능합니다.

***

즐거운 자동화 작업 되세요! 문제가 있으면 에러 메시지와 함께 알려주세요.
