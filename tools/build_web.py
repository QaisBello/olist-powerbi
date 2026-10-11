"""Wrap web/template.html into a standalone page, web/index.html (reads web/data/*.json from GitHub, or locally).

    python tools/build_web.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
body = open(os.path.join(ROOT, "web", "template.html"), encoding="utf-8").read().replace("<!--SITEBAR-->", "")
doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n'
       "</head>\n<body>\n" + body + "\n</body>\n</html>\n")
open(os.path.join(ROOT, "web", "index.html"), "w", encoding="utf-8").write(doc)
print("web/index.html")
