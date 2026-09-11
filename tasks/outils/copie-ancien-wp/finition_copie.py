#!/usr/bin/env python3
"""Rend la copie de l'ancien WordPress autonome.

Trois défauts relevés le 11/09/2026, tous invisibles tant que cnt-so.org
pointe sur l'ancien serveur, tous fatals après la bascule :
- feuilles de style et scripts cités avec un ?ver=, que la copie a écartés ;
- images en tailles alternatives dans srcset, que la copie ne suit pas — et un
  navigateur qui choisit une taille de srcset ne se rabat pas sur src ;
- adresses absolues vers cnt-so.org, qui mèneraient au nouveau site.

Simulation par défaut ; --ecrire pour agir (sauvegarde des HTML et CSS avant).
"""
import os, re, sys, tarfile, time, posixpath, urllib.request
from urllib.parse import unquote, quote

A = "/var/www/cntso/archive-wp"
ECRIRE = "--ecrire" in sys.argv
# --sauf=a,b : arborescences à ne pas toucher (une copie wget encore en cours
# les réécrira elle-même à sa fin, à partir de positions notées au téléchargement).
SAUF = [x.strip("/") for a in sys.argv if a.startswith("--sauf=") for x in a.split("=", 1)[1].split(",") if x]

def exclu(racine):
    rel = os.path.relpath(racine, A)
    return any(rel == s or rel.startswith(s + os.sep) for s in SAUF)
UA = {"User-Agent": "archive-cntso"}
# staa-cnt-so.org : le sous-site /staa/ est le site propre du STAA, dont les
# ressources vivent sur ce domaine — qui a eu des ratés DNS et de certificat
# (10/09/2026). Ses styles sont rapatriés ; ses pages restent des liens vivants.
ABS = re.compile(r'https?://((?:educ\.)?cnt-so\.org|staa-cnt-so\.org)(/[^"\'\s<>()]*)')
# Styles, scripts, polices, images — et les documents joints aux articles :
# 5 PDF n'avaient jamais été copiés (relevé le 11/09/2026).
TELECHARGEABLE = re.compile(r'/wp-(?:content|includes)/.*\.(?:css|js|woff2?|ttf|eot|otf|svg|png|jpe?g|gif|webp|ico|pdf|docx?|odt|ods|xlsx?|pptx?|zip|mp[34])$', re.I)
SRCSET = re.compile(r'\s(?:srcset|sizes|data-srcset)="[^"]*"', re.I)
URL_CSS = re.compile(r'url\(\s*([\'"]?)([^\'")]+)\1\s*\)')

st = dict(pages=0, pages_modifiees=0, reecrites=0, laissees=0, srcset=0,
          telechargees=0, echecs=0, css=0)
a_telecharger = set()

def propre(chemin):
    return unquote(chemin.split("#")[0].split("?")[0])

def local(hote, chemin):
    base = os.path.join(A, hote, propre(chemin).lstrip("/"))
    for cand in (base, os.path.join(base, "index.html"), base + ".html"):
        if os.path.isfile(cand):
            return cand
    return None

def telecharge(hote, chemin):
    p = propre(chemin)
    dest = os.path.join(A, hote, p.lstrip("/"))
    if os.path.isfile(dest):
        return dest
    if not ECRIRE:
        a_telecharger.add(hote + p)
        return dest
    try:
        data = urllib.request.urlopen(urllib.request.Request(
            f"https://{hote}{quote(p, safe='/')}", headers=UA), timeout=40).read()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
        st["telechargees"] += 1
        time.sleep(0.1)          # l'ancienne machine est fragile
        return dest
    except Exception:
        st["echecs"] += 1
        return None

def remplace(m):
    hote, chemin = m.group(1), m.group(2)
    ancre = "#" + chemin.split("#", 1)[1] if "#" in chemin else ""
    p = chemin.split("#")[0].split("?")[0]
    if local(hote, p) or (TELECHARGEABLE.search(p) and telecharge(hote, p)):
        st["reecrites"] += 1
        return f"/{hote}{p}{ancre}"
    st["laissees"] += 1
    return m.group(0)

if ECRIRE:
    sauvegarde = os.path.expanduser(f"~/archive-wp-html-avant-finition-{time.strftime('%Y%m%d-%H%M')}.tgz")
    with tarfile.open(sauvegarde, "w:gz") as t:
        for r, _, fs in os.walk(A):
            for f in fs:
                if f.endswith((".html", ".css")):
                    p = os.path.join(r, f)
                    t.add(p, arcname=os.path.relpath(p, A))
    print("sauvegarde :", sauvegarde)

# 1. Les pages
for r, _, fs in os.walk(A):
    if exclu(r):
        continue
    for f in fs:
        if not f.endswith(".html"):
            continue
        p = os.path.join(r, f)
        st["pages"] += 1
        with open(p, encoding="utf-8", errors="surrogateescape") as fh:
            s = fh.read()
        n = len(SRCSET.findall(s))
        s2 = ABS.sub(remplace, SRCSET.sub("", s))
        st["srcset"] += n
        if s2 != s:
            st["pages_modifiees"] += 1
            if ECRIRE:
                with open(p, "w", encoding="utf-8", errors="surrogateescape") as fh:
                    fh.write(s2)

# 2. Les feuilles de style : leurs url(...) — polices, images de fond
for r, _, fs in os.walk(A):
    if exclu(r):
        continue
    for f in fs:
        if not f.endswith(".css"):
            continue
        p = os.path.join(r, f)
        st["css"] += 1
        hote_rel = os.path.relpath(p, A).split(os.sep)
        hote, url_css = hote_rel[0], "/" + "/".join(hote_rel[1:])
        with open(p, encoding="utf-8", errors="surrogateescape") as fh:
            s = fh.read()
        def dans_css(m):
            ref = m.group(2).strip()
            if ref.startswith(("data:", "#")):
                return m.group(0)
            ma = ABS.match(ref)
            if ma:
                return f"url({m.group(1)}{remplace(ma)}{m.group(1)})"
            cible = posixpath.normpath(posixpath.join(posixpath.dirname(url_css), ref.split("?")[0].split("#")[0]))
            if not local(hote, cible) and TELECHARGEABLE.search(cible):
                telecharge(hote, cible)
            return m.group(0)
        s2 = URL_CSS.sub(dans_css, s)
        if s2 != s and ECRIRE:
            with open(p, "w", encoding="utf-8", errors="surrogateescape") as fh:
                fh.write(s2)

print("MODE", "ÉCRITURE" if ECRIRE else "SIMULATION")
print(f"pages : {st['pages']} · à modifier : {st['pages_modifiees']} · attributs srcset retirés : {st['srcset']}")
print(f"adresses réécrites vers la copie : {st['reecrites']} · laissées telles quelles : {st['laissees']}")
print(f"feuilles de style examinées : {st['css']}")
if ECRIRE:
    print(f"fichiers rapatriés : {st['telechargees']} · échecs : {st['echecs']}")
else:
    print(f"fichiers à rapatrier : {len(a_telecharger)}")
    ext = {}
    for x in a_telecharger:
        e = os.path.splitext(x)[1].lower(); ext[e] = ext.get(e, 0) + 1
    print("  par type :", dict(sorted(ext.items(), key=lambda kv: -kv[1])))
