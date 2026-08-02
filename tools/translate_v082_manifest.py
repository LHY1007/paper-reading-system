#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CJK_RE = re.compile(r"[\u3400-\u9fff]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def split_chunks(text: str, limit: int = 420) -> list[str]:
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    sentences = SENTENCE_SPLIT_RE.split(text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            words = sentence.split()
            part = ""
            for word in words:
                if part and len(part) + len(word) + 1 > limit:
                    chunks.append(part)
                    part = word
                else:
                    part += (" " if part else "") + word
            if part:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(part)
            continue
        if current and len(current) + len(sentence) + 1 > limit:
            chunks.append(current)
            current = sentence
        else:
            current += (" " if current else "") + sentence
    if current:
        chunks.append(current)
    return chunks


class Translator:
    def __init__(self, model_name: str, cache_path: Path | None, identity: bool = False, batch_size: int = 12):
        self.model_name = model_name
        self.cache_path = cache_path
        self.identity = identity
        self.batch_size = batch_size
        self.cache: dict[str, str] = {}
        if cache_path and cache_path.exists():
            self.cache = json.loads(cache_path.read_text("utf-8"))
        self.model = None
        self.tokenizer = None
        if not identity:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
            self.model.eval()

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2) + "\n", "utf-8")

    @staticmethod
    def needs_translation(text: str) -> bool:
        if not text.strip() or CJK_RE.search(text):
            return False
        letters = sum(ch.isalpha() for ch in text)
        return letters >= 3

    def translate_chunks(self, chunks: list[str]) -> list[str]:
        if self.identity:
            return chunks
        import torch
        outputs: list[str] = []
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start:start + self.batch_size]
            encoded = self.tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=512)
            with torch.inference_mode():
                generated = self.model.generate(**encoded, max_new_tokens=512, num_beams=4, length_penalty=1.0)
            outputs.extend(self.tokenizer.batch_decode(generated, skip_special_tokens=True))
        return outputs

    def translate(self, text: str) -> str:
        text = " ".join(str(text).split())
        if not self.needs_translation(text):
            return text
        key = hashlib.sha256((self.model_name + "\n" + text).encode("utf-8")).hexdigest()
        if key in self.cache:
            return self.cache[key]
        chunks = split_chunks(text)
        translated = self.translate_chunks(chunks)
        result = "".join(translated) if all(CJK_RE.search(x or "") for x in translated) else " ".join(translated)
        result = re.sub(r"\s+([，。；：！？])", r"\1", result)
        self.cache[key] = result.strip()
        return self.cache[key]

    def translate_many(self, texts: list[str]) -> list[str]:
        missing: list[tuple[str, str]] = []
        for text in texts:
            normalized = " ".join(str(text).split())
            if not self.needs_translation(normalized):
                continue
            key = hashlib.sha256((self.model_name + "\n" + normalized).encode("utf-8")).hexdigest()
            if key not in self.cache:
                missing.append((key, normalized))
        chunk_records: list[tuple[str, list[str]]] = []
        all_chunks: list[str] = []
        for key, text in missing:
            chunks = split_chunks(text)
            chunk_records.append((key, chunks))
            all_chunks.extend(chunks)
        if all_chunks:
            translated_chunks = self.translate_chunks(all_chunks)
            cursor = 0
            for key, chunks in chunk_records:
                values = translated_chunks[cursor:cursor + len(chunks)]
                cursor += len(chunks)
                result = "".join(values) if all(CJK_RE.search(x or "") for x in values) else " ".join(values)
                result = re.sub(r"\s+([，。；：！？])", r"\1", result).strip()
                self.cache[key] = result
        return [self.translate(text) for text in texts]


def collect_texts(manifest: dict[str, Any]) -> list[str]:
    texts = [manifest["paper"]["title_en"]]
    ov = manifest["overview"]
    texts.extend(x["answer"] for x in ov["qa"])
    texts.extend([ov.get("method", ""), ov.get("story", "")])
    for section in manifest["sections"]:
        texts.append(section["title_en"])
        for block in section["blocks"]:
            if block["type"] == "paragraph":
                texts.extend(item["text"] for item in block["english"])
    for asset in manifest["assets"]:
        texts.extend([asset["title_en"], asset["intro"], asset["caption_en"]])
        study = asset.get("study") or {}
        texts.extend([study.get("overview", ""), study.get("conclusion", ""), study.get("boundary", "")])
        for panel in study.get("panels", []):
            texts.extend([panel.get("title", ""), panel.get("explanation", "")])
    return [x for x in texts if x]


def glossary_terms(manifest: dict[str, Any], glossary: dict[str, str]) -> list[dict[str, Any]]:
    corpus = "\n".join(
        item["text"]
        for section in manifest["sections"]
        for block in section["blocks"] if block["type"] == "paragraph"
        for item in block["english"]
    ).lower()
    terms = []
    seen_ids = set()
    for english, chinese in sorted(glossary.items(), key=lambda x: (-len(x[0]), x[0].lower())):
        if english.lower() not in corpus:
            continue
        tid = re.sub(r"[^a-z0-9]+", "-", english.lower()).strip("-")[:64]
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        terms.append({
            "id": tid,
            "label": english,
            "definition_zh": f"{chinese}。原文术语：{english}。",
            "aliases": [english],
            "category": "生物医学术语",
            "level": 2,
        })
    return terms[:120]


