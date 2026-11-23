# 폰안파는폰가게 안내 페이지 (웹영역)

- 원고: `content/*.md` (머리말 + 마크다운). 금액·조건 문구는 `config.yml`의 facts 한 곳에서만 고친다.
- 빌드: `python3 build.py` → `dist/`
- 검사: `python3 ops/check.py` (오류 0이어야 올린다. '공개 전 확인' 항목은 원고 머리말 verify)
- 주소가 정해지면 `config.yml`의 base_url(과 custom_domain)만 바꾸고 다시 빌드한다.
- 올리는 순서: git pull --rebase → 빌드 → 검사 → source 브랜치 커밋·푸시 → main에 dist 덮어쓰기·푸시.
- 로고를 받으면 `static/favicon.ico`로 넣는다(없으면 임시 파비콘이 만들어짐).
