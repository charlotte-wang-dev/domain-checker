#!/usr/bin/env python3
"""
批量域名可用性检查工具（自用版）
================================
替代 query.domains，无需验证码。
自动生成连字符变体（beatmaker → beat-maker）。

用法：
  python3 domain_checker.py beatmaker                  # 查常用 TLD（含变体）
  python3 domain_checker.py beatmaker -e               # 查 ~250 个 TLD
  python3 domain_checker.py beatmaker --all             # 查全部 IANA TLD
  python3 domain_checker.py beatmaker --tld com,ai,io   # 指定 TLD
  python3 domain_checker.py beatmaker --no-variants     # 不生成变体
  python3 domain_checker.py word1 word2                 # 多个词
  python3 domain_checker.py --file keywords.txt         # 文件批量
  python3 domain_checker.py beatmaker -a                # 只看可注册

查完后进入交互模式，输入序号查看域名详情（WHOIS/流量/预览/原始数据）。

依赖：pip install python-whois dnspython
"""

import whois
import socket
import sys
import csv
import os
import re
import time
import argparse
import urllib.request
import concurrent.futures
from datetime import datetime

try:
    import wordninja
    HAS_WORDNINJA = True
except ImportError:
    HAS_WORDNINJA = False

# ============ 已知词根（用于自动拆分连字符变体）============
KNOWN_ROOTS = [
    'generator', 'creator', 'maker', 'builder', 'constructor', 'composer',
    'helper', 'assistant', 'agent', 'advisor', 'copilot',
    'tool', 'finder', 'checker', 'detector', 'scanner', 'tester',
    'converter', 'translator', 'editor', 'enhancer', 'optimizer', 'remover',
    'resizer', 'compressor', 'splitter', 'merger', 'cleaner', 'replacer',
    'planner', 'scheduler', 'manager', 'tracker', 'monitor',
    'recorder', 'viewer', 'player', 'reader', 'writer', 'counter',
    'timer', 'picker', 'sorter', 'matcher', 'blocker', 'validator',
    'extractor', 'summarizer', 'transcriber', 'analyzer', 'evaluator',
    'simulator', 'comparator', 'calculator', 'estimator',
    'downloader', 'uploader', 'connector', 'syncer',
    'solver', 'tutor', 'coach', 'trainer', 'quiz',
    'cloner', 'swapper', 'colorizer', 'restorer', 'animator',
    'predictor', 'recommender', 'classifier', 'curator',
    'hub', 'lab', 'studio', 'zone', 'base', 'box', 'pad', 'bot',
    'flow', 'stack', 'craft', 'wave', 'mind', 'lens', 'spark',
]


def generate_variants(keyword):
    """已知词根精确匹配 + wordninja 兜底，自动生成连字符变体"""
    variants = [keyword]
    kw = keyword.lower()

    # 1) 精确词根匹配（优先，准确率高）
    for root in sorted(KNOWN_ROOTS, key=len, reverse=True):
        if kw.endswith(root) and len(kw) > len(root):
            prefix = kw[:-len(root)]
            if len(prefix) >= 2:
                variants.append(f"{prefix}-{root}")
                return variants
        if kw.startswith(root) and len(kw) > len(root):
            suffix = kw[len(root):]
            if len(suffix) >= 2:
                variants.append(f"{root}-{suffix}")
                return variants

    # 2) wordninja 智能拆词兜底（过滤单字母碎片）
    if HAS_WORDNINJA:
        parts = wordninja.split(kw)
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
            hyphenated = '-'.join(parts)
            if hyphenated != kw and hyphenated not in variants:
                variants.append(hyphenated)

    return variants


# ============ TLD 列表 ============
POPULAR_TLDS = [
    'com', 'net', 'org', 'io', 'ai', 'co', 'dev', 'app',
    'me', 'cc', 'xyz', 'info', 'biz', 'tech', 'site', 'online',
    'store', 'shop', 'fun', 'pro', 'top', 'cloud', 'design',
    'tools', 'agency', 'digital', 'studio', 'land', 'zone',
    'life', 'world', 'space', 'live', 'art', 'work', 'cool',
    'one', 'plus', 'run', 'ink', 'gg', 'lol', 'wtf',
]

