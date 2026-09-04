from __future__ import annotations

import re
from typing import Optional

from app.schemas.metrics import MetricValue, ModelValidationProfile


class ModelMetricsExtractor:
    """Extracts model validation metrics from raw document text and Markdown tables."""

    def __init__(self) -> None:
        """Initialize metric extraction regular expression patterns."""
        # Helper regex to capture comma-formatted numbers and optional units (ANA-01, ANA-02)
        # Rule 10: Preserve comma-separated financial numbers (e.g. 1,500,000 or 1,250,000.50)
        # Allows optional markdown bold/italic formatting surrounding the numerical value
        self.val_pattern = r"[\*_\`]*(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)[\*_\`]*\s*(?P<unit>%|percent|bps|bp)?"

        # Delimiter pattern supporting markdown formatting, prose words ('of', 'is', 'was', 'equals', 'at'),
        # and table delimiters ('|', ':', '=', '-') without dropping matches (ANA-03)
        sep = r"[\s\*_\`]*(?:of|is|was|equals?|at|:|=|\||-)+[\s\*_\`]*"

        # Specific compiled patterns for different metrics with robust parenthesized acronym and formatting support
        self.patterns: dict[str, re.Pattern[str]] = {
            "gini": re.compile(rf"(?:Gini(?:\s*(?:coefficient|index))?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "auc": re.compile(rf"(?:(?:AUC|AUROC)(?:\s*\([^\)]+\))?|Area\s+Under\s+(?:the\s+)?(?:ROC|Curve)(?:\s*\((?:AUC|AUROC)\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "ks": re.compile(rf"(?:KS(?:\s*(?:statistic))?(?:\s*\([^\)]+\))?|Kolmogorov[- ]Smirnov(?:\s*\((?:KS)\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "psi": re.compile(rf"(?:Population\s+Stability\s+Index(?:\s*\(PSI\))?|PSI(?:\s*\(Population\s+Stability\s+Index\))?|PSI(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "hosmer_lemeshow_p_value": re.compile(rf"(?:(?:Hosmer[- ]Lemeshow|H[- ]L)(?:\s*(?:goodness[- ]of[- ]fit|p[- ]value|\(H[- ]L\)|\(p[- ]value\)))?){sep}{self.val_pattern}", re.IGNORECASE),
            "brier_score": re.compile(rf"(?:Brier(?:\s*Score)?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "pd_accuracy_ratio": re.compile(rf"(?:(?:PD\s*(?:accuracy\s*ratio|AR)|Accuracy\s*Ratio)(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "observed_vs_predicted_default_rate": re.compile(rf"(?:(?:observed\s*(?:vs\.?|versus)\s*predicted|obs\s*(?:vs\.?|versus)\s*pred)(?:\s*default\s*rate)?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "pd_value": re.compile(rf"(?:(?:Probability\s+of\s+Default(?:\s*\(PD\))?|PD(?:\s*\(Probability\s+of\s+Default\))?|PD)(?:\s*(?:value|range|spread|estimate|rate))?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "lgd_value": re.compile(rf"(?:(?:Loss\s+Given\s+Default(?:\s*\(LGD\))?|LGD(?:\s*\(Loss\s+Given\s+Default\))?|LGD)(?:\s*(?:value|range|estimate))?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "ead_value": re.compile(rf"(?:(?:Exposure\s+at\s+Default(?:\s*\(EAD\))?|EAD(?:\s*\(Exposure\s+at\s+Default\))?|EAD)(?:\s*(?:value|range|estimate))?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "ifrs9_ecl_provision_coverage": re.compile(rf"(?:IFRS\s*9(?:\s*ECL)?(?:\s*Provision)?(?:\s*Coverage)?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "capital_adequacy_ratio": re.compile(rf"(?:Capital\s+Adequacy\s+Ratio(?:\s*\(CAR\))?|CAR(?:\s*\(Capital\s+Adequacy\s+Ratio\))?|CAR(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "tier_1_ratio": re.compile(rf"(?:Tier\s*1(?:\s*(?:capital|ratio))?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
            "npa_ratio": re.compile(rf"(?:(?:Non[- ]Performing\s*(?:Assets|Loans)|NPA|NPL)(?:\s*ratio)?(?:\s*\([^\)]+\))?){sep}{self.val_pattern}", re.IGNORECASE),
        }

    def _extract_metric(self, text: str, metric_key: str, pattern: re.Pattern[str]) -> Optional[MetricValue]:
        """Extract a single metric from text matching the specified pattern.

        Args:
            text: Raw document text or Markdown.
            metric_key: Key identifying the metric.
            pattern: Compiled regular expression.

        Returns:
            MetricValue object if found, otherwise None.
        """
        match = pattern.search(text)
        if not match:
            return None

        raw_val_str = match.group("value")
        # Strip commas before float conversion (ANA-01)
        clean_val_str = raw_val_str.replace(",", "")
        unit_str = (match.group("unit") or "").lower()

        try:
            value = float(clean_val_str)
        except ValueError:
            return None

        # Normalize unit and scale (ANA-04)
        if unit_str in ("%", "percent"):
            unit = "%"
        elif unit_str in ("bps", "bp"):
            unit = "%"
            value = value / 100.0  # e.g., 45 bps -> 0.45%
        else:
            unit = "absolute"

        # Get context (roughly the sentence or line containing the match)
        start_idx = max(0, match.start() - 50)
        end_idx = min(len(text), match.end() + 50)
        context = text[start_idx:end_idx].strip()

        return MetricValue(
            value=value,
            unit=unit,
            raw_text=match.group(0).strip(),
            context=f"...{context}...",
        )

    def _extract_metrics_from_tables(self, text: str) -> dict[str, MetricValue]:
        """Extract validation metrics from column-header Markdown tables.

        Handles standard validation tables such as:
        | Sample | GINI | AUC | KS |
        | --- | --- | --- | --- |
        | Development | 42.5% | 71.2% | 38.5% |
        | Validation | 43.80% | 71.90% | 39.10% |

        Args:
            text: Raw document text or Markdown.

        Returns:
            Dictionary mapping metric key to MetricValue.
        """
        table_metrics: dict[str, MetricValue] = {}
        lines = text.splitlines()

        metric_headers: dict[str, re.Pattern[str]] = {
            "gini": re.compile(r"\b(?:gini|accuracy\s*ratio)\b", re.IGNORECASE),
            "auc": re.compile(r"\b(?:auc|auroc|c[- ]stat(?:istic)?)\b", re.IGNORECASE),
            "ks": re.compile(r"\b(?:ks(?:\s*stat(?:istic)?)?|kolmogorov[- ]smirnov)\b", re.IGNORECASE),
            "psi": re.compile(r"\b(?:psi|population\s*stability(?:\s*index)?)\b", re.IGNORECASE),
            "hosmer_lemeshow_p_value": re.compile(r"\b(?:hosmer[- ]lemeshow|h[- ]l)\b", re.IGNORECASE),
            "brier_score": re.compile(r"\b(?:brier(?:\s*score)?)\b", re.IGNORECASE),
        }

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("|") and line.endswith("|") and not all(c in "|-: " for c in line):
                # Check if the subsequent row is a markdown separator row
                if i + 1 < len(lines) and all(c in "|-: " for c in lines[i + 1].strip()):
                    header_cells = [c.strip(" *`_") for c in line.strip("|").split("|")]
                    col_to_metric: dict[int, str] = {}
                    for col_idx, cell in enumerate(header_cells):
                        for m_key, pat in metric_headers.items():
                            if pat.search(cell):
                                col_to_metric[col_idx] = m_key
                                break

                    if col_to_metric:
                        r = i + 2
                        rows: list[list[str]] = []
                        while r < len(lines) and lines[r].strip().startswith("|"):
                            row_cells = [c.strip() for c in lines[r].strip("|").split("|")]
                            rows.append(row_cells)
                            r += 1

                        # Prefer validation / holdout / test rows over development rows, or first valid row
                        for row in rows:
                            row_label = row[0].lower() if len(row) > 0 else ""
                            is_preferred = any(w in row_label for w in ("valid", "hold", "test", "oot"))
                            for col_idx, m_key in col_to_metric.items():
                                if col_idx < len(row):
                                    cell_text = row[col_idx].strip(" *`_")
                                    match = re.search(r"(\d+(?:\.\d+)?)\s*(%)?", cell_text)
                                    if match:
                                        num_val = float(match.group(1))
                                        unit = "%" if match.group(2) else "absolute"
                                        if m_key not in table_metrics or is_preferred:
                                            table_metrics[m_key] = MetricValue(
                                                value=num_val,
                                                unit=unit,
                                                raw_text=cell_text,
                                                context=f"Table row '{row_label}': {cell_text}",
                                            )
                        i = r
                        continue
            i += 1

        return table_metrics

    def extract(self, text: str) -> ModelValidationProfile:
        """Extract metrics from the text and return a ModelValidationProfile.

        Args:
            text: Raw document text or Markdown.

        Returns:
            ModelValidationProfile with all extracted metrics.
        """
        metrics: dict[str, MetricValue] = {}
        for key, pattern in self.patterns.items():
            metric = self._extract_metric(text, key, pattern)
            if metric:
                metrics[key] = metric

        # Augment with metrics from column-header tables (e.g. Table 37 GINI / AUC tables)
        table_metrics = self._extract_metrics_from_tables(text)
        for key, metric in table_metrics.items():
            if key not in metrics:
                metrics[key] = metric

        return ModelValidationProfile(**metrics)


def parse_population_deciles(markdown: str) -> list[dict]:
    """Parse a population-stability / PSI decile table from Docling markdown.

    Returns a list of {"decile": "<label>", "expected": <float>, "actual": <float>}
    (empty list when no recognizable table is found).
    """
    if not markdown:
        return []

    lines = markdown.splitlines()

    def _is_separator(row: str) -> bool:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if not cells:
            return True
        return all(not cell or set(cell) <= set("-: ") for cell in cells)

    header_idx = None
    for i, line in enumerate(lines):
        if "|" in line and "decile" in line.lower():
            header_idx = i
            break

    if header_idx is None:
        return []

    header_cells = [c.strip() for c in lines[header_idx].strip().strip("|").split("|")]

    decile_col = None
    expected_col = None
    actual_col = None
    for idx, cell in enumerate(header_cells):
        lower = cell.lower()
        if decile_col is None and "decile" in lower:
            decile_col = idx
        elif expected_col is None and "expect" in lower:
            expected_col = idx
        elif actual_col is None and "actual" in lower:
            actual_col = idx

    if expected_col is None or actual_col is None:
        return []

    deciles: list[dict] = []
    for line in lines[header_idx + 1:]:
        if "|" not in line:
            break
        if _is_separator(line):
            continue
        if len(deciles) >= 10:
            break

        cells = [c.strip() for c in line.strip().strip("|").split("|")]

        if decile_col is None or decile_col >= len(cells):
            label = ""
        else:
            label = cells[decile_col]

        if expected_col >= len(cells) or actual_col >= len(cells):
            continue

        exp_raw = cells[expected_col]
        act_raw = cells[actual_col]

        try:
            expected = float(exp_raw.replace(",", "").replace("%", "").strip())
            actual = float(act_raw.replace(",", "").replace("%", "").strip())
        except ValueError:
            continue

        deciles.append({"decile": label, "expected": expected, "actual": actual})

    return deciles
