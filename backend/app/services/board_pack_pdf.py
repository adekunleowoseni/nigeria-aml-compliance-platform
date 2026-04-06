"""Board AML pack PDF (ReportLab) — embeds ≥5 chart datasets as graphics + tables."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _bar_drawing(labels: List[str], values: List[float], width: float = 400, height: float = 160) -> Drawing:
    drawing = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 20
    chart.height = height - 40
    chart.width = width - 60
    chart.data = [values]
    chart.categoryAxis.categoryNames = [str(x)[:12] for x in labels]
    chart.bars[0].fillColor = colors.HexColor("#1a365d")
    drawing.add(chart)
    return drawing


def _trend_bar_drawing(series_rows: List[Dict[str, Any]], width: float = 400, height: float = 160) -> Drawing:
    """Last 14 days: total alerts per day (sum of severity buckets)."""
    rows = series_rows[-14:] if series_rows else []
    labels: List[str] = []
    vals: List[float] = []
    for row in rows:
        ds = str(row.get("date") or "")[-5:] or "?"
        labels.append(ds)
        t = 0.0
        for k in ("critical", "high", "medium", "low"):
            t += float(row.get(k) or 0)
        vals.append(t)
    if not vals:
        labels, vals = ["—"], [0.0]
    return _bar_drawing(labels, vals, width=width, height=height)


def build_board_pack_pdf_bytes(payload: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story: List[Any] = []

    title = payload.get("template_title") or "Board AML Management Information Pack"
    story.append(Paragraph(f"<b>{title}</b>", styles["Title"]))
    story.append(
        Paragraph(
            f"Generated (UTC): {payload.get('generated_at', datetime.now(timezone.utc).isoformat())}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    kpi = payload.get("kpi") or {}
    kt = [
        ["KPI", "Value"],
        ["Total alerts", str(kpi.get("total_alerts", "—"))],
        ["STR submitted", str(kpi.get("str_filed_submitted", "—"))],
        ["Open >7 days", str(kpi.get("open_alerts_ageing_over_7_days", "—"))],
        ["Material escalations (CCO track)", str(kpi.get("material_escalations_count", "—"))],
        ["Pending CCO STR approvals", str(kpi.get("pending_cco_str_approvals", "—"))],
        ["Tuning-related audit events", str(kpi.get("tuning_related_audit_events", "—"))],
        ["Exam-related audit events", str(kpi.get("regulatory_exam_related_audit_events", "—"))],
    ]
    t = Table(kt, colWidths=[8 * cm, 6 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5282")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))

    charts = payload.get("charts") or []
    story.append(Paragraph("<b>Charts</b> (management information)", styles["Heading2"]))

    dash = payload.get("dashboard") or {}
    trend = dash.get("trend_over_time") or []
    if trend:
        story.append(Paragraph("1. Alert volume trend (last 14 days of 30d series, total by severity)", styles["Heading3"]))
        story.append(_trend_bar_drawing(trend))
        story.append(Spacer(1, 0.3 * cm))

    ageing = dash.get("open_case_ageing") or {}
    if ageing:
        story.append(Paragraph("2. Open case ageing buckets", styles["Heading3"]))
        labels = ["<24h", "1-3d", "3-7d", ">7d"]
        vals = [
            float(ageing.get("lt_24h", 0)),
            float(ageing.get("d1_3", 0)),
            float(ageing.get("d3_7", 0)),
            float(ageing.get("gt_7d", 0)),
        ]
        story.append(_bar_drawing(labels, vals))
        story.append(Spacer(1, 0.3 * cm))

    for idx, ch in enumerate(charts):
        if ch.get("id") == "str_ctr_volume" and ch.get("values"):
            story.append(Paragraph("3. STR / CTR inventory", styles["Heading3"]))
            story.append(_bar_drawing(list(ch.get("labels") or []), [float(x) for x in ch.get("values") or []]))
            story.append(Spacer(1, 0.3 * cm))
        elif ch.get("id") == "severity_distribution" and ch.get("values"):
            story.append(Paragraph("4. Severity distribution", styles["Heading3"]))
            story.append(_bar_drawing(list(ch.get("labels") or []), [float(x) for x in ch.get("values") or []]))
            story.append(Spacer(1, 0.3 * cm))
        elif ch.get("id") == "outcome_pipeline" and ch.get("values"):
            story.append(Paragraph("5. Disposition pipeline", styles["Heading3"]))
            story.append(_bar_drawing(list(ch.get("labels") or []), [float(x) for x in ch.get("values") or []]))
            story.append(Spacer(1, 0.3 * cm))

    disc = payload.get("disclaimer") or ""
    if disc:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(f"<i>{disc}</i>", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()
