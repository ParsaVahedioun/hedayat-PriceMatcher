"""Matching engine - inventory driven.

The inventory is what the user owns, so the inventory is what drives the
output: every Excel row produces exactly one result row, and a price-list row
with no counterpart in the inventory is simply never shown.

For one inventory row the engine asks three independent questions and blends
the answers:

    code   does the model code in the item name point at this price row?
    specs  do the numbers (watt, amp, volt, density, size) agree?
    text   do the rare words of the item name appear in the price row?

`text` is scored with IDF weighting rather than plain string similarity.
In a price list every second row says "پنل", "وات" and "مهتابی"; what
identifies a product is the one rare word - "اپلاست", "اسلیم لاین",
"ترکیبی". Plain fuzzy similarity gives those the same vote as the filler,
which is precisely how price lists get mis-matched.

A disagreeing hard spec is a veto, not a penalty: a 9 W panel and an 18 W
panel of the same family are different products at different prices, and
returning the wrong one is worse than returning nothing.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable, Sequence

from core import similarity
from core.attributes import (
    DEFAULT_BRAND_PREFIXES,
    DEFAULT_DISCRIMINATORS,
    detect_brand,
    extract_codes,
    extract_specs,
    expand_synonyms,
)
from models.product import (
    MATCH_CODE_SPEC,
    MATCH_EXACT_CODE,
    MATCH_NONE,
    MATCH_TEXT,
    STATUS_EXACT,
    STATUS_HIGH,
    STATUS_NOT_FOUND,
    STATUS_REVIEW,
    MatchResult,
    PriceItem,
    StockItem,
)
from utils.config import load_config
from utils.logger import get_logger
from utils.text_utils import code_family, dense, normalize_code, normalize_text

log = get_logger("matcher")

# specs whose disagreement means "different product", never "close enough"
HARD_SPECS = ("watt", "amp", "volt", "density")
# specs that only support or weaken a match
SOFT_SPECS = ("degree", "ip", "cm")


class PriceIndex:
    """Lookup structures built once over the price list."""

    __slots__ = ("items", "by_code", "by_family", "packed", "_freq", "_count")

    def __init__(self, items: Sequence[PriceItem]):
        self.items: list[PriceItem] = list(items)
        self.by_code: dict[str, list[int]] = defaultdict(list)
        self.by_family: dict[str, list[int]] = defaultdict(list)
        self.packed: list[str] = []

        for index, item in enumerate(self.items):
            if item.code_key:
                self.by_code[item.code_key].append(index)
            if item.family:
                self.by_family[item.family].append(index)
            text = dense(" ".join([item.code, item.section_fa, item.section_en, item.text]))
            self.packed.append(text)

        # Document frequency is measured on the price list itself, because
        # that is the corpus the scoring happens in. It is filled lazily: the
        # inventory only ever asks about the few thousand words it actually
        # uses, not about every word in the language.
        self._count = max(1, len(self.items))
        self._freq: dict[str, int] = {}

    def frequency(self, token: str) -> int:
        """How many price rows contain `token` (cached)."""
        hit = self._freq.get(token)
        if hit is None:
            hit = sum(1 for text in self.packed if token in text)
            self._freq[token] = hit
        return hit

    def weight(self, token: str) -> float:
        """IDF weight; 0 for words the price list never uses at all."""
        count = self.frequency(token)
        if count == 0:
            return 0.0
        return math.log(1.0 + self._count / count)

    def candidates(self, item: StockItem, limit: int) -> list[int]:
        """Price rows worth scoring for this inventory row."""
        found: dict[int, float] = defaultdict(float)

        for code in item.codes:
            for index in self.by_code.get(code, ()):
                found[index] += 3.0
            family = code_family(code)
            if len(family) >= 3:
                for index in self.by_family.get(family, ()):
                    found[index] += 2.0
            for index, other in enumerate(self.items):
                if other.code_key and (
                    other.code_key.startswith(code) or code.startswith(other.code_key)
                ):
                    found[index] += 2.0

        # rare-word lookup: a price list is small (hundreds of rows), so a
        # straight scan beats maintaining an inverted index over text that
        # the PDF split at arbitrary points anyway
        for token in set(item.tokens):
            if len(token) < 3:
                continue
            weight = self.weight(token)
            if weight <= 0:
                continue
            for index, text in enumerate(self.packed):
                if token in text:
                    found[index] += weight
        if not found:
            return []
        if len(found) <= limit:
            return list(found)
        return sorted(found, key=found.get, reverse=True)[:limit]


def _spec_verdict(stock: dict, price: dict) -> tuple[float, int, int]:
    """(0..1 agreement, comparable hard specs, conflicting hard specs)."""
    agreed = comparable = conflicts = 0
    soft_agreed = soft_comparable = 0

    for name in HARD_SPECS:
        left, right = stock.get(name), price.get(name)
        if left is None or right is None:
            continue
        comparable += 1
        if _spec_equal(name, left, right, stock, price):
            agreed += 1
        else:
            conflicts += 1

    for name in SOFT_SPECS:
        left, right = stock.get(name), price.get(name)
        if left is None or right is None:
            continue
        soft_comparable += 1
        if abs(float(left) - float(right)) < 1e-6:
            soft_agreed += 1

    for name in HARD_SPECS:
        value = stock.get(name)
        if value is None or price.get(name) is not None:
            continue
        hint = price.get(name + "_hint")
        if hint is not None:
            soft_comparable += 1
            if abs(float(value) - float(hint)) < 1e-6:
                soft_agreed += 1
        elif int(value) in (price.get("numbers") or ()):
            # the price row prints the value as a bare number because its
            # column heading did not survive extraction: evidence for this
            # row, never against the others
            soft_comparable += 1
            soft_agreed += 1

    left_mm, right_mm = stock.get("mm"), price.get("mm")
    if left_mm and right_mm:
        soft_comparable += 1
        if set(left_mm) & set(right_mm):
            soft_agreed += 1

    total = comparable + soft_comparable
    if total == 0:
        return -1.0, 0, 0

    ratio = (agreed + soft_agreed) / total
    return ratio, comparable, conflicts


def _spec_equal(name: str, left: float, right: float, stock: dict, price: dict) -> bool:
    """`left` is the inventory value, `right` the price-list value.

    A price row may cover a whole range ("کلید مینیاتوری ۶ تا ۳۲ آمپر"), in
    which case any inventory value inside it is a match. Each range is only
    ever tested against the *other* side's value - testing a range against
    the value it was derived from would always succeed.
    """
    if abs(float(left) - float(right)) < 1e-6:
        return True
    span = price.get(name + "_range")
    if span and span[0] - 1e-6 <= float(left) <= span[1] + 1e-6:
        return True
    span = stock.get(name + "_range")
    if span and span[0] - 1e-6 <= float(right) <= span[1] + 1e-6:
        return True
    return False


class Matcher:
    def __init__(self, config: dict | None = None):
        cfg = config or load_config()
        self.cfg = cfg
        self.exact_threshold = float(cfg.get("exact_threshold", 99))
        self.high_threshold = float(cfg.get("fuzzy_threshold", 85))
        self.review_threshold = float(cfg.get("review_threshold", 70))
        self.ambiguity_margin = float(cfg.get("ambiguity_margin", 4))
        self.max_candidates = int(cfg.get("max_candidates", 60))
        self.conflict_factor = float(cfg.get("spec_conflict_factor", 0.35))
        self.brand_bonus = float(cfg.get("brand_prefix_bonus", 4))
        weights = cfg.get("weights", {})
        self.w_code = float(weights.get("code", 0.45))
        self.w_spec = float(weights.get("spec", 0.25))
        self.w_text = float(weights.get("text", 0.30))
        self.brand_prefixes = cfg.get("brand_prefixes") or DEFAULT_BRAND_PREFIXES
        self.neutral_spec = float(cfg.get("neutral_spec_score", 55))
        self.coverage_exponent = float(cfg.get("text_coverage_exponent", 0.6))
        self.discriminator_penalty = float(cfg.get("discriminator_penalty", 12))
        self.discriminators = [
            dense(term) for term in
            (cfg.get("discriminative_terms") or DEFAULT_DISCRIMINATORS)
        ]
        # brand typed in by the user for this specific PDF run (e.g. "شوان");
        # empty means "no override", i.e. fall back to restrict_to_price_list_brands
        self.target_brand = (cfg.get("target_brand") or "").strip()

    def discriminator_delta(self, item: StockItem, packed: str) -> float:
        """Penalty for variant words present on one side only.

        "سنسوردار" in the price row but not in the item name means the price
        belongs to the sensor variant, which is a different product.
        """
        packed_item = dense(item.expanded)
        delta = 0.0
        for term in self.discriminators:
            if (term in packed_item) != (term in packed):
                delta -= self.discriminator_penalty
        return delta

    # ------------------------------------------------------------ scoring
    def code_score(self, item: StockItem, price: PriceItem) -> float:
        """0..100 - how strongly the item's model code points at this row."""
        if not item.codes or not price.code_key:
            return -1.0
        best = 0.0
        for code in item.codes:
            if code == price.code_key:
                return 100.0
            if price.code_key.startswith(code) or code.startswith(price.code_key):
                best = max(best, 88.0)
            elif len(code_family(code)) >= 3 and code_family(code) == price.family:
                # a family of one or two letters ("SC", "VS") is just the
                # manufacturer prefix and says nothing about the product
                best = max(best, 78.0)
            else:
                best = max(best, similarity.ratio(code, price.code_key) * 0.5)
        return best

    def text_score(self, item: StockItem, price: PriceItem,
                   index: PriceIndex, packed: str) -> float:
        """0..100 - IDF-weighted share of the item's words found in the row."""
        total = found = 0.0
        for token in set(item.tokens):
            if len(token) < 3:
                continue
            weight = index.weight(token)
            if weight <= 0:          # word the price list never uses: no vote
                continue
            total += weight
            if token in packed:
                found += weight
        if total <= 0:
            return similarity.token_set_ratio(item.name_key, price.context)
        # The raw share is pessimistic by construction: an inventory name
        # carries colour, shape and packaging words that a price list simply
        # never prints, and those can never be found however right the row
        # is. The exponent rescales the share so that "most of the rare
        # words are there" reads as a high number, without changing the
        # order of the candidates.
        coverage = 100.0 * (found / total) ** self.coverage_exponent
        # a long common substring is extra evidence on top of the word votes
        overlap = similarity.partial_ratio(dense(item.expanded), packed)
        return min(100.0, 0.75 * coverage + 0.25 * overlap)

    def score(self, item: StockItem, price: PriceItem,
              index: PriceIndex, position: int) -> tuple[float, str, str]:
        packed = index.packed[position]
        code = self.code_score(item, price)
        text = self.text_score(item, price, index, packed)
        ratio, comparable, conflicts = _spec_verdict(item.specs, price.specs)

        exact_code = code >= 100.0
        parts: list[tuple[float, float]] = []
        if code >= 0:
            parts.append((self.w_code, code))
        # "no comparable spec" is scored as a neutral value rather than
        # dropped: otherwise a row that states nothing would outrank a row
        # whose numbers actually agree
        if ratio >= 0:
            parts.append((self.w_spec, ratio * 100.0))
        elif any(item.specs.get(name) is not None for name in HARD_SPECS):
            # the item states a rating and this row stays silent about it:
            # that is weaker evidence than a row whose numbers agree, but it
            # is not a contradiction either
            parts.append((self.w_spec, self.neutral_spec))
        parts.append((self.w_text, text))

        total_weight = sum(w for w, _ in parts)
        value = sum(w * s for w, s in parts) / total_weight if total_weight else 0.0

        # the brand named in the inventory should agree with the code prefix
        if item.brand:
            prefixes = self.brand_prefixes.get(item.brand, ())
            if prefixes and price.code_key.startswith(tuple(prefixes)):
                value += self.brand_bonus
            elif prefixes:
                value -= self.brand_bonus

        value += self.discriminator_delta(item, packed)

        note = ""
        if conflicts:
            value *= self.conflict_factor
            note = "مغایرت در مشخصات فنی (توان/آمپر/ولتاژ)"
        elif exact_code:
            value = 100.0

        kind = MATCH_EXACT_CODE if exact_code and not conflicts else (
            MATCH_CODE_SPEC if code > 0 else MATCH_TEXT
        )
        return max(0.0, min(100.0, value)), kind, note

    def _status_for(self, value: float) -> str:
        if value >= self.exact_threshold:
            return STATUS_EXACT
        if value >= self.high_threshold:
            return STATUS_HIGH
        if value >= self.review_threshold:
            return STATUS_REVIEW
        return STATUS_NOT_FOUND

    # -------------------------------------------------------------- match
    def match_one(self, item: StockItem, index: PriceIndex) -> MatchResult:
        # A brand typed in for this PDF run overrides the generic brand-
        # prefix table entirely: only inventory rows whose own name carries
        # that exact brand word are eligible, so a "شوان" PDF can never end
        # up pricing a "ویسنا" row and vice versa.
        if self.target_brand:
            if normalize_text(self.target_brand) not in normalize_text(item.name):
                return MatchResult(
                    item=item, status=STATUS_NOT_FOUND, match_type=MATCH_NONE,
                    note="برند این کالا با برند لیست قیمت وارد شده یکی نیست",
                )
        elif self.cfg.get("restrict_to_price_list_brands", True) and not item.brand:
            return MatchResult(
                item=item, status=STATUS_NOT_FOUND, match_type=MATCH_NONE,
                note="برند این کالا در لیست قیمت وجود ندارد",
            )

        positions = index.candidates(item, self.max_candidates)
        if not positions:
            return MatchResult(item=item, status=STATUS_NOT_FOUND, match_type=MATCH_NONE)

        scored = []
        for position in positions:
            value, kind, note = self.score(item, index.items[position], index, position)
            scored.append((value, position, kind, note))
        scored.sort(key=lambda row: row[0], reverse=True)

        best_value, best_position, kind, note = scored[0]
        if best_value < self.review_threshold:
            return MatchResult(
                item=item, score=best_value,
                status=STATUS_NOT_FOUND, match_type=MATCH_NONE,
            )

        best = index.items[best_position]
        status = self._status_for(best_value)
        alternatives: list[str] = []

        rivals = [row for row in scored[1:4] if row[0] >= self.review_threshold]
        close = [row for row in rivals if best_value - row[0] < self.ambiguity_margin]
        # two candidates that carry the same price are not really ambiguous:
        # whichever one is picked, the answer the user reads is identical
        close = [row for row in close if index.items[row[1]].price != best.price]
        if close:
            status = STATUS_REVIEW if status != STATUS_EXACT else status
            note = note or "چند ردیف مشابه در لیست قیمت"
            alternatives = [
                f"{index.items[row[1]].code} - {index.items[row[1]].price:,.0f}"
                for row in close
            ]

        return MatchResult(
            item=item, matched=best, score=best_value,
            match_type=kind, status=status, note=note, alternatives=alternatives,
        )

    def match_all(
        self,
        stock_items: Sequence[StockItem],
        price_items: Sequence[PriceItem],
        progress: Callable[[int, int], None] | None = None,
    ) -> list[MatchResult]:
        index = PriceIndex(price_items)
        log.info("index built over %d price rows", len(index.items))
        results: list[MatchResult] = []
        total = len(stock_items)
        step = max(1, total // 50)
        for position, item in enumerate(stock_items):
            results.append(self.match_one(item, index))
            if progress and (position % step == 0 or position == total - 1):
                progress(position + 1, total)
        return results


# ------------------------------------------------------------- preparation
def prepare_stock(item: StockItem, config: dict | None = None) -> StockItem:
    """Fill the derived keys an inventory row is matched on."""
    cfg = config or load_config()
    item.name_key = normalize_text(item.name)
    item.expanded = expand_synonyms(
        item.name, cfg.get("synonyms"), cfg.get("context_rules"),
    )
    item.brand = detect_brand(item.name, cfg.get("brand_prefixes"))
    item.codes = extract_codes(item.name)
    item.specs = extract_specs(item.name)
    item.tokens = tuple(dict.fromkeys(_tokens_with_bigrams(item.expanded)))
    if not item.codes and item.code:
        candidate = normalize_code(item.code)
        if candidate and not candidate.isdigit():
            item.codes = [candidate]
    return item


def _tokens_with_bigrams(text: str) -> list[str]:
    """Words of `text`, plus every adjacent pair glued together.

    Two things make the pairs necessary. PDF text has no reliable word
    boundaries, so it is searched in its space-free form - where "سه پل"
    only ever appears as "سهپل". And the words that carry the meaning here
    are short pairs ("تک پل", "اسلیم لاین", "فول لایت", "نقره ای") whose
    halves are far too common to identify anything on their own.
    """
    words = [word for word in text.split(" ") if word]
    out = list(words)
    out.extend(words[i] + words[i + 1] for i in range(len(words) - 1))
    return out


def summarize(results: Sequence[MatchResult]) -> dict:
    stats = {
        "total": len(results), "exact": 0, "high": 0, "review": 0,
        "not_found": 0, "matched": 0, "priced": 0,
        "in_stock": 0, "out_of_stock": 0,
    }
    for result in results:
        if result.status == STATUS_EXACT:
            stats["exact"] += 1
        elif result.status == STATUS_HIGH:
            stats["high"] += 1
        elif result.status == STATUS_REVIEW:
            stats["review"] += 1
        else:
            stats["not_found"] += 1
        if result.matched is not None and result.status in (STATUS_EXACT, STATUS_HIGH):
            stats["matched"] += 1
        if result.matched is not None and result.matched.price is not None:
            stats["priced"] += 1
            if (result.item.stock or 0) > 0:
                stats["in_stock"] += 1
            else:
                stats["out_of_stock"] += 1
    return stats