EXTENDED_TLDS = list(dict.fromkeys(POPULAR_TLDS + [
    'us', 'uk', 'ca', 'de', 'fr', 'jp', 'kr', 'cn', 'in', 'au',
    'br', 'mx', 'ru', 'it', 'es', 'nl', 'se', 'no', 'fi', 'dk',
    'pl', 'cz', 'at', 'ch', 'be', 'pt', 'ie', 'nz', 'sg', 'hk',
    'tw', 'th', 'vn', 'id', 'ph', 'my', 'za', 'ng', 'ke', 'eg',
    'ar', 'cl', 'pe', 'ae', 'sa', 'il', 'tr', 'ua', 'ro',
    'academy', 'actor', 'bar', 'bet', 'bio', 'black', 'blog',
    'blue', 'bot', 'build', 'business', 'buzz', 'cafe', 'capital',
    'cards', 'care', 'careers', 'cash', 'center', 'chat', 'cheap',
    'city', 'click', 'clinic', 'club', 'coach', 'codes', 'community',
    'company', 'computer', 'consulting', 'courses', 'credit', 'dance',
    'data', 'date', 'deal', 'deals', 'degree', 'delivery', 'dental',
    'directory', 'dog', 'domains', 'download', 'earth', 'education',
    'email', 'energy', 'engineer', 'expert', 'express', 'fail',
    'fans', 'farm', 'fashion', 'film', 'finance', 'fit', 'fitness',
    'flights', 'food', 'football', 'forex', 'foundation', 'fund',
    'gallery', 'game', 'games', 'garden', 'gift', 'global', 'gold',
    'golf', 'group', 'guide', 'guru', 'health', 'help', 'holiday',
    'home', 'host', 'house', 'how', 'icu', 'institute', 'insurance',
    'international', 'investments', 'jewelry', 'jobs', 'kitchen',
    'lawyer', 'legal', 'link', 'loan', 'love', 'ltd', 'luxury',
    'management', 'market', 'marketing', 'mba', 'media', 'menu',
    'mobile', 'money', 'monster', 'movie', 'museum', 'music', 'name',
    'network', 'news', 'ninja', 'page', 'partners', 'party', 'pet',
    'photo', 'photography', 'photos', 'pics', 'pink', 'pizza',
    'place', 'press', 'pub', 'quest', 'recipes', 'red', 'rent',
    'repair', 'report', 'rest', 'review', 'reviews', 'rich', 'rocks',
    'sale', 'salon', 'school', 'science', 'services', 'social',
    'software', 'solar', 'solutions', 'style', 'supply', 'support',
    'systems', 'tax', 'team', 'technology', 'tennis', 'tips',
    'today', 'tools', 'tours', 'town', 'toys', 'trade', 'trading',
    'training', 'travel', 'university', 'ventures', 'vet', 'video',
    'vision', 'watch', 'web', 'website', 'wedding', 'wiki', 'win',
    'wine', 'works', 'yoga',
]))


def fetch_all_tlds():
    try:
        url = 'https://data.iana.org/TLD/tlds-alpha-by-domain.txt'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        tlds = [l.strip().lower() for l in resp.read().decode().split('\n') if l.strip() and not l.startswith('#')]
        print(f"  📡 IANA: {len(tlds)} 个 TLD")
        return tlds
    except Exception as e:
        print(f"  ⚠️  IANA 拉取失败，用内置列表")
        return EXTENDED_TLDS


# ============ WHOIS 检查 ============
def check_domain(domain):
    try:
        w = whois.whois(domain)
        if w.domain_name:
            reg = w.creation_date
            exp = w.expiration_date
            upd = w.updated_date
            if isinstance(reg, list): reg = reg[0]
            if isinstance(exp, list): exp = exp[0]
            if isinstance(upd, list): upd = upd[0]
            return {
                'domain': domain,
                'status': 'taken',
                'reg_year': reg.strftime('%Y') if reg else '?',
                'reg_date': reg.strftime('%Y-%m-%d') if reg else '?',
                'exp_date': exp.strftime('%Y-%m-%d') if exp else '?',
                'upd_date': upd.strftime('%Y-%m-%d') if upd else '?',
                'registrar': (w.registrar or '?')[:35],
                'name_servers': w.name_servers or [],
                'status_codes': w.status if isinstance(w.status, list) else [w.status] if w.status else [],
                'dnssec': w.dnssec or '?',
                'emails': w.emails if isinstance(w.emails, list) else [w.emails] if w.emails else [],
                'whois_raw': w.text if hasattr(w, 'text') else '',
            }
        else:
            return {'domain': domain, 'status': 'available'}
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ['no match', 'not found', 'no entries', 'no output',
                                    'no whois', 'not registered', 'no data', 'available', 'free']):
            return {'domain': domain, 'status': 'available'}
        return {'domain': domain, 'status': 'unknown', 'error': str(e)[:60]}


