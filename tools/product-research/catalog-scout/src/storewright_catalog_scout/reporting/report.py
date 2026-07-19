from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, PackageLoader, select_autoescape

from storewright_catalog_scout.db.repositories import RunRepository
from storewright_catalog_scout.domain.models import ReportPaths


class ReportGenerator:
    def __init__(self, repository: RunRepository, artifacts_dir: Path) -> None:
        self.repository = repository
        self.artifacts_dir = artifacts_dir

    async def generate(self, run_id: UUID) -> ReportPaths:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        shops = await self.repository.report_rows(run_id)
        output = self.artifacts_dir / str(run_id)
        output.mkdir(parents=True, exist_ok=True)
        shop_rows: list[dict[str, object]] = []
        product_rows: list[dict[str, object]] = []
        html_shops: list[dict[str, object]] = []
        for shop_run in shops:
            shop_row = {
                "run_id": str(run_id),
                "shop_key": shop_run.shop.canonical_key,
                "shop_name": shop_run.shop.display_name or "",
                "input_url": shop_run.shop.original_url,
                "canonical_url": shop_run.shop.canonical_url,
                "discovered_count": shop_run.discovered_count,
                "processed_count": shop_run.processed_count,
                "search_success_count": shop_run.search_success_count,
                "exact_count": shop_run.exact_count,
                "qualified_count": shop_run.qualified_count,
                "skipped_count": shop_run.skipped_count,
                "error_count": shop_run.error_count,
                "rejection_rate": str(shop_run.rejection_rate),
                "catalog_complete": shop_run.catalog_complete,
                "early_stopped": shop_run.early_stopped,
                "decision": shop_run.decision or "",
                "reason_code": shop_run.decision_reason_code or "",
                "summary": shop_run.decision_summary or "",
                "started_at": _iso(shop_run.started_at),
                "finished_at": _iso(shop_run.finished_at),
            }
            shop_rows.append(shop_row)
            html_products: list[dict[str, object]] = []
            for product_run in sorted(
                shop_run.product_runs, key=lambda item: item.processing_index
            ):
                evidence = await self.repository.evidence_for_product(product_run.id)
                vision_query = (
                    await self.repository.vision_for_sha256(product_run.screening_image.sha256)
                    if product_run.screening_image
                    else None
                )
                full_count = sum(item.kind == "full_match_page" for item in evidence)
                partial_count = sum(item.kind == "partial_match_page" for item in evidence)
                image_path = (
                    product_run.screening_image.normalized_path
                    if product_run.screening_image
                    else ""
                )
                relative_image = _relative_link(output, image_path)
                row = {
                    "run_id": str(run_id),
                    "shop_key": shop_run.shop.canonical_key,
                    "shop_decision": shop_run.decision or "",
                    "processing_index": product_run.processing_index,
                    "item_id": product_run.product.external_item_id,
                    "item_url": product_run.product.canonical_url,
                    "title": (
                        product_run.snapshot.title
                        if product_run.snapshot
                        else product_run.product.title or ""
                    ),
                    "category": product_run.category_key or "",
                    "detail_archived": product_run.detail_archived,
                    "main_image_url": (
                        product_run.screening_image.source_url
                        if product_run.screening_image
                        else ""
                    ),
                    "local_image_path": relative_image,
                    "sha256": (
                        product_run.screening_image.sha256
                        if product_run.screening_image
                        else ""
                    ),
                    "phash": (
                        product_run.screening_image.phash
                        if product_run.screening_image
                        else ""
                    ),
                    "verdict": product_run.verdict.verdict if product_run.verdict else "",
                    "reason_code": (
                        product_run.verdict.reason_code if product_run.verdict else ""
                    ),
                    "confidence": (
                        str(product_run.verdict.confidence) if product_run.verdict else ""
                    ),
                    "full_match_page_count": full_count,
                    "partial_match_page_count": partial_count,
                    "top_evidence_url": evidence[0].url if evidence else "",
                    "error": product_run.last_error or "",
                    "status": product_run.status,
                    "raw_response_path": _relative_link(
                        output, (vision_query.raw_response_path or "") if vision_query else ""
                    ),
                    "evidence": [
                        {
                            "url": item.url,
                            "kind": item.kind,
                            "relation": item.relation,
                            "reason": item.reason,
                        }
                        for item in evidence
                    ],
                }
                product_rows.append(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"evidence", "raw_response_path"}
                    }
                )
                html_products.append(row)
            html_shops.append({"shop": shop_row, "products": html_products})
        shops_csv = output / "shops.csv"
        products_csv = output / "products.csv"
        _write_csv(shops_csv, shop_rows)
        _write_csv(products_csv, product_rows)
        summary = {
            "run_id": str(run_id),
            "run_status": run.status,
            "run_last_error": run.last_error or "",
            "generated_at": datetime.now(UTC).isoformat(),
            "candidate_shops": _keys_for(shop_rows, "candidate"),
            "rejected_shops": _keys_for(shop_rows, "rejected"),
            "review_shops": _keys_for(shop_rows, "review"),
            "insufficient_data_shops": _keys_for(shop_rows, "insufficient_data"),
        }
        summary_path = output / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        environment = Environment(
            loader=PackageLoader("storewright_catalog_scout.reporting", "templates"),
            autoescape=select_autoescape(["html"]),
        )
        html = environment.get_template("report.html.j2").render(
            run=run, shops=html_shops, generated_at=summary["generated_at"]
        )
        html_path = output / "report.html"
        html_path.write_text(html, encoding="utf-8")
        return ReportPaths(
            run_id=run_id,
            shops_csv=shops_csv,
            products_csv=products_csv,
            html=html_path,
            summary_json=summary_path,
        )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _keys_for(rows: list[dict[str, object]], decision: str) -> list[str]:
    return [str(row["shop_key"]) for row in rows if row["decision"] == decision]


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _relative_link(output: Path, value: str) -> str:
    if not value:
        return ""
    try:
        return Path(value).resolve().relative_to(output.resolve()).as_posix()
    except ValueError:
        return value
