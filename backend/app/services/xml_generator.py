from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from lxml import etree


class GoAMLGenerator:
    NAMESPACE = "http://www.fiu.gov.ng/goaml"

    def _sub_text(self, parent: etree._Element, tag: str, value: Any) -> None:
        if value is None:
            return
        el = etree.SubElement(parent, "{%s}%s" % (self.NAMESPACE, tag))
        el.text = str(value)

    def _append_case_details(self, root: Any, case_details: Dict[str, Any]) -> None:
        """Structured fields aligned with the platform STR narrative (customer, txn, typologies, analyst note)."""
        cd = etree.SubElement(root, "{%s}case_details" % self.NAMESPACE)

        alert_block = case_details.get("alert") or {}
        if alert_block:
            a_el = etree.SubElement(cd, "{%s}alert" % self.NAMESPACE)
            for key in (
                "id",
                "status",
                "severity",
                "last_resolution",
                "summary",
                "rule_ids",
                "created_at",
                "updated_at",
            ):
                if key == "rule_ids":
                    rules = alert_block.get("rule_ids") or []
                    self._sub_text(a_el, "rule_ids", ", ".join(str(r) for r in rules) if rules else None)
                elif key in alert_block:
                    self._sub_text(a_el, key, alert_block.get(key))

        txn_block = case_details.get("transaction") or {}
        if txn_block:
            t_el = etree.SubElement(cd, "{%s}primary_transaction" % self.NAMESPACE)
            for key in (
                "id",
                "customer_id",
                "amount",
                "currency",
                "transaction_type",
                "narrative",
                "channel",
                "counterparty_id",
                "counterparty_name",
                "risk_score",
                "created_at",
                "updated_at",
            ):
                if key in txn_block:
                    self._sub_text(t_el, key, txn_block.get(key))
            meta = txn_block.get("metadata")
            if meta is not None:
                self._sub_text(t_el, "metadata_json", meta if isinstance(meta, str) else str(meta))

        cash = case_details.get("cashflow") or {}
        if cash:
            c_el = etree.SubElement(cd, "{%s}customer_cashflow" % self.NAMESPACE)
            for key in ("period_text", "inflows_total", "outflows_total", "currency"):
                if key in cash:
                    self._sub_text(c_el, key, cash.get(key))

        hist = case_details.get("investigation_history") or []
        if hist:
            h_root = etree.SubElement(cd, "{%s}investigation_history" % self.NAMESPACE)
            for i, entry in enumerate(hist):
                if not isinstance(entry, dict):
                    continue
                e_el = etree.SubElement(h_root, "{%s}entry" % self.NAMESPACE)
                e_el.set("index", str(i))
                for k, v in entry.items():
                    self._sub_text(e_el, k, v)

        notes = case_details.get("analyst_str_notes")
        if notes:
            n_el = etree.SubElement(cd, "{%s}analyst_str_notes" % self.NAMESPACE)
            n_el.text = str(notes)

    def generate_str(
        self,
        reporting_entity: Dict,
        suspicious_activity: Dict,
        transactions: List[Dict],
        narrative: str,
        attachments: Optional[List[Dict]] = None,
        case_details: Optional[Dict[str, Any]] = None,
    ) -> str:
        root = etree.Element("{%s}report" % self.NAMESPACE, nsmap={"goaml": self.NAMESPACE})

        header = etree.SubElement(root, "{%s}report_header" % self.NAMESPACE)
        etree.SubElement(header, "{%s}report_id" % self.NAMESPACE).text = self._generate_report_id()
        etree.SubElement(header, "{%s}report_type" % self.NAMESPACE).text = "STR"
        etree.SubElement(header, "{%s}submission_date" % self.NAMESPACE).text = datetime.utcnow().isoformat()

        entity_elem = etree.SubElement(root, "{%s}reporting_entity" % self.NAMESPACE)
        for k, v in reporting_entity.items():
            etree.SubElement(entity_elem, "{%s}%s" % (self.NAMESPACE, k)).text = str(v)

        activity_elem = etree.SubElement(root, "{%s}suspicious_activity" % self.NAMESPACE)
        for k, v in suspicious_activity.items():
            etree.SubElement(activity_elem, "{%s}%s" % (self.NAMESPACE, k)).text = str(v)

        txns_elem = etree.SubElement(root, "{%s}transactions" % self.NAMESPACE)
        for txn in transactions:
            txn_elem = etree.SubElement(txns_elem, "{%s}transaction" % self.NAMESPACE)
            for k, v in txn.items():
                etree.SubElement(txn_elem, "{%s}%s" % (self.NAMESPACE, k)).text = str(v)

        narrative_elem = etree.SubElement(root, "{%s}reason_for_suspicion" % self.NAMESPACE)
        narrative_elem.text = narrative

        if case_details:
            self._append_case_details(root, case_details)

        if attachments:
            atts_elem = etree.SubElement(root, "{%s}attachments" % self.NAMESPACE)
            for att in attachments:
                att_elem = etree.SubElement(atts_elem, "{%s}attachment" % self.NAMESPACE)
                for k, v in att.items():
                    etree.SubElement(att_elem, "{%s}%s" % (self.NAMESPACE, k)).text = str(v)

        return etree.tostring(root, pretty_print=True, encoding="unicode")

    def _generate_report_id(self) -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"STR-{timestamp}-{uuid.uuid4().hex[:8].upper()}"

    def generate_narrative(self, alert_data: Dict, shap_explanation: Dict, related_patterns: List[str]) -> str:
        patterns = ", ".join(related_patterns) if related_patterns else "no dominant typology detected"
        return (
            f"Alert {alert_data.get('id')} flagged as suspicious. "
            f"Detected patterns: {patterns}. "
            f"Top drivers: {', '.join([f.get('feature','?') for f in (shap_explanation.get('top_features') or [])][:5])}."
        )

