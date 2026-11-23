#!/usr/bin/env python3
"""빌드 결과 검사. 사용: python3 ops/check.py [dist]
오류가 하나라도 있으면 종료 코드 1 (올리지 않는다)."""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent
DIST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
sys.path.insert(0, str(ROOT))
from build import load_config  # noqa: E402
CFG = load_config()
BP = (CFG.get("base_path") or "").rstrip("/")

BANNED = ["공짜", "누구나", "무조건", "최저가", "1위", "0원", "전국 최저", "정부 지원", "합법"]
TITLE_MAX = 60
DESC_MAX = 155
REQUIRED = ["robots.txt", "sitemap.xml", "sitemap.txt", "rss.xml", "llms.txt",
            "favicon.ico", ".nojekyll", "style.css", "404.html",
            f"{CFG['indexnow_key']}.txt"]


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.title, self.desc, self.canonical = [], "", "", ""
        self.ld, self.text, self._tag, self._ld = [], [], None, False
        self.h1 = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._tag = tag
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "meta" and a.get("name") == "description":
            self.desc = a.get("content", "")
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href", "")
        if tag == "script" and a.get("type") == "application/ld+json":
            self._ld = True
        if tag == "h1":
            self.h1 += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._ld = False
        self._tag = None

    def handle_data(self, data):
        if self._ld:
            self.ld.append(data)
        elif self._tag == "title":
            self.title += data
        elif self._tag not in ("script", "style"):
            self.text.append(data)


def main():
    errors, warns = [], []
    for name in REQUIRED:
        if not (DIST / name).exists():
            errors.append(f"필수 파일 없음: {name}")

    pages = sorted(DIST.rglob("index.html"))
    seen_utm, seen_title = {}, {}
    for f in pages:
        rel = "/" + str(f.parent.relative_to(DIST)).replace(".", "").strip("/")
        rel = rel if rel == "/" else rel + "/"
        p = P()
        p.feed(f.read_text(encoding="utf-8"))
        text = " ".join(" ".join(p.text).split())

        if not p.title.strip():
            errors.append(f"{rel}: 제목 없음")
        page_title = p.title.split(" | ")[0]
        if len(page_title) > TITLE_MAX:
            errors.append(f"{rel}: 제목 {len(page_title)}자 (최대 {TITLE_MAX})")
        if len(p.title) > TITLE_MAX + 12:
            warns.append(f"{rel}: 브랜드 포함 제목이 {len(p.title)}자")
        if page_title in seen_title:
            errors.append(f"{rel}: 제목이 {seen_title[page_title]} 와 같음")
        seen_title[page_title] = rel
        if not p.desc:
            errors.append(f"{rel}: 설명(description) 없음")
        elif len(p.desc) > DESC_MAX:
            warns.append(f"{rel}: 설명 {len(p.desc)}자 (권장 {DESC_MAX} 이내)")
        if p.h1 != 1:
            errors.append(f"{rel}: h1이 {p.h1}개")
        want = CFG["base_url"].rstrip("/") + rel
        if p.canonical != want:
            errors.append(f"{rel}: canonical {p.canonical} ≠ {want}")
        if "ponanpa.com 기준" not in text:
            errors.append(f"{rel}: 기준일 표기 없음")
        if CFG["facts"]["tel"] not in text:
            errors.append(f"{rel}: 전화번호 없음")

        for w in BANNED:
            if w in text:
                errors.append(f"{rel}: 금지어 '{w}'")
        if "최대" in text and CFG["facts"]["amount_note"] not in text:
            errors.append(f"{rel}: '최대'가 있는데 조건 문구(금액은 조건에 따라 달라짐)가 없음")
        if re.search(r"\d+\s*만\s*원\s*이상", text):
            errors.append(f"{rel}: '○만원 이상' 표기(사이트는 '최대' 표기)")
        if "{{" in text or "}}" in text:
            errors.append(f"{rel}: 채워지지 않은 {{{{값}}}}")

        utm_links = 0
        for href in p.links:
            u = urlparse(href)
            if u.netloc == "ponanpa.com" and u.query:
                q = parse_qs(u.query)
                utm_links += 1
                if q.get("utm_source") != [CFG["utm_source"]] or q.get("utm_campaign") != [CFG["utm_campaign"]] \
                        or not q.get("utm_content"):
                    errors.append(f"{rel}: utm 형식 오류 {unquote(href)}")
                else:
                    seen_utm.setdefault(q["utm_content"][0], set()).add(rel)
            elif u.netloc == "ponanpa.com" and u.path not in ("", "/"):
                warns.append(f"{rel}: utm 없는 ponanpa.com 링크 {href}")
            elif not u.netloc and not u.scheme and href.startswith("/"):
                if BP and not href.startswith(BP + "/"):
                    errors.append(f"{rel}: base_path 없는 내부 링크 {href}")
                    continue
                target = DIST / href[len(BP):].lstrip("/")
                if not (target.exists() or (target / "index.html").exists()):
                    errors.append(f"{rel}: 깨진 내부 링크 {href}")
        if utm_links == 0:
            errors.append(f"{rel}: 상담 링크(utm) 없음")

        types = []
        for raw in p.ld:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as ex:
                errors.append(f"{rel}: 구조화 데이터 JSON 오류 {ex}")
                continue
            types.append(obj.get("@type"))
            if obj.get("@type") == "FAQPage":
                for item in obj["mainEntity"]:
                    ans = " ".join(item["acceptedAnswer"]["text"].split())
                    if ans not in text or item["name"] not in text:
                        errors.append(f"{rel}: FAQ 구조화 데이터와 화면 문장이 다름 — {item['name']}")
        for need in ("Organization", "BreadcrumbList"):
            if need not in types:
                errors.append(f"{rel}: 구조화 데이터 {need} 없음")

    for utm, where in seen_utm.items():
        if len(where) > 1:
            errors.append(f"utm_content '{utm}' 가 여러 페이지에서 쓰임: {sorted(where)}")

    sm = (DIST / "sitemap.txt").read_text(encoding="utf-8").split() if (DIST / "sitemap.txt").exists() else []
    if len(sm) != len(pages):
        errors.append(f"사이트맵 주소 {len(sm)}개 ≠ 페이지 {len(pages)}개")

    # 공개 전 사실 확인이 남은 항목(원고 머리말 verify)
    todo = []
    for md in sorted((ROOT / "content").glob("*.md")):
        m = re.match(r"^---\n(.*?)\n---\n", md.read_text(encoding="utf-8"), re.S)
        head = re.sub(r"\{\{.*?\}\}", "x", m.group(1))
        for item in (yaml.safe_load(head).get("verify") or []):
            todo.append(f"{md.name}: {item}")

    print(f"검사한 페이지 {len(pages)}쪽 · 오류 {len(errors)} · 경고 {len(warns)} · 공개 전 확인 {len(todo)}")
    for x in errors:
        print("  [오류]", x)
    for x in warns:
        print("  [경고]", x)
    for x in todo:
        print("  [공개 전 확인]", x)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
