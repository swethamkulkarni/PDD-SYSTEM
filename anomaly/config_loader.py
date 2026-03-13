"""
Config Loader — loads and validates anomaly_config.yaml.
The config is loaded fresh on every pipeline run — no restart needed after edits.
"""
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "anomaly_config.yaml"


@dataclass
class AnomalyCheck:
    """A single anomaly check definition from the config."""
    id: str
    label: str
    category: str
    severity: str                          # HIGH | MEDIUM | LOW
    check_type: str                        # DETERMINISTIC | LLM
    target_sections: list[str]
    report_sections: list[str]
    generates_question: bool
    ic_memo_flag: bool
    enabled: bool
    probe_question: str = ""
    logic: str = ""

    def is_llm(self) -> bool:
        return self.check_type.upper() == "LLM"

    def is_deterministic(self) -> bool:
        return self.check_type.upper() == "DETERMINISTIC"

    def targets_section(self, section: str) -> bool:
        return "ANY" in self.target_sections or section in self.target_sections


@dataclass
class ReportSection:
    id: str
    label: str
    format: str
    source_slides: list[str] = field(default_factory=list)
    sub_sections: list[str] = field(default_factory=list)
    feeds_from: str = ""


@dataclass
class ReportFramework:
    name: str
    description: str
    tone: str
    persona: str = ""
    sections: list[ReportSection] = field(default_factory=list)


@dataclass
class DDConfig:
    """Complete loaded configuration."""
    framework_a: ReportFramework
    framework_b: ReportFramework
    anomalies: list[AnomalyCheck]

    def enabled_checks(self) -> list[AnomalyCheck]:
        return [a for a in self.anomalies if a.enabled]

    def deterministic_checks(self) -> list[AnomalyCheck]:
        return [a for a in self.enabled_checks() if a.is_deterministic()]

    def llm_checks(self) -> list[AnomalyCheck]:
        return [a for a in self.enabled_checks() if a.is_llm()]

    def checks_for_section(self, section: str) -> list[AnomalyCheck]:
        return [a for a in self.enabled_checks() if a.targets_section(section)]

    def high_severity_checks(self) -> list[AnomalyCheck]:
        return [a for a in self.enabled_checks() if a.severity.upper() == "HIGH"]


def load_config(config_path: Optional[str] = None) -> DDConfig:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    if not path.exists():
        raise FileNotFoundError(
            f"Anomaly config not found at: {path}\n"
            f"Expected location: config/anomaly_config.yaml"
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    # ── Parse report frameworks ───────────────────────────────────────────
    fw_raw = raw.get("report_frameworks", {})
    framework_a = _parse_framework(fw_raw.get("framework_a", {}))
    framework_b = _parse_framework(fw_raw.get("framework_b", {}))

    # ── Parse anomaly checks — reads our yaml format ──────────────────────
    anomalies = []
    for item in raw.get("checks", []):
        try:
            check = AnomalyCheck(
                id=str(item["id"]),
                label=str(item.get("question", item["id"])),
                category=str(item["category"]),
                severity=str(item.get("severity", "MEDIUM")).upper(),
                check_type=str(item.get("method", "llm")).upper(),
                target_sections=[s.upper() for s in item.get("section_scope", ["ANY"])],
                report_sections=item.get("report_sections", ["comments_obs"]),
                generates_question=bool(item.get("generates_question", True)),
                ic_memo_flag=bool(item.get("ic_memo_flag", False)),
                enabled=bool(item.get("enabled", True)),
                probe_question=str(item.get("question", "")).strip(),
                logic=str(item.get("investor_question", "")).strip(),
            )
            anomalies.append(check)
        except KeyError as e:
            print(f"[CONFIG WARNING] Skipping check with missing field {e}: {item.get('id', 'unknown')}")

    config = DDConfig(
        framework_a=framework_a,
        framework_b=framework_b,
        anomalies=anomalies,
    )

    enabled = config.enabled_checks()
    print(f"[CONFIG] Loaded {len(enabled)} enabled checks "
          f"({len(config.deterministic_checks())} deterministic, "
          f"{len(config.llm_checks())} LLM)")

    return config


def _parse_framework(raw: dict) -> ReportFramework:
    sections = []
    for s in raw.get("sections", []):
        sub = s.get("sub_sections", [])
        sub_labels = []
        for item in sub:
            if isinstance(item, str):
                sub_labels.append(item)
            elif isinstance(item, dict):
                sub_labels.append(item.get("label", str(item)))

        sections.append(ReportSection(
            id=str(s.get("id", "")),
            label=str(s.get("label", "")),
            format=str(s.get("format", "prose")),
            source_slides=s.get("source_slides", []),
            sub_sections=sub_labels,
            feeds_from=str(s.get("feeds_from", "")),
        ))

    return ReportFramework(
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        tone=raw.get("tone", ""),
        persona=raw.get("persona", ""),
        sections=sections,
    )