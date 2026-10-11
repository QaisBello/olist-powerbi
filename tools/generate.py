"""Generate the Power BI project (PBIP: TMDL semantic model + PBIR report) from one readable spec.

Power BI projects are plain text, so the model and report can be written, reviewed and validated like code.
This script is the single source of truth: run it after changing a table, measure or visual, then
`python tools/validate.py` to check every file against Microsoft's JSON schemas and every field reference
against the model.

    python tools/generate.py
"""
import json
import os
import shutil
import textwrap
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "Olist"
SM = os.path.join(ROOT, f"{NAME}.SemanticModel")
RP = os.path.join(ROOT, f"{NAME}.Report")
BASE_URL = "https://raw.githubusercontent.com/QaisBello/olist-dbt-warehouse/main/data/clean/"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
ACCENT, WARN, GREY, INK = "#0F766E", "#C2410C", "#B6BEB9", "#13201B"


def uid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"olist-powerbi/{seed}"))


def short(seed):
    return uid(seed).replace("-", "")[:20]


# ====================================================================== semantic model spec
# column: (name, dataType, extra properties)
TABLES = {
    "Orders": dict(
        file="fct_orders.csv", description="One row per order (dbt model fct_orders), January 2017 to August 2018.",
        filter="in_analysis_window",
        columns=[("order_id", "string", {"isKey": False}), ("customer_unique_id", "string", {"isHidden": True}),
                 ("customer_state", "string", {}), ("order_status", "string", {}), ("purchased_at", "dateTime", {"formatString": "General Date"}),
                 ("purchase_date", "dateTime", {"formatString": "Short Date", "isHidden": True}), ("items", "int64", {}), ("sellers", "int64", {}),
                 ("items_value", "decimal", {}), ("freight_value", "decimal", {}), ("order_value", "decimal", {}), ("payment_value", "decimal", {}),
                 ("payment_type", "string", {}), ("installments", "int64", {}), ("used_voucher", "boolean", {}), ("payment_mismatch", "boolean", {}),
                 ("delivered_at", "dateTime", {"formatString": "General Date"}), ("estimated_delivery_date", "dateTime", {"formatString": "Short Date"}),
                 ("delivery_days", "int64", {}), ("days_late", "int64", {}), ("is_late", "boolean", {}), ("review_score", "int64", {}),
                 ("has_comment", "boolean", {}), ("in_analysis_window", "boolean", {"isHidden": True})],
        added=[("Lateness", "string", {"sortByColumn": "Lateness Order"}), ("Lateness Order", "int64", {"isHidden": True})],
        m_extra='''
            #"Lateness Order" = Table.AddColumn(#"Filtered Rows", "Lateness Order", each
                if [days_late] = null then null
                else if [days_late] <= -15 then 1 else if [days_late] <= -8 then 2 else if [days_late] <= -1 then 3
                else if [days_late] = 0 then 4 else if [days_late] <= 3 then 5 else if [days_late] <= 7 then 6
                else if [days_late] <= 14 then 7 else 8, Int64.Type),
            #"Lateness" = Table.AddColumn(#"Lateness Order", "Lateness", each
                {null, "15+ days early", "8-14 days early", "1-7 days early", "On the day",
                 "1-3 days late", "4-7 days late", "8-14 days late", "15+ days late"}{if [Lateness Order] = null then 0 else [Lateness Order]}, type text)
        ''', m_last="Lateness"),
    "Order Items": dict(
        file="fct_order_items.csv", description="One row per item sold (dbt model fct_order_items).", filter="in_analysis_window",
        columns=[("order_id", "string", {"isHidden": True}), ("order_item_id", "int64", {}), ("product_id", "string", {"isHidden": True}),
                 ("seller_id", "string", {"isHidden": True}), ("customer_unique_id", "string", {"isHidden": True}), ("customer_state", "string", {"isHidden": True}),
                 ("purchase_date", "dateTime", {"isHidden": True, "formatString": "Short Date"}), ("order_status", "string", {"isHidden": True}),
                 ("category", "string", {"isHidden": True}), ("price", "decimal", {}), ("freight_value", "decimal", {}),
                 ("in_analysis_window", "boolean", {"isHidden": True})]),
    "Customers": dict(
        file="dim_customers.csv", description="One row per person (customer_unique_id), not per order.",
        columns=[("customer_unique_id", "string", {"isKey": True}), ("state", "string", {}), ("city", "string", {}),
                 ("first_order_at", "dateTime", {"formatString": "General Date"}), ("last_order_at", "dateTime", {"formatString": "General Date"}),
                 ("orders", "int64", {}), ("is_repeat_customer", "boolean", {})]),
    "Products": dict(
        file="dim_products.csv", description="Products with English category names.",
        columns=[("product_id", "string", {"isKey": True}), ("category", "string", {}), ("category_pt", "string", {"isHidden": True}),
                 ("weight_g", "int64", {}), ("photos", "int64", {}), ("volume_cm3", "int64", {})]),
    "Sellers": dict(
        file="dim_sellers.csv", description="Marketplace sellers.",
        columns=[("seller_id", "string", {"isKey": True}), ("state", "string", {}), ("city", "string", {})]),
    "Calendar": dict(
        file="dim_date.csv", description="Calendar from dbt (dim_date), marked as the model's date table.", date_table=True,
        columns=[("date_day", "dateTime", {"isKey": True, "formatString": "Short Date"}), ("month_start", "dateTime", {"formatString": "mmm yyyy"}),
                 ("year", "int64", {}), ("month", "int64", {"isHidden": True}), ("day_of_week", "int64", {"isHidden": True}),
                 ("is_weekend", "boolean", {}), ("in_analysis_window", "boolean", {"isHidden": True})],
        added=[("Month Name", "string", {"sortByColumn": "month_start"})],
        m_extra='''
            #"Month Name" = Table.AddColumn(#"Changed Types", "Month Name", each Date.ToText(Date.From([month_start]), "MMM yyyy", "en-GB"), type text)
        ''', m_last="Month Name"),
}