def check_keyword(keyword, tlds, max_workers=10):
    taken, available, unknown = [], [], []
    total = len(tlds)
    done = 0

    def do_check(tld):
        r = check_domain(f"{keyword}.{tld}")
        r['tld'] = tld
        return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(do_check, tld): tld for tld in tlds}
        for f in concurrent.futures.as_completed(futures):
            done += 1
            r = f.result()
            [taken, available, unknown][['taken','available','unknown'].index(r['status'])].append(r)
            filled = int(30 * done / total)
            sys.stdout.write(f'\r  [{"█"*filled}{"░"*(30-filled)}] {done}/{total}')
            sys.stdout.flush()

    print()
    taken.sort(key=lambda x: x.get('reg_year', '9999'))
    available.sort(key=lambda x: len(x.get('tld', '')))
    return taken, available, unknown


# ============ 网站活跃度检测 ============
def check_site_live(domain):
    for scheme in ['https', 'http']:
        try:
            req = urllib.request.Request(f"{scheme}://{domain}",
                                         headers={'User-Agent': 'Mozilla/5.0'},
                                         method='GET')
            resp = urllib.request.urlopen(req, timeout=5)
            html = resp.read(8000).decode('utf-8', errors='ignore')
            title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.DOTALL)
            return {
                'live': True,
                'url': resp.url,
                'status_code': resp.status,
                'title': title_m.group(1).strip()[:80] if title_m else '',
            }
        except:
            continue
    return {'live': False}


# ============ 显示结果列表 ============
def print_results(keyword, taken, available, unknown, available_only=False):
    hot_tlds = {'com', 'net', 'org', 'io', 'ai', 'co', 'dev', 'app', 'me'}
    all_domains = []
    idx = 1

    if not available_only and taken:
        print(f"\n  ● 已注册 ({len(taken)}):")
        print(f"  {'#':<5} {'域名':<28} {'年份':<7} {'到期':<13} {'注册商'}")
        print(f"  {'─'*75}")
        for r in taken:
            print(f"  {idx:<5} ● {r['domain']:<26} {r.get('reg_year','?'):<7} {r.get('exp_date','?'):<13} {r.get('registrar','?')}")
            r['idx'] = idx
            all_domains.append(r)
            idx += 1

    if available:
        print(f"\n  ○ 可注册 ({len(available)}):")
        hot = [r for r in available if r['tld'] in hot_tlds]
        other = [r for r in available if r['tld'] not in hot_tlds]

        if hot:
            print(f"  🔥 热门:")
            for r in hot:
                print(f"  {idx:<5} ✅ {r['domain']}")
                r['idx'] = idx
                all_domains.append(r)
                idx += 1
        if other:
            for r in other:
                print(f"  {idx:<5} ✅ {r['domain']}")
                r['idx'] = idx
                all_domains.append(r)
                idx += 1

    print(f"\n  📊 已注册: {len(taken)} | 可注册: {len(available)} | 未知: {len(unknown)}")
    return all_domains


# ============ 域名详情 ============
def show_detail(result):
    domain = result['domain']
    status = result['status']

    print(f"\n{'='*60}")
    print(f"  {domain.upper()}")
    print(f"{'='*60}")

    if status == 'available':
        print(f"\n  ✅ 可注册!")
        print(f"\n  📎 注册链接:")
        print(f"     https://www.namecheap.com/domains/registration/results/?domain={domain}")
        print(f"     https://www.godaddy.com/domainsearch/find?domainToCheck={domain}")
        return

    print(f"\n  📋 域名信息")
    print(f"  {'─'*50}")
    print(f"  注册时间:   {result.get('reg_date', '?')}")
    print(f"  到期时间:   {result.get('exp_date', '?')}")
    print(f"  更新时间:   {result.get('upd_date', '?')}")
    print(f"  注册商:     {result.get('registrar', '?')}")
    print(f"  DNSSEC:     {result.get('dnssec', '?')}")

    ns = result.get('name_servers', [])
    if ns:
        print(f"  Nameservers: {', '.join(ns[:4])}")

    codes = result.get('status_codes', [])
    if codes:
        print(f"  状态:")
        for c in codes[:5]:
            print(f"    · {c}")

    print(f"\n  🌐 网站状态")
    print(f"  {'─'*50}")
    print(f"  检测中...")
    site = check_site_live(domain)
    if site['live']:
        print(f"\r  ✅ 在线 | HTTP {site['status_code']}")
        print(f"  URL:   {site['url']}")
        if site['title']:
            print(f"  Title: {site['title']}")
    else:
        print(f"\r  ❌ 离线或无法访问")

    print(f"\n  📸 网站预览")
    print(f"  {'─'*50}")
    print(f"  截图: https://image.thum.io/get/https://{domain}")
    print(f"  访问: https://{domain}")

    raw = result.get('whois_raw', '')
    if raw:
        print(f"\n  📄 原始 WHOIS")
        print(f"  {'─'*50}")
        for line in raw.strip().split('\n')[:40]:
            print(f"  {line}")
        if raw.count('\n') > 40:
            print(f"  ... (共 {raw.count(chr(10))} 行)")


