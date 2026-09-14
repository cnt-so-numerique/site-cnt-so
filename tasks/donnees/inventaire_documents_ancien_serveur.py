import re, sys, json, urllib.request, urllib.parse, concurrent.futures as cf, html
BASE="https://testwp.cnt-so.org/wp-content/uploads/"
DOC=re.compile(r'\.(pdf|odt|ods|odp|doc|docx|xls|xlsx|ppt|pptx|zip|mp3|mp4|ogg|wav|m4a|avi|mov|epub|rtf|txt)$', re.I)
ROW=re.compile(r'<a href="([^"?][^"]*)">.*?</a>\s*</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>\s*([^<]*)</td>', re.S)
def get(u):
    for _ in range(3):
        try: return urllib.request.urlopen(u, timeout=30).read().decode('utf-8','replace')
        except Exception as e: err=e
    print("ECHEC", u, err, file=sys.stderr); return ""
docs=[]; dirs=[BASE]; seen=set(); n=0
with cf.ThreadPoolExecutor(6) as ex:
    while dirs:
        batch=[d for d in dirs if d not in seen]; dirs=[]
        seen.update(batch)
        for d,page in zip(batch, ex.map(get,batch)):
            n+=1
            rows=ROW.findall(page)
            if not rows:  # autre format de listing
                rows=[(h,'','') for h in re.findall(r'href="([^"?][^"]*)"',page)]
            for href,date,size in rows:
                if href.startswith(('/', 'http')) or href in ('../',): continue
                u=urllib.parse.urljoin(d, href)
                if href.endswith('/'): dirs.append(u)
                elif DOC.search(href): docs.append({"url":u,"nom":urllib.parse.unquote(href),"taille":size.strip(),"date":date.strip()})
print(n,"dossiers,",len(docs),"documents", file=sys.stderr)
json.dump(docs, open(sys.argv[1],"w"), ensure_ascii=False, indent=0)
