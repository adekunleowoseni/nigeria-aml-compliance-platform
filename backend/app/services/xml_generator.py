from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from lxml import etree


class GoAMLGenerator:
    NAMESPACE = "http://www.fiu.gov.ng/goaml"

    def generate_str(
        self,
        reporting_entity: Dict,
        suspicious_activity: Dict,
        transactions: List[Dict],
        narrative: str,
        attachments: Optional[List[Dict]] = None,
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

