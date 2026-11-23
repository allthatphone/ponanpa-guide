#!/usr/bin/env python3
"""폰안파는폰가게 정보 페이지 빌드 도구.

content/*.md (YAML 머리말 + 마크다운 본문) → dist/ (정적 사이트)
사용: python3 build.py [--out dist]
"""
import argparse
import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import markdown
import yaml

ROOT = Path(__file__).resolve().parent


def load_config():
    import os
    cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))
    # 환경변수로 주소만 바꿔 빌드할 수 있다: SITE_BASE_URL, SITE_BASE_PATH, SITE_CUSTOM_DOMAIN
    for env, key in (("SITE_BASE_URL", "base_url"), ("SITE_BASE_PATH", "base_path"),
                     ("SITE_CUSTOM_DOMAIN", "custom_domain")):
        if env in os.environ:
            cfg[key] = os.environ[env]
    return cfg


def fill(text, cfg):
    """{{facts.xxx}} / {{operator.xxx}} / {{fact_date}} 를 설정값으로 바꾼다."""
    def repl(m):
        cur = cfg
        for part in m.group(1).split("."):
            if not isinstance(cur, dict) or part not in cur:
                raise KeyError(f"설정에 없는 값: {{{{{m.group(1)}}}}}")
            cur = cur[part]
        return str(cur)
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", repl, text)


def load_pages(cfg):
    pages = []
    for path in sorted((ROOT / "content").glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        if not m:
            raise ValueError(f"{path.name}: 머리말(---)이 없습니다")
        meta = yaml.safe_load(fill(m.group(1), cfg))
        meta["body_md"] = fill(m.group(2), cfg)
        meta["source"] = path.name
        for key in ("title", "slug", "description", "utm", "updated", "order", "question"):
            if key not in meta:
                raise ValueError(f"{path.name}: 머리말에 {key} 가 없습니다")
        meta["updated"] = str(meta["updated"])
        meta["path"] = "/" if meta["slug"] == "index" else f"/{meta['slug']}/"
        pages.append(meta)
    pages.sort(key=lambda p: p["order"])
    return pages


def apply_link(cfg, utm_content):
    return (f"{cfg['apply_base']}?utm_source={quote(cfg['utm_source'])}"
            f"&utm_campaign={quote(cfg['utm_campaign'])}&utm_content={quote(utm_content)}")


def e(s):
    return html.escape(str(s), quote=True)


def render_md(text):
    md = markdown.Markdown(extensions=["tables", "attr_list", "sane_lists"])
    out = md.convert(text)
    out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    return out


def json_ld(obj):
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
            + "</script>")


def organization_ld(cfg):
    op, f = cfg["operator"], cfg["facts"]
    return {
        "@context": "https://schema.org", "@type": "Organization",
        "name": op["name"], "url": op["site"],
        "parentOrganization": {"@type": "Organization", "name": "유진텔레콤"},
        "contactPoint": {"@type": "ContactPoint", "telephone": f["tel"],
                         "contactType": "customer service", "areaServed": "KR",
                         "availableLanguage": "ko"},
        "address": {"@type": "PostalAddress", "addressCountry": "KR",
                    "streetAddress": op["address"]},
    }


