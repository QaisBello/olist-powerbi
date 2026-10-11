"""Check the Power BI project without opening Power BI.

1. Every report JSON file validates against Microsoft's published JSON schema (fetched from github.com/microsoft/json-schemas,
   cached in tools/.schemas).
2. Every field a visual uses exists in the semantic model (table, column or measure, with the right kind).
3. Every [Measure] and 'Table'[Column] referenced in DAX exists, and no measure refers to itself.
4. TMDL basics: tabs for indentation, every relationship points at real columns, the date table has a key column,
   sortByColumn targets exist.

    python tools/validate.py        # exit code 1 on any problem
"""
import glob
import json
import os
import re
import sys
import urllib.request

from jsonschema import Draft7Validator
from referencing import Registry, Resource

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", ".schemas")
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/fabric/"
PREFIX = "https://developer.microsoft.com/json-schemas/fabric/"
problems = []


def fetch(uri):
    rel = uri.split("#")[0].replace(PREFIX, "")
    path = os.path.join(CACHE, rel)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        urllib.request.urlretrieve(RAW + rel, path)
    return json.load(open(path, encoding="utf-8"))


registry = Registry(retrieve=lambda uri: Resource.from_contents(fetch(uri)))


def check_json():
    files = glob.glob(os.path.join(ROOT, "**", "*.json"), recursive=True) + glob.glob(os.path.join(ROOT, "*.pbip")) + \
        glob.glob(os.path.join(ROOT, "**", "*.pbir"), recursive=True) + glob.glob(os.path.join(ROOT, "**", "*.pbism"), recursive=True)
    n = 0
    for f in sorted(set(files)):
        if any(d in f for d in ("/tools/", "/docs/", "/web/")):
            continue
        doc = json.load(open(f, encoding="utf-8"))
        uri = doc.get("$schema")
        if not uri:
            problems.append(f"{f}: no $schema")
            continue
        schema = fetch(uri)
        v = Draft7Validator(schema, registry=registry.with_resource(uri, Resource.from_contents(schema)))
        for e in v.iter_errors(doc):
            problems.append(f"{os.path.relpath(f, ROOT)}: {'/'.join(map(str, e.absolute_path))}: {e.message[:200]}")
        n += 1
    return n


def parse_model():
    model = {}
    for f in glob.glob(os.path.join(ROOT, "*.SemanticModel", "definition", "tables", "*.tmdl")):
        text = open(f, encoding="utf-8").read()
        if re.search(r"^ +\S", text, re.M) and not re.search(r"^ +\S", text.split("source = ```")[0], re.M) is None:
            pass
        head = text.split("source = ```")[0]
        if re.search(r"^ +[a-z/]", head, re.M):
            problems.append(f"{os.path.basename(f)}: TMDL uses spaces for indentation outside the M expression")
        name = re.search(r"^table (.+)$", text, re.M).group(1).strip("'")
        cols = {m.strip("'") for m in re.findall(r"^\tcolumn (.+)$", text, re.M)}
        meas = {}
        for m in re.finditer(r"^\tmeasure (.+?) =(.*?)(?=^\t\tformatString)", text, re.M | re.S):
            meas[m.group(1).strip("'")] = m.group(2)
        keys = re.findall(r"^\tcolumn (.+)\n(?:\t\t.*\n)*?\t\tisKey", text, re.M)
        sorts = re.findall(r"sortByColumn: (.+)$", text, re.M)
        model[name] = dict(columns=cols, measures=meas, keys=keys, date="dataCategory: Time" in text, sorts=[s.strip("'") for s in sorts])
    return model


def check_names(model):
    """Power BI compares names case-insensitively: 'month' and 'Month' in one table is an error on load."""
    seen = {}
    for t, d in model.items():
        names = [c.lower() for c in d["columns"]] + [m.lower() for m in d["measures"]]
        for n in {x for x in names if names.count(x) > 1}:
            problems.append(f"{t}: name '{n}' is used more than once (names are case-insensitive)")
        for m in d["measures"]:
            if m.lower() in seen:
                problems.append(f"measure {m} on {t} clashes with {seen[m.lower()]}")
            seen[m.lower()] = f"measure on {t}"
    for m, where in seen.items():
        if m in {t.lower() for t in model}:
            problems.append(f"measure {m} has the same name as a table")


def check_model(model):
    check_names(model)
    all_measures = {m: t for t, d in model.items() for m in d["measures"]}
    for t, d in model.items():
        for s in d["sorts"]:
            if s not in d["columns"]:
                problems.append(f"{t}: sortByColumn {s} is not a column")
        if d["date"] and not d["keys"]:
            problems.append(f"{t}: date table has no key column")
        for m, dax in d["measures"].items():
            for ref in re.findall(r"(?<!')\[([^\]]+)\]", re.sub(r"'[^']+'\[[^\]]+\]|\b\w+\[[^\]]+\]", "", dax)):
                if ref not in all_measures:
                    problems.append(f"measure {m}: [{ref}] is not a measure")
                if ref == m:
                    problems.append(f"measure {m}: refers to itself")
            for tbl, col in re.findall(r"'?([A-Za-z][\w ]*?)'?\[([^\]]+)\]", dax):
                tbl = tbl.strip()
                if tbl in model and col not in model[tbl]["columns"]:
                    problems.append(f"measure {m}: {tbl}[{col}] is not a column")
                elif tbl and tbl not in model and not tbl.isupper():
                    problems.append(f"measure {m}: table {tbl} not in model")
    rel = open(glob.glob(os.path.join(ROOT, "*.SemanticModel", "definition", "relationships.tmdl"))[0]).read()
    for side in re.findall(r"(?:fromColumn|toColumn): (.+)$", rel, re.M):
        m = re.match(r"('?)(.+?)\1\.('?)(.+?)\3$", side.strip())
        t, c = m.group(2), m.group(4)
        if t not in model or c not in model[t]["columns"]:
            problems.append(f"relationship column {side} not found")
    return all_measures


def check_visuals(model):
    n = 0
    for f in glob.glob(os.path.join(ROOT, "*.Report", "definition", "pages", "*", "visuals", "*", "visual.json")):
        v = json.load(open(f))
        n += 1

        def walk(o):
            if isinstance(o, dict):
                for kind in ("Column", "Measure"):
                    if kind in o and isinstance(o[kind], dict) and "Property" in o[kind]:
                        t = o[kind]["Expression"]["SourceRef"]["Entity"]
                        p = o[kind]["Property"]
                        bucket = "columns" if kind == "Column" else "measures"
                        if t not in model or p not in model[t][bucket]:
                            problems.append(f"{v['visual']['visualType']} {v['name']}: {kind} {t}.{p} not in model")
                for x in o.values():
                    walk(x)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(v)
    return n


if __name__ == "__main__":
    nj = check_json()
    model = parse_model()
    nm = check_model(model)
    nv = check_visuals(model)
    print(f"{nj} JSON files checked against Microsoft schemas, {len(model)} tables, {len(nm)} measures, {nv} visuals")
    for p in problems:
        print("PROBLEM:", p)
    sys.exit(1 if problems else 0)
