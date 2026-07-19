# Catalog Scout result interpretation

Use generated `summary.json`, `shops.csv`, `products.csv`, and `report.html`. Do not edit them to change decisions.

## Run status

- `created`: recorded but not processing yet.
- `running`: currently processing; do not launch a duplicate run.
- `paused`: resumable after its manual/configuration boundary is resolved.
- `completed`: pipeline finished; individual shops or products may still require review.
- `failed`: stopped on an error; preserve artifacts and diagnose before retrying.
- `cancelled`: intentionally stopped; do not resume unless the installed version documents support.

## Shop decision

- `candidate`: the shop passed the configured screening policy. This is not proof that every product is unique or suitable.
- `rejected`: the shop reached the configured rejection rule, including final or early-stop thresholds.
- `review`: results require human judgment, often because error rate, partial/unmapped matches, or catalog completeness prevent a deterministic decision.
- `insufficient_data`: too few reliable results to decide.
- `failed`: shop processing ended on an error.

Explain `early_stopped=true` as a deliberate cost/page-visit control, not full-catalog coverage. Explain `catalog_complete=false` as incomplete discovery that requires caution.

## Product status

- `qualified`: passed image screening, detail processing completed, category quota allowed it, and the full supported archive was saved.
- `screened_qualified`: listing image passed, but detail processing/archive may still be pending or paused.
- `rejected`: deterministic external exact-image-match rule rejected the product; only minimal audit evidence is retained.
- `review`: evidence is ambiguous or search failed and needs human judgment.
- `failed`: processing error; not equivalent to rejection.
- `skipped_category_quota_reached`: passed far enough to identify a category, but that category already reached its configured saved-product limit.
- `skipped_after_shop_rejected`: not processed further after the shop rejection rule stopped remaining work.

Intermediate statuses such as `pending`, `searching_listing_image`, `extracting_detail`, or `archiving` mean the run is unfinished or was interrupted at that phase.

## Product verdict

- `exact_external_image_match`: a full image match mapped to an external page; deterministic rejection evidence.
- `no_indexed_match_found`: the configured provider returned no exact indexed match. It does not prove that no matching product exists online.
- `full_image_unmapped`: a full image was found but could not be safely mapped to an external page; review.
- `partial_external_image_match`: only a partial match was found; review rather than automatic rejection.
- `search_error`: provider/query failure; no product conclusion.
- `manual_review`: explicit human judgment required.

Image evidence does not establish identical SKU, materials, quality, supplier, legality, or intellectual-property status.

## Counts and rates

- `discovered_count`: products found in the controlled catalog pool.
- `processed_count`: products whose current pipeline work was attempted/completed according to the report.
- `search_success_count`: successful image searches used as the rejection-rate denominator.
- `exact_count`: deterministic exact external matches.
- `qualified_count`: qualified products retained under the policy.
- `skipped_count`: products skipped because of category quota or shop stopping.
- `error_count`: product/search processing errors.
- `rejection_rate`: exact matches divided by successful image searches, not by all discovered products.

## User-facing summary

Report in this order:

1. Run status and whether further action is required.
2. Shops: candidate/rejected/review/insufficient counts and the most important reason.
3. Products: qualified/rejected/review/skipped/error counts.
4. Whether discovery was complete or early-stopped.
5. Absolute report path and, when useful, archive path.
6. Caveats about `no_indexed_match_found` and image-only evidence.
7. One recommended next action, such as inspect review items, resolve login, update a key locally, or resume.

Do not overwhelm a non-technical user with every evidence URL. Offer detailed product-level evidence only when asked.