def page_html(cfg, page, pages):
    base = cfg["base_url"].rstrip("/")
    url = base + page["path"]
    f, op = cfg["facts"], cfg["operator"]
    link = apply_link(cfg, page["utm"])
    body = render_md(page["body_md"])

    # 자주 묻는 질문: 화면 본문과 구조화 데이터가 같은 문장을 쓴다
    faq_html, lds = "", [organization_ld(cfg)]
    faqs = page.get("faq") or []
    if faqs:
        heading = page.get("faq_heading", "자주 묻는 질문")
        items = "".join(f'<div class="qa"><h3>{e(q["q"])}</h3><p>{e(q["a"])}</p></div>' for q in faqs)
        faq_html = f'<section class="faq"><h2>{e(heading)}</h2>{items}</section>'
        lds.append({"@context": "https://schema.org", "@type": "FAQPage",
                    "mainEntity": [{"@type": "Question", "name": q["q"],
                                    "acceptedAnswer": {"@type": "Answer", "text": q["a"]}}
                                   for q in faqs]})
    crumbs = [{"@type": "ListItem", "position": 1, "name": cfg["site_name"], "item": base + "/"}]
    if page["slug"] != "index":
        crumbs.append({"@type": "ListItem", "position": 2, "name": page["nav"], "item": url})
    lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs})

    # 맞지 않는 경우(모든 페이지 공통, 페이지에서 따로 쓰면 그걸 씀)
    notfit = page.get("not_fit") or [
        "지금 쓰는 통신사에 약정이 많이 남아 위약금이 큰 경우",
        f"{f['plan_keep']} 조건이 부담되는 경우",
        f"인터넷·TV {f['term_net']} 약정이 부담되는 경우(이사 계획 등)",
    ]
    notfit_html = ('<section class="notfit"><h2>이런 경우는 맞지 않아요</h2><ul>'
                   + "".join(f"<li>{e(x)}</li>" for x in notfit) + "</ul>"
                   f"<p>{e(f['penalty'])}</p></section>")

    nav = "".join(
        f'<a href="{p["path"]}"{" aria-current=\"page\"" if p is page else ""}>{e(p["nav"])}</a>'
        for p in pages)
    related = ""
    if page["slug"] == "index":
        cards = "".join(
            f'<a class="card" href="{p["path"]}"><strong>{e(p["nav"])}</strong>'
            f'<span>{e(p["question"])}</span></a>' for p in pages if p is not page)
        related = f'<section class="cards"><h2>궁금한 것부터 보세요</h2><div class="grid">{cards}</div></section>'
    else:
        others = [p for p in pages if p is not page and p["slug"] != "index"]
        idx = [p["slug"] for p in pages].index(page["slug"])
        pick = (others[idx - 1:] + others)[:3]
        related = ('<section class="related"><h2>함께 보면 좋은 안내</h2><ul>'
                   + "".join(f'<li><a href="{p["path"]}">{e(p["question"])}</a></li>' for p in pick)
                   + '<li><a href="/">안내 첫 화면</a></li></ul></section>')

    verify = ""
    for name, key in (("google-site-verification", "google_verification"),
                      ("naver-site-verification", "naver_verification"),
                      ("msvalidate.01", "bing_verification")):
        if cfg.get(key):
            verify += f'<meta name="{name}" content="{e(cfg[key])}">\n'

    crumb_html = "" if page["slug"] == "index" else (
        f'<p class="crumb"><a href="/">안내 첫 화면</a> › {e(page["nav"])}</p>')
    full_title = page["title"] if page["slug"] == "index" else f'{page["title"]} | {cfg["brand"]}'

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(page['description'])}">
<link rel="canonical" href="{e(url)}">
{verify}<meta property="og:type" content="article">
<meta property="og:title" content="{e(page['title'])}">
<meta property="og:description" content="{e(page['description'])}">
<meta property="og:url" content="{e(url)}">
<meta property="og:site_name" content="{e(cfg['site_name'])}">
<meta property="og:locale" content="ko_KR">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="alternate" type="application/rss+xml" title="{e(cfg['site_name'])}" href="/rss.xml">
<link rel="stylesheet" href="/style.css">
{"".join(json_ld(x) for x in lds)}
</head>
<body>
<header class="top">
  <a class="logo" href="/"><b>폰안파는</b>폰가게 <span>안내</span></a>
  <a class="btn small" href="{e(link)}">상담 신청</a>
</header>
<nav class="menu" aria-label="안내 목록">{nav}</nav>
<main>
{crumb_html}
<p class="stamp">{e(page['updated'])} ponanpa.com 기준 · 운영 측이 직접 쓴 안내</p>
<h1>{e(page['title'])}</h1>
<p class="summary">{e(page['summary'])}</p>
{body}
{notfit_html}
{faq_html}
<section class="cta">
  <h2>내 조건에서 얼마인지는 상담으로 확인하세요</h2>
  <p>{e(f['amount_note'])} {e(f['callback'])}</p>
  <a class="btn" href="{e(link)}">ponanpa.com에서 상담 신청</a>
  <p class="tel">전화 <a href="tel:{e(f['tel'])}">{e(f['tel'])}</a> · {e(f['hours'])}</p>