# ============ 交互模式 ============
def interactive_mode(all_domains):
    if not all_domains:
        return

    print(f"\n{'─'*60}")
    print(f"💡 输入序号查看域名详情，输入 q 退出")
    print(f"{'─'*60}")

    while True:
        try:
            inp = input("\n  序号> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if inp.lower() in ('q', 'quit', 'exit', ''):
            break

        try:
            idx = int(inp)
            match = next((d for d in all_domains if d.get('idx') == idx), None)
            if match:
                show_detail(match)
            else:
                print(f"  ⚠️  序号 {idx} 不存在")
        except ValueError:
            print(f"  ⚠️  请输入数字序号")


# ============ 主流程 ============
def main():
    parser = argparse.ArgumentParser(
        description='批量域名检查（替代 query.domains）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s beatmaker                    查常用 TLD + 自动变体 beat-maker
  %(prog)s beatmaker -e                 查扩展 ~250 个 TLD
  %(prog)s beatmaker --all              查全部 IANA TLD
  %(prog)s beatmaker --tld com,ai,io    指定 TLD
  %(prog)s beatmaker --no-variants      不生成连字符变体
  %(prog)s word1 word2                  多个词
  %(prog)s --file keywords.txt          文件批量
  %(prog)s beatmaker -a                 只看可注册
  %(prog)s beatmaker --no-interactive   不进入交互模式
        """
    )
    parser.add_argument('keywords', nargs='*', help='关键词/词根')
    parser.add_argument('--tld', type=str, help='指定 TLD，逗号分隔')
    parser.add_argument('--file', '-f', type=str, help='从文件读取')
    parser.add_argument('--all', action='store_true', help='全部 IANA TLD')
    parser.add_argument('--extended', '-e', action='store_true', help='扩展 ~250 TLD')
    parser.add_argument('--available-only', '-a', action='store_true', help='只显示可注册')
    parser.add_argument('--workers', '-w', type=int, default=10, help='并发数')
    parser.add_argument('--export', type=str, help='导出 CSV')
    parser.add_argument('--no-interactive', '-n', action='store_true', help='不进入交互模式')
    parser.add_argument('--no-variants', action='store_true', help='不生成连字符变体')
    args = parser.parse_args()

    keywords = list(args.keywords)
    if args.file:
        with open(args.file, 'r') as f:
            keywords.extend([l.strip() for l in f if l.strip()])
    if not keywords:
        parser.print_help()
        sys.exit(1)

    # 生成变体
    if not args.no_variants:
        expanded = []
        for kw in keywords:
            variants = generate_variants(kw.lower().strip().replace(' ', ''))
            if len(variants) > 1:
                print(f"  🔀 {kw} → {', '.join(variants)}")
            expanded.extend(variants)
        keywords = list(dict.fromkeys(expanded))  # 去重保序

    if args.tld:
        tlds = [t.strip().lstrip('.') for t in args.tld.split(',')]
    elif args.all:
        tlds = fetch_all_tlds()
    elif args.extended:
        tlds = EXTENDED_TLDS
    else:
        tlds = POPULAR_TLDS

    print(f"\n{'='*60}")
    print(f"🔍 域名检查: {len(keywords)} 词根 × {len(tlds)} TLD | 并发: {args.workers}")
    print(f"{'='*60}")

    all_results = []
    last_domains = []

    for keyword in keywords:
        keyword = keyword.lower().strip()
        print(f"\n{'─'*60}")
        print(f"📌 [{keyword}]")

        taken, available, unknown = check_keyword(keyword, tlds, args.workers)
        last_domains = print_results(keyword, taken, available, unknown, args.available_only)

        for r in taken + available + unknown:
            r['keyword'] = keyword
            all_results.append(r)

    # 导出
    if args.export or len(keywords) > 1:
        path = args.export or f"domains_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=['keyword','domain','tld','status','reg_year','reg_date','exp_date','registrar'])
            w.writeheader()
            for r in all_results:
                w.writerow({k: r.get(k,'') for k in w.fieldnames})
        print(f"\n📁 导出: {path}")

    total_avail = sum(1 for r in all_results if r['status'] == 'available')
    print(f"\n✅ 完成! 共 {total_avail} 个可注册域名")

    if not args.no_interactive and last_domains:
        interactive_mode(last_domains)


if __name__ == '__main__':
    main()