def annotate_items(items: list[dict[str, Any]], terms: list[dict[str, Any]], chinese: bool = False) -> list[dict[str, Any]]:
    aliases: list[tuple[str, str]] = []
    for term in terms:
        aliases.append((term["definition_zh"].split("。", 1)[0] if chinese else term["label"], term["id"]))
    aliases.sort(key=lambda x: len(x[0]), reverse=True)
    output: list[dict[str, Any]] = []
    for item in items:
        if item.get("figure_ids") or item.get("section_id") or item.get("term_id"):
            output.append(item)
            continue
        text = item.get("text", "")
        matches = []
        for alias, tid in aliases:
            flags = 0 if chinese else re.I
            for m in re.finditer(re.escape(alias), text, flags):
                matches.append((m.start(), m.end(), tid))
        matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        selected = []
        cursor = -1
        for start, end, tid in matches:
            if start >= cursor:
                selected.append((start, end, tid))
                cursor = end
        if not selected:
            output.append(item)
            continue
        pos = 0
        for start, end, tid in selected:
            if start > pos:
                output.append({"text": text[pos:start]})
            output.append({"text": text[start:end], "term_id": tid})
            pos = end
        if pos < len(text):
            output.append({"text": text[pos:]})
        if item.get("citation_ids"):
            output[-1]["citation_ids"] = item["citation_ids"]
    return output


def normalize_glossary_translation(text: str, glossary: dict[str, str]) -> str:
    replacements = {
        "肿瘤微环境(TME)": "肿瘤微环境（TME）",
        "肿瘤免疫微环境(TIME)": "肿瘤免疫微环境（TIME）",
        "血红素和伊红": "苏木精-伊红",
        "苏木精和伊红": "苏木精-伊红",
        "全幻灯片图像": "全切片图像",
        "全片图像": "全切片图像",
        "胶质细胞母细胞瘤": "胶质母细胞瘤",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def translate_manifest(manifest: dict[str, Any], translator: Translator, glossary: dict[str, str]) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    translator.translate_many(collect_texts(result))
    result["paper"]["title_zh"] = normalize_glossary_translation(translator.translate(result["paper"]["title_en"]), glossary)
    ov = result["overview"]
    for qa in ov["qa"]:
        qa["answer"] = normalize_glossary_translation(translator.translate(qa["answer"]), glossary)
    ov["method"] = normalize_glossary_translation(translator.translate(ov.get("method", "")), glossary)
    ov["story"] = normalize_glossary_translation(translator.translate(ov.get("story", "")), glossary)

    for section in result["sections"]:
        section["title_zh"] = normalize_glossary_translation(translator.translate(section["title_en"]), glossary)
        for block in section["blocks"]:
            if block["type"] != "paragraph":
                continue
            chinese_items = []
            for item in block["english"]:
                translated_item = {"text": normalize_glossary_translation(translator.translate(item.get("text", "")), glossary)}
                for key in ("citation_ids", "figure_ids", "section_id"):
                    if key in item:
                        translated_item[key] = copy.deepcopy(item[key])
                chinese_items.append(translated_item)
            block["chinese"] = chinese_items

    for asset in result["assets"]:
        asset["title_zh"] = normalize_glossary_translation(translator.translate(asset["title_en"]), glossary)
        asset["intro"] = normalize_glossary_translation(translator.translate(asset["intro"]), glossary)
        asset["caption_zh"] = normalize_glossary_translation(translator.translate(asset["caption_en"]), glossary)
        study = asset.get("study") or {}
        if study:
            study["overview"] = normalize_glossary_translation(translator.translate(study.get("overview", "")), glossary)
            study["conclusion"] = normalize_glossary_translation(translator.translate(study.get("conclusion", "")), glossary)
            study["boundary"] = "图表解读仅依据原始图注与正文明确陈述，不添加来源未支持的因果解释。"
            for panel in study.get("panels", []):
                panel["title"] = normalize_glossary_translation(translator.translate(panel.get("title", "")), glossary)
                panel["explanation"] = normalize_glossary_translation(translator.translate(panel.get("explanation", "")), glossary)

    terms = glossary_terms(result, glossary)
    result["terms"] = terms
    for section in result["sections"]:
        for block in section["blocks"]:
            if block["type"] == "paragraph":
                block["english"] = annotate_items(block["english"], terms, chinese=False)
                block["chinese"] = annotate_items(block["chinese"], terms, chinese=True)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Translate and terminology-normalize a V0.8.2 PDF-native manifest")
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--glossary", type=Path, required=True)
    p.add_argument("--cache", type=Path)
    p.add_argument("--model", default="Helsinki-NLP/opus-mt-en-zh")
    p.add_argument("--batch-size", type=int, default=12)
    p.add_argument("--identity", action="store_true")
    args = p.parse_args()
    manifest = json.loads(args.input.read_text("utf-8"))
    glossary = json.loads(args.glossary.read_text("utf-8"))
    translator = Translator(args.model, args.cache, identity=args.identity, batch_size=args.batch_size)
    result = translate_manifest(manifest, translator, glossary)
    translator.save()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"output": str(args.output), "terms": len(result["terms"]), "cache_entries": len(translator.cache)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
