from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


OUT = Path("ospool_manager_overview.pptx")
SLIDE_W = 13_333_333
SLIDE_H = 7_500_000

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def emu(inches: float) -> int:
    return int(inches * 914400)


def text_run(text: str, size: int = 22, bold: bool = False, color: str = "1E293B") -> str:
    b = ' b="1"' if bold else ""
    return (
        f'<a:r><a:rPr lang="en-US" sz="{size * 100}"{b}>'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f"</a:rPr><a:t>{escape(text)}</a:t></a:r>"
    )


def paragraph(text: str, size: int = 22, bold: bool = False, color: str = "1E293B", level: int = 0) -> str:
    mar_l = level * 342900
    indent = -228600 if level else 0
    bu = '<a:buChar char="•"/>' if level or size <= 24 else '<a:buNone/>'
    return (
        f'<a:p><a:pPr marL="{mar_l}" indent="{indent}">{bu}</a:pPr>'
        f"{text_run(text, size=size, bold=bold, color=color)}</a:p>"
    )


def textbox(shape_id: int, x: float, y: float, w: float, h: float, paras: list[str], fill: str | None = None) -> str:
    fill_xml = (
        f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln><a:noFill/></a:ln>'
        if fill
        else '<a:noFill/><a:ln><a:noFill/></a:ln>'
    )
    return f"""
    <p:sp>
      <p:nvSpPr><p:cNvPr id="{shape_id}" name="Text {shape_id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        {fill_xml}
      </p:spPr>
      <p:txBody>
        <a:bodyPr wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720"/>
        <a:lstStyle/>
        {''.join(paras)}
      </p:txBody>
    </p:sp>
    """


def rect(shape_id: int, x: float, y: float, w: float, h: float, fill: str) -> str:
    return f"""
    <p:sp>
      <p:nvSpPr><p:cNvPr id="{shape_id}" name="Rect {shape_id}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        <a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln><a:noFill/></a:ln>
      </p:spPr>
    </p:sp>
    """


def slide_xml(idx: int, title: str, bullets: list[str], subtitle: str | None = None, code: str | None = None) -> str:
    shapes = [
        rect(2, 0, 0, 13.333, 0.18, "0F766E"),
        textbox(3, 0.55, 0.35, 12.1, 0.75, [paragraph(title, size=32, bold=True, color="0F172A")]),
    ]
    next_id = 4
    y = 1.25
    if subtitle:
        shapes.append(textbox(next_id, 0.62, 1.02, 11.7, 0.45, [paragraph(subtitle, size=17, color="475569")]))
        next_id += 1
        y = 1.55

    body_paras = [paragraph(b, size=20, color="1E293B", level=1) for b in bullets]
    body_h = 3.8 if code else 5.0
    shapes.append(textbox(next_id, 0.75, y, 11.85, body_h, body_paras))
    next_id += 1

    if code:
        code_paras = [paragraph(line, size=14, color="E2E8F0") for line in code.splitlines()]
        shapes.append(textbox(next_id, 0.85, 5.32, 11.65, 1.18, code_paras, fill="0F172A"))
        next_id += 1

    shapes.append(textbox(next_id, 0.62, 7.02, 11.8, 0.28, [paragraph(f"OSPool Manager | {idx}", size=10, color="64748B")]))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="{NS['a']}" xmlns:r="{NS['r']}" xmlns:p="{NS['p']}">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="F8FAFC"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


