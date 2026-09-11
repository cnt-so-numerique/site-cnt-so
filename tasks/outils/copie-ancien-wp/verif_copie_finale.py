#!/usr/bin/env python3
"""Contrôle final de la copie de l'ancien WordPress (lecture seule)."""
import os, re, json, subprocess, urllib.request
from urllib.parse import urlparse, unquote, urljoin

A = "/var/www/cntso/archive-wp"
UA = {"User-Agent": "audit"}
SITES = ["https://cnt-so.org", "https://educ.cnt-so.org", "https://cnt-so.org/13", "https://cnt-so.org/auvergne",
         "https://cnt-so.org/poitiers", "https://cnt-so.org/rhone-alpes", "https://cnt-so.org/numerique",
         "https://cnt-so.org/staa", "https://cnt-so.org/education"]

def liens(base):
    out, page = [], 1
    while page <= 20:
        try:
            arr = json.load(urllib.request.urlopen(urllib.request.Request(
                f"{base}/wp-json/wp/v2/posts?per_page=100&page={page}&_fields=link", headers=UA), timeout=40))
        except Exception:
            break
        if not arr:
            break
        out += [p["link"] for p in arr]
        page += 1
    return out

print("=== 1. articles publiés / copiés ===")
tot_pub = tot_manq = 0
for base in SITES:
    ls = liens(base)
    manq = [l for l in ls if not os.path.isfile(os.path.join(
        A, urlparse(l).netloc, unquote(urlparse(l).path).lstrip("/"), "index.html"))]
    tot_pub += len(ls); tot_manq += len(manq)
    print(f"  {base:32} {len(ls):4} publiés · {len(ls) - len(manq):4} copiés" + (f" · MANQUANTS {len(manq)}" if manq else ""))
    for m in manq[:2]:
        print("       ex.", urlparse(m).path[:90])
print(f"  TOTAL : {tot_pub} articles, {tot_manq} manquant(s)")

print("\n=== 2. ressources encore citées en adresse absolue, et srcset ===")
RES = re.compile(r'https?://((?:educ\.)?cnt-so\.org)(/[^"\'\s<>()]*?/?wp-(?:content|includes)/[^"\'\s<>()?#]+)')
absentes, srcset, pages = set(), 0, 0
for r, _, fs in os.walk(A):
    for f in fs:
        if f.endswith(".html"):
            pages += 1
            with open(os.path.join(r, f), encoding="utf-8", errors="ignore") as fh:
                s = fh.read()
            srcset += len(re.findall(r'\ssrcset="', s, re.I))
            for h, c in RES.findall(s):
                if not os.path.exists(os.path.join(A, h, unquote(c).lstrip("/"))):
                    absentes.add(h + c)
print(f"  pages : {pages} · srcset restants : {srcset} · ressources absentes citées en absolu : {len(absentes)}")
for x in sorted(absentes)[:5]:
    print("       ex.", x[:95])

print("\n=== 3. rendu par old.cnt-so.org, feuilles de style comprises ===")
def get(chemin):
    r = subprocess.run(["curl", "-s", "--resolve", "old.cnt-so.org:80:127.0.0.1", "-w", "\n%{http_code}",
                        f"http://old.cnt-so.org{chemin}"], capture_output=True, text=True)
    corps, _, code = r.stdout.rpartition("\n")
    return code, corps
for chemin in ("/cnt-so.org/", "/educ.cnt-so.org/", "/cnt-so.org/13/", "/cnt-so.org/auvergne/",
               "/cnt-so.org/rhone-alpes/", "/cnt-so.org/staa/", "/cnt-so.org/poitiers/"):
    code, corps = get(chemin)
    css = re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']', corps)
    # Adresses relatives résolues par rapport à la page : ne compter que celles
    # qui commencent par « / » faisait croire à des styles manquants (11/09).
    locales = [urljoin(chemin, h.split("?")[0]) for h in css if not h.startswith("http")]
    css_ok = sum(1 for h in locales if get(h)[0] == "200")
    print(f"  {chemin:26} {code} · feuilles de style : {len(css)} citées, {css_ok} servies en local"
          + (f", {len(css) - len(locales)} encore en adresse absolue" if len(css) > len(locales) else ""))