# measures: (name, folder, format, DAX, description)
MEASURES = [
    ("Order Count", "Sales", "#,0", "COUNTROWS ( Orders )", "Orders placed."),
    ("Revenue", "Sales", r'R\$#,0', "SUM ( 'Order Items'[price] )", "Value of goods sold, excluding freight (Brazilian reais)."),
    ("Freight", "Sales", r'R\$#,0', "SUM ( 'Order Items'[freight_value] )", "Freight charged to customers."),
    ("Avg Order Value", "Sales", r'R\$#,0.00', "DIVIDE ( [Revenue], [Order Count] )", "Revenue per order."),
    ("Customer Count", "Sales", "#,0", "DISTINCTCOUNT ( Orders[customer_unique_id] )", "Distinct people who ordered."),
    ("Revenue LY", "Sales", r'R\$#,0', "CALCULATE ( [Revenue], SAMEPERIODLASTYEAR ( 'Calendar'[date_day] ) )", "Revenue in the same period a year earlier."),
    ("Revenue YoY %", "Sales", "0.0%;-0.0%;0.0%", """
VAR _ly = [Revenue LY]
RETURN
    IF ( NOT ISBLANK ( _ly ), DIVIDE ( [Revenue] - _ly, _ly ) )""", "Change in revenue against the same period a year earlier."),
    ("Revenue Running Total", "Sales", r'R\$#,0', """
CALCULATE (
    [Revenue],
    FILTER ( ALL ( 'Calendar'[date_day] ), 'Calendar'[date_day] <= MAX ( 'Calendar'[date_day] ) )
)""", "Cumulative revenue up to the latest date in context."),
    ("Delivered Orders", "Delivery", "#,0", """
CALCULATE (
    COUNTROWS ( Orders ),
    Orders[order_status] = "delivered",
    NOT ISBLANK ( Orders[delivered_at] )
)""", "Orders delivered, with a delivery date recorded."),
    ("Late Orders", "Delivery", "#,0", "CALCULATE ( [Delivered Orders], Orders[is_late] == TRUE () )", "Delivered after the date promised at checkout."),
    ("% Late", "Delivery", "0.0%", "DIVIDE ( [Late Orders], [Delivered Orders] )", "Share of delivered orders that arrived late."),
    ("Avg Delivery Days", "Delivery", "0.0", "CALCULATE ( AVERAGE ( Orders[delivery_days] ), Orders[order_status] = \"delivered\" )", "Days from purchase to delivery."),
    ("Avg Review", "Reviews", "0.00", "AVERAGE ( Orders[review_score] )", "Average review score, 1 to 5."),
    ("Avg Review (Delivered)", "Reviews", "0.00", "CALCULATE ( [Avg Review], KEEPFILTERS ( NOT ISBLANK ( Orders[Lateness] ) ) )",
     "Average review for delivered orders only. KEEPFILTERS keeps the chart's own Lateness filter, so the blank (not delivered) band returns BLANK and drops out."),
    ("Avg Review (On Time)", "Reviews", "0.00", "CALCULATE ( [Avg Review], Orders[is_late] == FALSE () )", "Average review for orders delivered on or before the promised date."),
    ("Avg Review (Late)", "Reviews", "0.00", "CALCULATE ( [Avg Review], Orders[is_late] == TRUE () )", "Average review for orders delivered late."),
    ("Review Gap", "Reviews", "0.00", "[Avg Review (On Time)] - [Avg Review (Late)]", "How many stars a late delivery costs."),
    ("% One-Star", "Reviews", "0.0%", """
DIVIDE (
    CALCULATE ( COUNTROWS ( Orders ), Orders[review_score] = 1 ),
    CALCULATE ( COUNTROWS ( Orders ), NOT ISBLANK ( Orders[review_score] ) )
)""", "Share of reviewed orders rated one star."),
    ("Repeat Customer %", "Customers", "0.0%", """
DIVIDE (
    CALCULATE ( COUNTROWS ( Customers ), Customers[is_repeat_customer] == TRUE () ),
    COUNTROWS ( Customers )
)""", "Share of customers who ordered more than once."),
]