SLIDES = [
    {
        "title": "OSPool Manager",
        "subtitle": "Python CLI for repeatable HTCondor/OSPool workflows from local machines or an Access Point",
        "bullets": [
            "Wraps common OSPool operations into a single Typer command line: setup, sync, submit, monitor, report, watch, fetch, upload, and OSDF listing.",
            "Supports two operating modes: local remote-submit with HTCondor token auth, and AP-project execution after syncing the project to the Access Point.",
            "Keeps workflow assets organized under execution/, with runtime logs, outputs, and run metadata isolated from source files.",
        ],
    },
    {
        "title": "Problem It Solves",
        "subtitle": "OSPool jobs have several moving parts; this project turns them into a predictable loop.",
        "bullets": [
            "Reduces manual SSH, rsync, condor_submit, condor_q, condor_history, and output retrieval steps.",
            "Makes submit files easier to reuse by resolving shorthand names and keeping local/AP paths in configuration.",
            "Provides a project-specific path for container jobs, data staging, large output handling, and post-run reporting.",
        ],
    },
    {
        "title": "Workflow Model",
        "subtitle": "The README workflow maps directly to CLI modules.",
        "bullets": [
            "Setup creates the remote project tree on ap40.uw.osg-htc.org and sync copies the local project while excluding logs, outputs, runs, venvs, caches, and data by default.",
            "Submit sends single .sub jobs or DAGMan workflows to the AP schedd through htcondor2 bindings.",
            "Monitor, logs, report, watch, and fetch cover the operational loop from live status through completed output collection.",
        ],
        "code": "ospool setup remote\nospool sync remote\nospool submit job patchwork_direct\nospool monitor <cluster>\nospool watch\nospool fetch <cluster>",
    },
    {
        "title": "Architecture",
        "subtitle": "Small modules with explicit responsibilities.",
        "bullets": [
            "cli.py defines the Typer surface and delegates work to focused implementation modules.",
            "config.py loads config.toml into typed dataclasses for remote, OSDF, local, and submit settings.",
            "submit.py owns HTCondor schedd access, submit modes, DAG submission, and job removal.",
            "monitor.py and watcher.py handle live queue views, reports, and automatic fetch on completion.",
            "remote.py, upload.py, osdf.py, fetch.py, token.py, and runs.py cover AP operations, storage, auth, retrieval, and SQLite run tracking.",
        ],
    },
    {
        "title": "Configuration",
        "subtitle": "Most environment-specific details are centralized in config.toml.",
        "bullets": [
            "Remote settings identify the AP, schedd, collector, username, SSH key, and remote project directory.",
            "OSDF settings define the user's large-storage root, such as osdf:///ospool/ap40/data/lucas.ferguson.",
            "Local settings define project, execution, data, logs, outputs, and runs directories.",
            "Submit mode chooses between spool for local remote-submit and ap-project for synced AP execution.",
        ],
    },
    {
        "title": "Submit Modes",
        "subtitle": "The project supports two deployment shapes without changing the CLI.",
        "bullets": [
            "spool mode uses schedd.submit(spool=True) followed by schedd.spool(), so local files are transferred from the submitting machine.",
            "ap-project mode injects initialdir = remote.project_dir and expects files to already exist on the Access Point.",
            "For AP-project mode, submit.py verifies the remote project directory and gives a targeted setup/sync instruction if it is missing.",
        ],
    },
    {
        "title": "Data and Output Handling",
        "subtitle": "The code handles both OSDF storage and AP-home output fallbacks.",
        "bullets": [
            "upload.py pushes files or data/ to the OSDF origin via rsync, falling back to scp if rsync is unavailable.",
            "Submit files can reference OSDF URLs as transfer inputs and remap outputs back into OSDF outputs/.",
            "fetch.py first searches AP project outputs, then OSDF outputs, rsyncs matching cluster files locally, and also syncs cluster logs.",
            "retrieve_spool handles jobs without OSDF output remaps by running condor_transfer_data on the AP and copying selected result files back.",
        ],
    },
    {
        "title": "Monitoring and Reporting",
        "subtitle": "Operational feedback is built around HTCondor queue and history APIs.",
        "bullets": [
            "monitor displays a live Rich table with cluster, proc, status, time in state, input data, executable, and hold reason.",
            "report queries active jobs and history to summarize timing, duration, resources, starts, and transfer inputs; it can emit CSV.",
            "watcher polls tracked runs from SQLite, updates status, fetches outputs when jobs complete, and marks failed states for held or removed jobs.",
        ],
    },
    {
        "title": "Patchwork Job Example",
        "subtitle": "The current submit files show a containerized packet-analysis workload.",
        "bullets": [
            "patchwork_direct.sub runs in a container universe using docker://nicolaka/netshoot:v0.15.",
            "The executable is execution/job-scripts/ospool_main.sh with analysis.tar.gz and site archives such as data/LOSA.tar.gz transferred as inputs.",
            "Resource requests are explicit: 6 CPUs, 6 GB memory, and 40 GB disk in patchwork_direct.sub.",
            "Outputs are packaged as patchwork_results.tar.gz and remapped to the AP project outputs directory with the cluster ID in the filename.",
        ],
    },
    {
        "title": "Current Strengths and Next Steps",
        "subtitle": "Useful for a working learning project, with clear places to harden.",
        "bullets": [
            "Strengths: cohesive CLI, typed config, remote/AP support, OSDF integration, live monitoring, automatic fetch, run history, and CSV reporting.",
            "Short-term hardening: add tests around path resolution, submit-mode behavior, report formatting, and fetch search order.",
            "Operational polish: validate config values before submission, redact or template user-specific paths for sharing, and document expected token/SSH setup.",
            "Packaging polish: add example config generation and sample workflows so new users can bootstrap without editing production paths directly.",
        ],
    },
]


def content_types() -> str:
    overrides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, len(SLIDES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  {overrides}
</Types>"""


def presentation_xml() -> str:
    slide_ids = "\n".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, len(SLIDES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="{NS['a']}" xmlns:r="{NS['r']}" xmlns:p="{NS['p']}" saveSubsetFonts="1">
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle>
    <a:defPPr><a:defRPr lang="en-US"/></a:defPPr>
  </p:defaultTextStyle>
</p:presentation>"""


def presentation_rels() -> str:
    rels = "\n".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, len(SLIDES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {rels}
</Relationships>"""


def write_deck() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with ZipFile(OUT, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types())
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""")
        zf.writestr("docProps/core.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>OSPool Manager Overview</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>""")
        zf.writestr("docProps/app.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat><Slides>{len(SLIDES)}</Slides>
</Properties>""")
        zf.writestr("ppt/presentation.xml", presentation_xml())
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels())
        for idx, slide in enumerate(SLIDES, start=1):
            zf.writestr(f"ppt/slides/slide{idx}.xml", slide_xml(idx=idx, **slide))


if __name__ == "__main__":
    write_deck()
    print(f"Wrote {OUT}")