</section>
{related}
</main>
<footer>
  <p><strong>{e(op['name'])}</strong> · {e(op['run_by'])} · 대표 {e(op['ceo'])}</p>
  <p>사업자등록번호 {e(op['biz_no'])} · 통신판매업신고 {e(op['mail_order'])}</p>
  <p>{e(op['address'])} · 고객센터 {e(f['tel'])}</p>
  <p><a href="{e(op['cert_url'])}" rel="nofollow noopener">{e(op['cert_text'])} 확인</a> · <a href="/about/">운영자 소개</a> · <a href="{e(op['site'])}">ponanpa.com</a></p>
  <p class="fine">이 사이트는 폰안파는폰가게 운영 측이 만든 안내 페이지입니다. 금액과 조건은 {e(cfg['fact_date'])} ponanpa.com 화면 기준이며, 바뀌면 ponanpa.com이 우선입니다.</p>
</footer>
</body>
</html>
"""


CSS = """:root{--o:#FFA94D;--b:#E8590C;--bg:#F7F6F2;--ink:#22201c;--sub:#6b655c;--line:#e6dfd3;--card:#fff}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;word-break:keep-all;overflow-wrap:anywhere}
a{color:var(--b)}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;max-width:760px;margin:0 auto;padding:14px 18px}
.logo{font-weight:800;font-size:19px;color:var(--ink);text-decoration:none}
.logo b{color:var(--b)}
.logo span{font-weight:600;font-size:14px;color:var(--sub);margin-left:4px}
.menu{display:flex;gap:8px;overflow-x:auto;max-width:760px;margin:0 auto;padding:0 18px 12px;scrollbar-width:none}
.menu::-webkit-scrollbar{display:none}
.menu a{flex:none;font-size:16px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);text-decoration:none}
.menu a[aria-current]{background:var(--ink);color:#fff;border-color:var(--ink)}
main{max-width:760px;margin:0 auto;padding:8px 18px 40px}
.crumb,.stamp{font-size:16px;color:var(--sub);margin:6px 0}
h1{font-size:28px;line-height:1.35;margin:10px 0 14px;letter-spacing:-.02em}
h2{font-size:22px;line-height:1.4;margin:38px 0 10px;letter-spacing:-.01em}
h3{font-size:18px;margin:22px 0 4px}
.summary{background:var(--card);border-left:5px solid var(--o);padding:14px 16px;border-radius:0 10px 10px 0;font-weight:600;margin:0 0 8px}
.table-wrap{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:16px}
th,td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:#fff3e2;font-weight:700;white-space:nowrap}
td{min-width:6.5em}
td:first-child{white-space:nowrap;min-width:0}
tr:last-child td{border-bottom:0}
ul,ol{padding-left:22px}
li{margin:4px 0}
.notfit{background:#fff;border:1px solid var(--line);border-radius:12px;padding:4px 18px 10px;margin-top:38px}
.notfit h2{margin-top:16px}
.qa{border-bottom:1px solid var(--line);padding-bottom:8px}
.qa p{margin:4px 0 8px}
.cta{background:#fff3e2;border-radius:14px;padding:6px 18px 18px;margin-top:38px;text-align:center}
.cta h2{margin-top:18px}
.btn{display:inline-block;background:var(--b);color:#fff;font-weight:800;text-decoration:none;padding:13px 22px;border-radius:10px;font-size:17px}
.btn.small{padding:8px 14px;font-size:16px;flex:none}
.tel{font-size:16px;color:var(--sub);margin:12px 0 0}
.grid{display:grid;gap:10px;grid-template-columns:1fr}
.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;text-decoration:none;color:var(--ink)}
.card strong{display:block;color:var(--b);font-size:16px}
footer{max-width:760px;margin:0 auto;padding:22px 18px 48px;border-top:1px solid var(--line);font-size:16px;color:var(--sub)}
footer p{margin:4px 0}
.fine{margin-top:10px}
@media(min-width:620px){.grid{grid-template-columns:1fr 1fr}h1{font-size:32px}}
"""


def with_base(text, cfg):
    """사이트를 폴더 아래(예: ponanpa.com/guide/)에 둘 때 내부 주소 앞에 base_path를 붙인다."""
    bp = (cfg.get("base_path") or "").rstrip("/")
    if not bp:
        return text
    return re.sub(r'(href|src)="/(?!/)', lambda m: f'{m.group(1)}="{bp}/', text)


def make_favicon(out):
    """로고 파일을 받기 전까지 쓰는 임시 파비콘(주황 바탕 + 흰 원). static/favicon.ico 가 있으면 그걸 쓴다."""
    custom = ROOT / "static" / "favicon.ico"
    if custom.exists():
        shutil.copy(custom, out / "favicon.ico")
        return
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (64, 64), "#E8590C")
        d = ImageDraw.Draw(img)
        d.ellipse((14, 14, 50, 50), fill="#FFFFFF")
        d.ellipse((24, 24, 40, 40), fill="#FFA94D")
        img.save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    except ImportError:
        print("경고: PIL이 없어 favicon.ico를 만들지 못했습니다", file=sys.stderr)


def build(out_dir):
    cfg = load_config()
    pages = load_pages(cfg)
    base = cfg["base_url"].rstrip("/")
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for p in pages:
        target = out / "index.html" if p["slug"] == "index" else out / p["slug"] / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(with_base(page_html(cfg, p, pages), cfg), encoding="utf-8")

    (out / "style.css").write_text(CSS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    if cfg.get("custom_domain"):
        (out / "CNAME").write_text(cfg["custom_domain"] + "\n", encoding="utf-8")
    static = ROOT / "static"
    if static.exists():
        for item in static.iterdir():
            if item.name != "favicon.ico" and item.is_file():
                shutil.copy(item, out / item.name)
    make_favicon(out)

    urls = [(base + p["path"], p["updated"]) for p in pages]
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    (out / "sitemap.txt").write_text("\n".join(u for u, _ in urls) + "\n", encoding="utf-8")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{e(u)}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls)
        + "</urlset>\n", encoding="utf-8")

    def rfc822(d):
        return dt.datetime.strptime(d, "%Y-%m-%d").strftime("%a, %d %b %Y 09:00:00 +0900")
    items = "".join(
        f"<item><title>{e(p['title'])}</title><link>{e(base + p['path'])}</link>"
        f"<guid>{e(base + p['path'])}</guid><pubDate>{rfc822(p['updated'])}</pubDate>"
        f"<description>{e(p['summary'])}</description></item>\n" for p in pages)
    (out / "rss.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>\n'
        f"<title>{e(cfg['site_name'])}</title><link>{base}/</link>"
        f"<description>{e(cfg['tagline'])}</description><language>ko</language>\n{items}</channel></rss>\n",
        encoding="utf-8")

    f, op = cfg["facts"], cfg["operator"]
    llms = [
        f"# {cfg['brand']} 안내", "",
        f"> {cfg['brand']}(ponanpa.com)는 휴대폰은 그대로 쓰고 유심·인터넷·TV를 바꾸면 현금 지원금을 받는 서비스입니다. "
        f"휴대폰은 판매하지 않습니다. {op['run_by']}. 이 사이트는 운영 측이 만든 안내 페이지입니다.", "",
        f"기준일: {cfg['fact_date']} ponanpa.com 화면", "",
        "## 핵심 조건",
        f"- {f['amount_title']}: 유심 변경 {f['amount_usim']} / 유심+인터넷 {f['amount_usim_net']} / 유심+인터넷+TV {f['amount_all']}",
        f"- {f['amount_note']}",
        f"- {f['plan_keep']}. 약정은 유심 {f['term_usim']}, 인터넷·TV {f['term_net']}.",
        f"- 입금 시점: {f['pay_usim']}, {f['pay_net']}.",
        f"- {f['penalty']}",
        "- 번호이동 방식이라 쓰던 번호는 그대로 유지됩니다.",
        f"- 상담: {f['tel']} ({f['hours']}), 신청 https://ponanpa.com/", "",
        "## 페이지",
    ] + [f"- [{p['title']}]({base + p['path']}): {p['summary']}" for p in pages]
    (out / "llms.txt").write_text("\n".join(llms) + "\n", encoding="utf-8")

    key = cfg.get("indexnow_key")
    if key:
        (out / f"{key}.txt").write_text(key, encoding="utf-8")
    (out / "404.html").write_text(with_base(
        '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex"><title>페이지를 찾을 수 없습니다</title><link rel="stylesheet" href="/style.css">'
        '<main><h1>페이지를 찾을 수 없습니다</h1><p><a href="/">안내 첫 화면으로 가기</a></p></main></html>', cfg),
        encoding="utf-8")
    print(f"빌드 완료: {len(pages)}쪽 → {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    sys.exit(build(ap.parse_args().out))