RELATIONSHIPS = [  # (from many, to one, extra)
    (("Orders", "purchase_date"), ("Calendar", "date_day"), {}),
    (("Orders", "customer_unique_id"), ("Customers", "customer_unique_id"), {}),
    (("Order Items", "order_id"), ("Orders", "order_id"), {"crossFilteringBehavior": "bothDirections"}),
    (("Order Items", "product_id"), ("Products", "product_id"), {}),
    (("Order Items", "seller_id"), ("Sellers", "seller_id"), {}),
]

M_TYPES = {"string": "type text", "int64": "Int64.Type", "decimal": "Currency.Type", "double": "type number",
           "dateTime": "type datetime", "boolean": "type logical"}
FORMAT = {"int64": "0", "decimal": "#,0.00"}


def q(name):
    """quote a TMDL name when it is not a plain identifier"""
    return name if name.replace("_", "").isalnum() else f"'{name}'"


def ind(text, n):
    return textwrap.indent(textwrap.dedent(text).strip("\n"), "\t" * n)


def table_tmdl(name, t):
    out = [f"/// {t['description']}", f"table {q(name)}"]
    if t.get("date_table"):
        out.append("\tdataCategory: Time")
    out.append("")
    if name == "Orders":
        for m, folder, fmt, dax, desc in MEASURES:
            out.append(f"\t/// {desc}")
            if "\n" in dax.strip():
                out.append(f"\tmeasure {q(m)} =")
                out.append(ind(dax, 3))
            else:
                out.append(f"\tmeasure {q(m)} = {dax.strip()}")
            out.append(f"\t\tformatString: {fmt}")
            out.append(f"\t\tdisplayFolder: {folder}")
            out.append("")
    for col, typ, extra in t["columns"] + t.get("added", []):
        out.append(f"\tcolumn {q(col)}")
        out.append(f"\t\tdataType: {typ}")
        if extra.get("isHidden"):
            out.append("\t\tisHidden")
        if extra.get("isKey"):
            out.append("\t\tisKey")
        fmt = extra.get("formatString", FORMAT.get(typ))
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out.append("\t\tsummarizeBy: none")
        out.append(f"\t\tsourceColumn: {col}")
        if extra.get("sortByColumn"):
            out.append(f"\t\tsortByColumn: {q(extra['sortByColumn'])}")
        out.append("")
    # Power Query (M) partition reading the dbt export straight from GitHub
    types = ",\n".join(f'{{"{c}", {M_TYPES[ty]}}}' for c, ty, _ in t["columns"])
    filt = f'\n#"Filtered Rows" = Table.SelectRows(#"Changed Types", each [{t["filter"]}] = true),' if t.get("filter") else \
        '\n#"Filtered Rows" = #"Changed Types",'
    extra = textwrap.dedent(t.get("m_extra", "").strip("\n").rstrip()).strip("\n")
    last = t.get("m_last", "Filtered Rows")
    m = f'''let
    Source = Csv.Document(
        Web.Contents(BaseUrl, [RelativePath = "{t['file']}"]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // empty cells arrive as "" and would fail the type change (e.g. is_late for undelivered orders): make them null
    #"Blanks to Null" = Table.TransformColumns(#"Promoted Headers", {{}}, each if _ = "" then null else _),
    #"Changed Types" = Table.TransformColumnTypes(
        #"Blanks to Null",
        {{
{textwrap.indent(types, " " * 12)}
        }},
        "en-US"
    ),{textwrap.indent(filt, "    ")}{(chr(10) + textwrap.indent(extra, "    ") + ",") if extra else ""}
    Result = #"{last}"
in
    Result'''
    if t.get("date_table"):
        m = m.replace('    #"Filtered Rows" = #"Changed Types",\n', "")
    out.append(f"\tpartition {q(name)} = m")
    out.append("\t\tmode: import")
    out.append("\t\tsource = ```")
    out.append(textwrap.indent(m, "\t\t\t\t"))
    out.append("\t\t\t\t```")
    out.append("")
    return "\n".join(out) + "\n"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def jwrite(path, obj):
    write(path, json.dumps(obj, indent=2) + "\n")


