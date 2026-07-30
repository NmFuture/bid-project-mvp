# -*- coding: utf-8 -*-
"""专项抽取器真实样本对拍脚本（开发自检用，可保留）。

用法：cd code/sewpg-bid-backend && .venv/bin/python scripts/dev_check_special_extractors.py
对两个真实项目（华能翁牛特旗北区、国电投邢台50MW）跑四类专项解析器，
按 spec label 打印抽到的值与 location，并统计命中率。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.technical_fact_special_extractors import (
    facts_from_certificate_materials,
    facts_from_foundation_moment_xlsx,
    facts_from_hours_commitment_docx,
    facts_from_production_base_docx,
    facts_from_tower_quantity_docx,
    facts_from_wind_resource_docx,
    _spec_labels,
)

ROOT = Path("/Users/anbc/Desktop/技术标模板-20260709")
HN = ROOT / "项目定制/华能赤峰市200万千瓦自建调峰能力风光储多能互补一体化+荒漠治理基地项目（翁牛特旗120万千瓦风电项目北区）"
XT = ROOT / "项目定制/国电投2026年第一批集采标段15-河北省邢台市卓希经开区50MW风电项目"


def material(name: str, folder: str) -> dict:
    return {"id": f"dev-{name}", "name": name, "folderPath": folder, "materialTier": "project", "path": ""}


def report(title: str, facts, spec_labels: set[str]) -> tuple[int, int]:
    from app.services.technical_gap_fact_table import fact_label_key

    by_key = {fact_label_key(f["label"]): f for f in facts}
    hit = 0
    print(f"\n### {title}（命中 spec label {len([l for l in spec_labels if fact_label_key(l) in by_key])}/{len(spec_labels)}）")
    for label in sorted(spec_labels):
        fact = by_key.get(fact_label_key(label))
        if fact:
            hit += 1
            value = str(fact["value"])
            print(f"  [中] {label} = {value[:80]}  @ {fact['sourceRef'].get('location')}（fact label: {fact['label']}）")
        else:
            print(f"  [缺] {label}")
    spec_keys = {fact_label_key(l) for l in spec_labels}
    extra = [f["label"] for f in facts if fact_label_key(f["label"]) not in spec_keys]
    if extra:
        print(f"  （spec 外额外产出: {extra}）")
    return hit, len(spec_labels)


def main() -> None:
    project: dict = {}
    total_hit = total = 0

    cases = [
        (
            "华能-风资源评估报告",
            facts_from_wind_resource_docx,
            HN / "风资源评估报告/风资源评估报告.docx",
            _spec_labels("风资源报告"),
        ),
        (
            "国电投-风资源报告及担保",
            facts_from_wind_resource_docx,
            XT / "风资源评估报告/标段15-河北省邢台市卓希经开区50MW风电项目风资源报告及担保.docx",
            _spec_labels("风资源报告"),
        ),
        (
            "华能-塔架与基础工程量",
            facts_from_tower_quantity_docx,
            HN / "塔架与基础工程量/塔架与基础工程量.docx",
            _spec_labels("塔架与基础工程量"),
        ),
        (
            "国电投-混塔工程量",
            facts_from_tower_quantity_docx,
            XT / "塔架与基础工程量/国电投26年第一批河北邢台6.25-160m混塔工程量-20260428.docx",
            _spec_labels("塔架与基础工程量"),
        ),
        (
            "华能-基础弯矩表",
            facts_from_foundation_moment_xlsx,
            HN / "基础弯矩表/基础弯矩表.xlsx",
            _spec_labels("弯矩"),
        ),
        (
            "国电投-基础弯矩表",
            facts_from_foundation_moment_xlsx,
            XT / "基础弯矩表/国电投标段15-河北省邢台市卓希经开区50MW风电项目EW6.25-220-160_基础弯矩表_260428.xlsx",
            _spec_labels("弯矩"),
        ),
        (
            "华能-发电小时数承诺函（保证值）",
            facts_from_hours_commitment_docx,
            HN / "发电小时数承诺函/发电小时数承诺函（承诺保证值）.docx",
            # spec label canonical 坍缩为"保证有效小时数"，专项产出别名（SPEC_LABEL_ALIASES 归位）
            {"电量承诺函版本"},
        ),
        (
            "华能-生产制造基地专题（主机）",
            facts_from_production_base_docx,
            HN / "项目生产制造基地专题/生产制造基地专题_锡盟基地.docx",
            _spec_labels("生产制造基地"),
        ),
        (
            "华能-叶片供货制造基地",
            facts_from_production_base_docx,
            HN / "项目生产制造基地专题/本项目叶片供货制造基地.docx",
            _spec_labels("生产制造基地"),
        ),
    ]
    for title, extractor, path, labels in cases:
        facts = extractor(path, material(path.name, path.parent.name), project) or []
        hit, n = report(title, facts, labels)
        total_hit += hit
        total += n

    # 证书：EW6.7-220（型式+设计）、EW10.0-220上置（仅设计认证D）
    for model_dir in ["EW6.7-220", "EW10.0-220上置"]:
        cert_dir = ROOT / f"标准文件-all/{model_dir}/认证证书"
        certs = []
        for pdf in sorted(cert_dir.glob("*.pdf")):
            if "型式认证" in pdf.name or "设计认证" in pdf.name:
                certs.append((material(pdf.name, f"标准文件/{model_dir}/认证证书"), pdf))
        facts = facts_from_certificate_materials(certs, project)
        hit, n = report(f"证书-{model_dir}（{len(certs)} 本认证）", facts, _spec_labels("", source_kind="cert"))
        total_hit += hit
        total += n

    print(f"\n===== 总计命中 {total_hit}/{total}")


if __name__ == "__main__":
    main()
