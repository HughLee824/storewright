from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from shop_scout.adapters.base import AdapterRegistry
from shop_scout.db.models import ProductAssetRow, ProductRunRow, ScreeningImageRow
from shop_scout.db.repositories import RunRepository
from shop_scout.domain.models import ImageArtifact, ProductDetail, ProductRef
from shop_scout.images.processor import safe_segment


def _image_identity(url: str) -> str:
    filename = Path(urlsplit(url).path).name
    match = re.match(r"^(.+?)(?:\.(?:jpe?g|png|webp))(?:_|$)", filename, re.I)
    return (match.group(1) if match else filename).lower()


def _artifact(row: ProductAssetRow | ScreeningImageRow, role: str = "gallery") -> ImageArtifact:
    return ImageArtifact(
        source_url=row.source_url,
        raw_path=Path(row.raw_path),
        normalized_path=Path(row.normalized_path),
        sha256=row.sha256,
        phash=row.phash,
        width=row.width,
        height=row.height,
        file_size=row.file_size,
        content_type=row.content_type,
        role=role,
    )


class OfflineArchiveRebuilder:
    def __init__(
        self,
        repository: RunRepository,
        adapters: AdapterRegistry,
        artifacts_dir: Path,
    ) -> None:
        self.repository = repository
        self.adapters = adapters
        self.artifacts_dir = artifacts_dir

    async def rebuild(self, run_id: UUID) -> dict[str, int]:
        shops = await self.repository.report_rows(run_id)
        rebuilt = 0
        skipped = 0
        for shop_run in shops:
            adapter = self.adapters.for_url(shop_run.shop.canonical_url)
            for product_run in shop_run.product_runs:
                if not product_run.detail_archived or product_run.snapshot is None:
                    continue
                raw_path = Path(product_run.snapshot.raw_html_path or "")
                if not await asyncio.to_thread(raw_path.is_file):
                    skipped += 1
                    continue
                product = product_run.product
                detail = adapter.extract_product_detail_html(
                    await asyncio.to_thread(raw_path.read_text, encoding="utf-8"),
                    ProductRef(
                        external_item_id=product.external_item_id,
                        canonical_url=product.canonical_url,
                        title=product.title,
                        listing_image_url=product.listing_image_url,
                        source_position=product_run.processing_index,
                        metadata=product.metadata_json,
                    ),
                    product.canonical_url,
                )
                if await self._rebuild_product(
                    run_id, shop_run.shop.canonical_key, product_run, detail, raw_path
                ):
                    rebuilt += 1
                else:
                    skipped += 1
        return {"rebuilt": rebuilt, "skipped": skipped}

    async def _rebuild_product(
        self,
        run_id: UUID,
        shop_key: str,
        product_run: ProductRunRow,
        detail: ProductDetail,
        old_raw_path: Path,
    ) -> bool:
        if product_run.screening_image is None:
            return False
        product = product_run.product
        output_dir = (
            self.artifacts_dir
            / str(run_id)
            / "shops"
            / safe_segment(shop_key)
            / "products"
            / safe_segment(product.external_item_id)
        )
        available = [_artifact(product_run.screening_image, "main")]
        available.extend(_artifact(row, row.role) for row in product_run.assets)
        by_url = {item.source_url: item for item in available}
        by_identity: dict[str, ImageArtifact] = {}
        for item in available:
            by_identity.setdefault(_image_identity(item.source_url), item)

        selected: list[ImageArtifact] = [available[0]]
        seen_hashes = {available[0].sha256}
        seen_phashes = {available[0].phash}
        for url in detail.image_urls:
            candidate = by_url.get(url) or by_identity.get(_image_identity(url))
            if candidate is None:
                continue
            if candidate.sha256 in seen_hashes or candidate.phash in seen_phashes:
                continue
            seen_hashes.add(candidate.sha256)
            seen_phashes.add(candidate.phash)
            selected.append(
                candidate.model_copy(update={"role": detail.image_roles.get(url, "gallery")})
            )

        images_stage = output_dir / "images.rebuild"
        originals_stage = output_dir / "evidence" / "original-images.rebuild"
        shutil.rmtree(images_stage, ignore_errors=True)
        shutil.rmtree(originals_stage, ignore_errors=True)
        images_stage.mkdir(parents=True)
        originals_stage.mkdir(parents=True)
        rebuilt_assets: list[ImageArtifact] = []
        for position, source in enumerate(selected, start=1):
            role = "main" if position == 1 else source.role
            stem = f"{position:03d}-{safe_segment(role)}"
            staged_normalized = images_stage / f"{stem}.jpg"
            staged_raw = originals_stage / f"{stem}.raw"
            shutil.copy2(source.normalized_path, staged_normalized)
            shutil.copy2(source.raw_path, staged_raw)
            rebuilt_assets.append(
                source.model_copy(
                    update={
                        "normalized_path": output_dir / "images" / f"{stem}.jpg",
                        "raw_path": output_dir / "evidence" / "original-images" / f"{stem}.raw",
                        "role": role,
                    }
                )
            )

        images_dir = output_dir / "images"
        originals_dir = output_dir / "evidence" / "original-images"
        shutil.rmtree(images_dir, ignore_errors=True)
        shutil.rmtree(originals_dir, ignore_errors=True)
        images_stage.rename(images_dir)
        originals_stage.rename(originals_dir)

        detail = detail.model_copy(
            update={
                "main_image_url": rebuilt_assets[0].source_url,
                "image_urls": [item.source_url for item in rebuilt_assets],
                "image_roles": {item.source_url: item.role for item in rebuilt_assets},
            }
        )
        detail_path = output_dir / "product.json"
        evidence_dir = output_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        raw_path = evidence_dir / "raw.html"
        if old_raw_path != raw_path:
            shutil.copy2(old_raw_path, raw_path)
            await asyncio.to_thread(old_raw_path.unlink, missing_ok=True)
        detail_path.write_text(
            json.dumps(
                detail.model_dump(mode="json", exclude={"raw_html"}),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (evidence_dir / "image-sources.json").write_text(
            json.dumps(
                [
                    {
                        "position": position,
                        "role": item.role,
                        "source_url": item.source_url,
                        "sha256": item.sha256,
                        "phash": item.phash,
                        "width": item.width,
                        "height": item.height,
                        "normalized_path": str(item.normalized_path),
                    }
                    for position, item in enumerate(rebuilt_assets, start=1)
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        await self.repository.replace_archive(
            product_run.id, detail, detail_path, raw_path, rebuilt_assets
        )
        return True