def semantic_model():
    shutil.rmtree(SM, ignore_errors=True)
    jwrite(os.path.join(SM, "definition.pbism"), {"$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                                    "version": "4.2", "settings": {"qnaEnabled": True}})
    d = os.path.join(SM, "definition")
    write(os.path.join(d, "database.tmdl"), "database\n\tcompatibilityLevel: 1601\n")
    refs = "\n".join(f"ref table {q(t)}" for t in TABLES)
    write(os.path.join(d, "model.tmdl"), f"""model Model
\tculture: en-GB
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tdiscourageImplicitMeasures
\tsourceQueryCulture: en-GB
\tdataAccessOptions
\t\tlegacyRedirects
\t\treturnErrorValuesAsNull

{refs}
""")
    write(os.path.join(d, "expressions.tmdl"),
          f'/// Folder of CSVs exported by the dbt warehouse (github.com/QaisBello/olist-dbt-warehouse). Point it at a local folder or another branch to test.\n'
          f'expression BaseUrl = "{BASE_URL}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n')
    rels = []
    for (ft, fc), (tt, tc), extra in RELATIONSHIPS:
        r = [f"relationship {uid(f'{ft}.{fc}->{tt}.{tc}')}"]
        for k, v in extra.items():
            r.append(f"\t{k}: {v}")
        r += [f"\tfromColumn: {q(ft)}.{q(fc)}", f"\ttoColumn: {q(tt)}.{q(tc)}"]
        rels.append("\n".join(r))
    write(os.path.join(d, "relationships.tmdl"), "\n\n".join(rels) + "\n")
    for name, t in TABLES.items():
        write(os.path.join(d, "tables", f"{name}.tmdl"), table_tmdl(name, t))


# ====================================================================== report spec
def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": f"'{v}'"}}}


def field(kind, table, prop):
    return {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": prop}}


def proj(kind, table, prop, display=None):
    p = {"field": field(kind, table, prop), "queryRef": f"{table}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


M = lambda name, display=None: proj("Measure", "Orders", name, display)
C = lambda table, col, display=None: proj("Column", table, col, display)


def title(text):
    return {"title": [{"properties": {"show": lit(True), "text": lit(text), "fontSize": lit(12)}}]}


def visual(page, key, vtype, x, y, w, h, roles, title_text=None, objects=None, sort=None, z=0):
    v = {"visualType": vtype, "query": {"queryState": {r: {"projections": p} for r, p in roles.items()}}, "drillFilterOtherVisuals": True}
    if sort:
        v["query"]["sortDefinition"] = {"sort": [{"field": sort[0]["field"], "direction": sort[1]}], "isDefaultSort": False}
    if objects:
        v["objects"] = objects
    if title_text:
        v["visualContainerObjects"] = title(title_text)
    name = short(f"{page}/{key}")
    return name, {"$schema": f"{SCHEMA}/item/report/definition/visualContainer/2.4.0/schema.json", "name": name,
                  "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}, "visual": v}


def fill(color):
    return {"dataPoint": [{"properties": {"fill": {"solid": {"color": lit(color)}}}}]}


def card(page, key, x, measure, label):
    return visual(page, key, "card", x, 76, 236, 104, {"Values": [M(measure, label)]}, objects={
        "labels": [{"properties": {"fontSize": lit(26), "labelDisplayUnits": lit(1), "color": {"solid": {"color": lit(INK)}}}}],
        "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(11)}}]}, z=x)


def text_box(page, key, x, y, w, h, text, size, bold=False, color=INK):
    run = {"value": text, "textStyle": {"fontSize": f"{size}pt", "color": color, **({"fontWeight": "bold"} if bold else {})}}
    name = short(f"{page}/{key}")
    return name, {"$schema": f"{SCHEMA}/item/report/definition/visualContainer/2.4.0/schema.json", "name": name,
                  "position": {"x": x, "y": y, "z": 0, "width": w, "height": h, "tabOrder": 0},
                  "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [run]}]}}]}}}


def pages():
    p1, p2 = "delivery", "categories"
    v1 = [
        text_box(p1, "title", 24, 12, 900, 56, "Late parcels, angry customers · Olist orders Jan 2017 – Aug 2018", 18, bold=True),
        card(p1, "orders", 24, "Order Count", "Orders"),
        card(p1, "revenue", 272, "Revenue", "Revenue (R$)"),
        card(p1, "late", 520, "% Late", "Delivered late"),
        card(p1, "ontime", 768, "Avg Review (On Time)", "Review if on time"),
        card(p1, "latereview", 1016, "Avg Review (Late)", "Review if late"),
        visual(p1, "lateness", "clusteredColumnChart", 24, 196, 612, 300,
               {"Category": [C("Orders", "Lateness", "Delivery against promised date")], "Y": [M("Avg Review (Delivered)", "Avg Review")]},
               "Average review by how late the parcel arrived", objects={**fill(WARN), "labels": [{"properties": {"show": lit(True)}}]},
               sort=(C("Orders", "Lateness"), "Ascending"), z=10),
        visual(p1, "states", "clusteredBarChart", 652, 196, 604, 300,
               {"Category": [C("Orders", "customer_state", "Customer state")], "Y": [M("% Late")]},
               "Share delivered late, by customer state", objects=fill(ACCENT), sort=(M("% Late"), "Descending"), z=11),
        visual(p1, "monthly", "lineChart", 24, 512, 900, 196,
               {"Category": [C("Calendar", "month_start", "Month")], "Y": [M("Order Count", "Orders")]}, "Orders by month",
               objects={"dataPoint": [{"properties": {"fill": {"solid": {"color": lit(ACCENT)}}}}]}, z=12),
        visual(p1, "category", "slicer", 940, 512, 316, 196, {"Values": [C("Products", "category", "Product category")]},
               "Filter by product category", objects={"data": [{"properties": {"mode": lit("Dropdown")}}]}, z=13),
    ]
    v2 = [
        text_box(p2, "title", 24, 12, 900, 56, "Product categories: revenue, lateness and reviews", 18, bold=True),
        visual(p2, "table", "tableEx", 24, 76, 760, 632,
               {"Values": [C("Products", "category", "Category"), M("Revenue"), M("Order Count", "Orders"), M("Avg Order Value"),
                           M("% Late"), M("Avg Review"), M("% One-Star")]},
               "Categories ranked by revenue", sort=(M("Revenue"), "Descending"), z=10),
        visual(p2, "scatter", "scatterChart", 800, 76, 456, 400,
               {"Category": [C("Products", "category", "Category")], "X": [M("% Late")], "Y": [M("Avg Review")], "Size": [M("Order Count", "Orders")]},
               "Lateness against reviews, by category", objects=fill(WARN), z=11),
        card(p2, "gap", 800, "Review Gap", "Stars lost to a late delivery"),
        card(p2, "repeat", 1032, "Repeat Customer %", "Customers who came back"),
    ]
    # cards on page 2 sit under the scatter
    for name, v in v2[-2:]:
        v["position"].update(y=496, width=220 if v["position"]["x"] == 800 else 224)
    return [(p1, "Delivery and reviews", v1), (p2, "Categories", v2)]


def report():
    shutil.rmtree(RP, ignore_errors=True)
    jwrite(os.path.join(RP, "definition.pbir"), {"$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
                                                  "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    d = os.path.join(RP, "definition")
    jwrite(os.path.join(d, "version.json"), {"$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    jwrite(os.path.join(d, "report.json"), {"$schema": f"{SCHEMA}/item/report/definition/report/3.0.0/schema.json", "themeCollection": {}})
    ps = pages()
    jwrite(os.path.join(d, "pages", "pages.json"), {"$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
                                                     "pageOrder": [short(p) for p, _, _ in ps], "activePageName": short(ps[0][0])})
    for key, display, visuals in ps:
        pid = short(key)
        jwrite(os.path.join(d, "pages", pid, "page.json"), {"$schema": f"{SCHEMA}/item/report/definition/page/2.0.0/schema.json",
                                                             "name": pid, "displayName": display, "displayOption": "FitToPage",
                                                             "height": 720, "width": 1280})
        for name, v in visuals:
            jwrite(os.path.join(d, "pages", pid, "visuals", name, "visual.json"), v)


def pbip():
    jwrite(os.path.join(ROOT, f"{NAME}.pbip"), {"$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
                                                "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})


def measures_doc():
    lines = ["# Measures", "", "Generated from `tools/generate.py`. All measures live on the `Orders` table, grouped in display folders.", ""]
    for m, folder, fmt, dax, desc in MEASURES:
        lines += [f"## {m}", "", f"*{folder}* · format `{fmt}` · {desc}", "", "```dax", f"{m} =", textwrap.dedent(dax).strip(), "```", ""]
    write(os.path.join(ROOT, "docs", "measures.md"), "\n".join(lines))


def model_json():
    """The model as JSON for the web page: tables, columns, relationships, measures and the report layout."""
    tables = [dict(name=t, file=d["file"], description=d["description"], date=bool(d.get("date_table")),
                   columns=[dict(name=c, type=ty, hidden=bool(x.get("isHidden")), key=bool(x.get("isKey"))) for c, ty, x in d["columns"] + d.get("added", [])])
              for t, d in TABLES.items()]
    rels = [dict(fromTable=a[0], fromColumn=a[1], toTable=b[0], toColumn=b[1], both=x.get("crossFilteringBehavior") == "bothDirections")
            for a, b, x in RELATIONSHIPS]
    meas = [dict(name=m, folder=f, format=fmt, dax=textwrap.dedent(dax).strip(), description=desc) for m, f, fmt, dax, desc in MEASURES]
    layout = [dict(page=title, visuals=[dict(type=v["visual"]["visualType"], **{k: v["position"][k] for k in ("x", "y", "width", "height")})
                                        for _, v in vs]) for _, title, vs in pages()]
    os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
    json.dump(dict(tables=tables, relationships=rels, measures=meas, pages=layout, base_url=BASE_URL),
              open(os.path.join(ROOT, "web", "data", "model.json"), "w"), indent=1)


if __name__ == "__main__":
    semantic_model()
    model_json()
    report()
    pbip()
    measures_doc()
    print("generated", NAME, "semantic model,", sum(len(v) for _, _, v in pages()), "visuals on", len(pages()), "pages,", len(MEASURES), "measures")
