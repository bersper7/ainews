# GitHub Actions로 상시 자동 실행하기

맥이 꺼져 있어도 주기적으로 동작하게 하려면 GitHub Actions 스케줄을 사용합니다.

## 1) 리포지토리 준비
1. GitHub에 새 리포를 만듭니다(권장: Private).
2. 로컬(현재 폴더)에서 아래 명령으로 초기화 후 푸시합니다.
   - 이미 git을 쓰고 있다면 원격만 추가하면 됩니다.
```
# 선택: 아직 git 초기화 안했다면
# git init
# git add -A
# git commit -m "GeekNews→Notion initial"

# 원격 추가 (예: yourname/geeknews-to-notion)
# git remote add origin git@github.com:YOUR_NAME/YOUR_REPO.git
# git branch -M main
# git push -u origin main
```

> 주의: 이 저장소에는 `.env`를 올리지 마세요. 비밀은 GitHub Secrets에만 저장합니다.

## 2) Secrets & Variables 설정
리포지토리 → Settings → Secrets and variables → Actions

- New repository secret 에 아래 값 추가(필수)
  - `NOTION_TOKEN` = Notion Integration 토큰
  - `NOTION_DATABASE_ID` = 32자리 DB ID(하이픈 있어도/없어도 OK)
- 선택(secrets)
  - `OPENAI_API_KEY` = 요약 사용 시 키 입력
- 선택(variables) — 기본값 유지해도 됩니다
  - `FEED_URL` = 기본 `https://news.hada.io/rss` (현재는 RSS 403 우회로 HTML 스크래핑이 동작)
  - `SUMMARY_LANGUAGE` = `ko`
  - `MAX_ITEMS` = 예: `30`
  - `OPENAI_MODEL` = 예: `gpt-4o-mini`

## 3) 워크플로우 동작
- 이 저장소에는 `.github/workflows/geeknews.yml`가 포함되어 있습니다.
- 스케줄: 매 30분(UTC 기준). 한국 시간은 +9시간입니다.
- 즉시 테스트: 리포지토리 → Actions → "GeekNews to Notion" → "Run workflow"

## 4) 정상 동작 체크
- Actions 실행 로그에 `[info] ...`와 `Notion page created`가 보이면 성공입니다.
- Notion DB에 새 항목이 들어왔는지 확인하세요.

## 5) 문제 해결 팁
- 403 등 네트워크 이슈: 현재 RSS는 403이어서 HTML 스크래핑 포백을 탑재해두었습니다.
- DB 권한: Integration을 해당 DB에 `Share → Add connections`로 초대해야 합니다.
- 속성명/타입: `Name(title)`, `Summary(rich text)`, `Tags(multi-select)`, `Source(select)`, `URL(url)`, `Published(date)`
- 중복 방지: URL 기준으로 중복을 건너뜁니다.

즐거운 자동화 되세요! 필요 시 스케줄 주기나 필터(키워드 포함/제외) 옵션도 확장해 드릴 수 있습니다.
