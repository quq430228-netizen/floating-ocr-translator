from __future__ import annotations

import html
import http.client
import http.cookiejar
import json
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid
from typing import Optional

import numpy as np
from PIL import Image


def _has_mostly_cjk(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha() or ("\u4e00" <= ch <= "\u9fff")]
    if not letters:
        return False
    cjk = sum(1 for ch in letters if "\u4e00" <= ch <= "\u9fff")
    return (cjk / len(letters)) >= 0.6


def _merge_ocr_lines(ocr_result: list) -> str:
    """Group RapidOCR bounding boxes into clean, readable lines & paragraphs."""
    if not ocr_result:
        return ""

    items: list[tuple[float, float, float, float, str]] = []
    for entry in ocr_result:
        if not entry or len(entry) < 2:
            continue
        box, txt = entry[0], str(entry[1]).strip()
        if not txt:
            continue
        xs = [float(pt[0]) for pt in box]
        ys = [float(pt[1]) for pt in box]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        y_mid = (y_min + y_max) / 2.0
        h = max(8.0, y_max - y_min)
        items.append((y_mid, x_min, h, x_max, txt))

    if not items:
        return ""

    # Sort roughly top-to-bottom, then left-to-right
    items.sort(key=lambda it: (it[0], it[1]))

    # Group items that sit on the same horizontal visual line
    lines: list[list[tuple[float, float, float, float, str]]] = []
    for item in items:
        y_mid, _x_min, h, _x_max, _txt = item
        placed = False
        for line in lines:
            ref_y = sum(x[0] for x in line) / len(line)
            ref_h = sum(x[2] for x in line) / len(line)
            if abs(y_mid - ref_y) <= max(h, ref_h) * 0.55:
                line.append(item)
                placed = True
                break
        if not placed:
            lines.append([item])

    # Sort each line left-to-right and join into sentences/paragraphs
    lines.sort(key=lambda ln: sum(x[0] for x in ln) / len(ln))
    rendered_lines: list[tuple[float, float, str]] = []
    for ln in lines:
        ln.sort(key=lambda x: x[1])
        avg_y = sum(x[0] for x in ln) / len(ln)
        avg_h = sum(x[2] for x in ln) / len(ln)
        parts: list[str] = []
        for _, _, _, _, t in ln:
            if parts and parts[-1][-1].isascii() and t[0].isascii():
                parts.append(" " + t)
            else:
                parts.append(t)
        rendered_lines.append((avg_y, avg_h, "".join(parts).strip()))

    paragraphs: list[str] = []
    cur_para = rendered_lines[0][2]
    prev_y, prev_h = rendered_lines[0][0], rendered_lines[0][1]

    for y, h, line_text in rendered_lines[1:]:
        gap = y - prev_y
        # Large vertical gap or terminal punctuation -> new paragraph
        if gap > max(prev_h, h) * 1.75 or cur_para.endswith((".", "!", "?", "。", "！", "？", ":")):
            paragraphs.append(cur_para)
            cur_para = line_text
        elif cur_para.endswith("-") and len(cur_para) >= 2 and cur_para[-2].isalpha():
            cur_para = cur_para[:-1] + line_text
        else:
            sep = " " if (cur_para[-1].isascii() and line_text[0].isascii()) else ""
            cur_para = cur_para + sep + line_text
        prev_y, prev_h = y, h

    if cur_para:
        paragraphs.append(cur_para)
    return "\n".join(paragraphs).strip()


def _split_text_chunks(text: str, max_chars: int = 1600) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    current: list[str] = []
    cur_len = 0
    for para in text.split("\n"):
        if len(para) > max_chars:
            if current:
                chunks.append("\n".join(current))
                current, cur_len = [], 0
            # Split long paragraph by sentence boundaries
            sentences = re.split(r"(?<=[.!?。！？])\s+", para)
            buf = ""
            for sent in sentences:
                if len(buf) + len(sent) + 1 <= max_chars:
                    buf = f"{buf} {sent}".strip() if buf else sent
                else:
                    if buf:
                        chunks.append(buf)
                    buf = sent[:max_chars]
            if buf:
                chunks.append(buf)
        else:
            added = len(para) + (1 if current else 0)
            if cur_len + added > max_chars:
                chunks.append("\n".join(current))
                current = [para]
                cur_len = len(para)
            else:
                current.append(para)
                cur_len += added
    if current:
        chunks.append("\n".join(current))
    return chunks


class LocalOCREngine:
    """Offline OCR powered by RapidOCR (ONNX Runtime)."""

    def __init__(self) -> None:
        self._ocr = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._ocr is not None

    def load(self) -> None:
        if self._ocr is not None:
            return
        from rapidocr_onnxruntime import RapidOCR

        self._ocr = RapidOCR()

    def extract_text(self, image: Image.Image) -> str:
        if self._ocr is None:
            self.load()
        rgb = image.convert("RGB")
        # Upscale very small screenshots slightly for sharper OCR accuracy
        w, h = rgb.size
        if max(w, h) < 420 and min(w, h) > 0:
            scale = min(2.0, 420.0 / max(w, h))
            rgb = rgb.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        arr = np.array(rgb)
        with self._lock:
            result, _ = self._ocr(arr)
        return _merge_ocr_lines(result or [])


class FreeTranslator:
    """Zero-API-key translator prioritizing low-latency direct China endpoints."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }

    def __init__(self) -> None:
        self._client_key = f"browser-chrome-126.0.0-Windows 10-{uuid.uuid4()}"
        self._ssl_ctx = ssl.create_default_context()
        # Direct opener bypasses system proxy so domestic China endpoints stay fast and reliable
        self._direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._proxy_opener = urllib.request.build_opener()

        # Persistent Keep-Alive connection for Tencent TranSmart
        self._tm_lock = threading.Lock()
        self._tm_conn: Optional[http.client.HTTPSConnection] = None

        # Cached session/token for Bing CN fallback
        self._bing_lock = threading.Lock()
        self._bing_cookies = http.cookiejar.CookieJar()
        self._bing_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self._bing_cookies),
        )
        self._bing_token_cache: Optional[tuple[str, str, str, str, float]] = None
        self._bing_req_seq = 0

    def translate(self, text: str, auto_swap_zh_en: bool = False) -> tuple[str, str]:
        """Translate text and return (translated_text, direction_label)."""
        clean = text.strip()
        if not clean:
            return "", ""

        target = "en" if (auto_swap_zh_en and _has_mostly_cjk(clean)) else "zh-CN"
        direction = "中 → 英" if target == "en" else "英 → 中"

        chunks = _split_text_chunks(clean, max_chars=1500)
        translated_chunks: list[str] = []
        for chunk in chunks:
            translated_chunks.append(self._translate_chunk(chunk, target=target))
        return "\n".join(translated_chunks).strip(), direction

    def _translate_chunk(self, text: str, target: str) -> str:
        errors: list[str] = []

        # Tier 1: Tencent TranSmart (domestic China direct + TLS Keep-Alive, ~200-400ms)
        try:
            return self._tencent_transmart(text, target)
        except Exception as exc:
            errors.append(f"transmart: {exc}")

        # Tier 2: Youdao Mobile (domestic China direct, ~150-250ms)
        try:
            return self._youdao_mobile(text, target)
        except Exception as exc:
            errors.append(f"youdao: {exc}")

        # Tier 3: Bing CN (domestic China direct, cached token)
        try:
            return self._bing_cn(text, target)
        except Exception as exc:
            errors.append(f"bing_cn: {exc}")

        # Tier 4: Google GTX final fallback (uses system proxy if configured)
        try:
            return self._google_gtx(text, target)
        except Exception as exc:
            errors.append(f"gtx: {exc}")

        raise RuntimeError("翻译服务暂时不可用，请检查网络连接（" + "; ".join(errors[:2]) + "）")

    def _post_transmart_keepalive(self, body: bytes) -> dict:
        headers = {
            "User-Agent": self.HEADERS["User-Agent"],
            "Content-Type": "application/json",
            "Origin": "https://transmart.qq.com",
            "Referer": "https://transmart.qq.com/",
            "Connection": "keep-alive",
        }
        with self._tm_lock:
            last_exc: Optional[Exception] = None
            for _attempt in range(2):
                try:
                    if self._tm_conn is None:
                        self._tm_conn = http.client.HTTPSConnection(
                            "transmart.qq.com",
                            443,
                            timeout=5,
                            context=self._ssl_ctx,
                        )
                    self._tm_conn.request("POST", "/api/imt", body=body, headers=headers)
                    resp = self._tm_conn.getresponse()
                    raw = resp.read()
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    return json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    last_exc = exc
                    if self._tm_conn is not None:
                        try:
                            self._tm_conn.close()
                        except Exception:
                            pass
                        self._tm_conn = None
            assert last_exc is not None
            raise last_exc

    def _tencent_transmart(self, text: str, target: str) -> str:
        raw_lines = text.split("\n")
        non_empty_indices = [i for i, ln in enumerate(raw_lines) if ln.strip()]
        if not non_empty_indices:
            return ""
        text_list = [raw_lines[i] for i in non_empty_indices]

        tgt_lang = "en" if target == "en" else "zh"
        src_lang = "zh" if target == "en" else "auto"
        payload = {
            "header": {
                "fn": "auto_translation",
                "client_key": self._client_key,
            },
            "type": "plain",
            "model_category": "normal",
            "source": {
                "lang": src_lang,
                "text_list": text_list,
            },
            "target": {
                "lang": tgt_lang,
            },
        }
        data = self._post_transmart_keepalive(json.dumps(payload).encode("utf-8"))
        ret_code = str(data.get("header", {}).get("ret_code", ""))
        translated_list = data.get("auto_translation")
        if ret_code != "succ" or not isinstance(translated_list, list) or len(translated_list) != len(text_list):
            raise ValueError(f"unexpected transmart payload (ret_code={ret_code!r})")

        out_lines = list(raw_lines)
        for idx, translated in zip(non_empty_indices, translated_list):
            out_lines[idx] = html.unescape(str(translated)).strip()
        result = "\n".join(out_lines).strip()
        if not result:
            raise ValueError("empty transmart result")
        return result

    def _youdao_mobile(self, text: str, target: str) -> str:
        trans_type = "ZH_CN2EN" if target == "en" else "AUTO"
        body = urllib.parse.urlencode({"inputtext": text, "type": trans_type}).encode("utf-8")
        req = urllib.request.Request(
            "https://m.youdao.com/translate",
            data=body,
            headers={
                "User-Agent": self.HEADERS["User-Agent"],
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://m.youdao.com",
                "Referer": "https://m.youdao.com/translate",
            },
        )
        with self._direct_opener.open(req, timeout=5) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
        ul_match = re.search(r'<ul id="translateResult">(.*?)</ul>', page, re.S)
        if not ul_match:
            raise ValueError("missing translateResult in youdao response")
        items = [
            html.unescape(item).strip()
            for item in re.findall(r"<li>(.*?)</li>", ul_match.group(1), re.S)
        ]
        joined = "\n".join(items).strip()
        if not joined:
            raise ValueError("empty youdao result")
        return joined

    def _get_bing_cn_token(self) -> tuple[str, str, str, str]:
        now = time.monotonic()
        if self._bing_token_cache is not None:
            ig, iid, key, token, ts = self._bing_token_cache
            if (now - ts) < 480.0:
                return ig, iid, key, token

        req = urllib.request.Request("https://cn.bing.com/translator", headers=self.HEADERS)
        with self._bing_opener.open(req, timeout=6) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
        ig_m = re.search(r'IG:"([^"]+)"', page)
        iid_m = re.search(r'data-iid="([^"]+)"', page)
        params_m = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),"([^"]+)"', page)
        if not ig_m or not params_m:
            raise ValueError("failed to extract Bing CN session token")
        ig = ig_m.group(1)
        iid = iid_m.group(1) if iid_m else "translator.5024"
        key, token = params_m.group(1), params_m.group(2)
        self._bing_token_cache = (ig, iid, key, token, now)
        return ig, iid, key, token

    def _bing_cn(self, text: str, target: str) -> str:
        to_lang = "en" if target == "en" else "zh-Hans"
        with self._bing_lock:
            ig, iid, key, token = self._get_bing_cn_token()
            self._bing_req_seq += 1
            seq = self._bing_req_seq
            url = f"https://cn.bing.com/ttranslatev3?isVertical=1&IG={ig}&IID={iid}.{seq}"
            body = urllib.parse.urlencode(
                {
                    "fromLang": "auto-detect",
                    "text": text,
                    "to": to_lang,
                    "token": token,
                    "key": key,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "User-Agent": self.HEADERS["User-Agent"],
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://cn.bing.com",
                    "Referer": "https://cn.bing.com/translator",
                },
            )
            try:
                with self._bing_opener.open(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                self._bing_token_cache = None
                raise

        if isinstance(data, list) and data and isinstance(data[0], dict):
            translations = data[0].get("translations")
            if isinstance(translations, list) and translations:
                out = str(translations[0].get("text", "")).strip()
                if out:
                    return out
        self._bing_token_cache = None
        raise ValueError("unexpected bing_cn payload")

    def _google_gtx(self, text: str, target: str) -> str:
        params = urllib.parse.urlencode(
            {
                "client": "gtx",
                "sl": "auto",
                "tl": target,
                "dt": "t",
                "q": text,
            }
        )
        url = f"https://translate.googleapis.com/translate_a/single?{params}"
        req = urllib.request.Request(url, headers=self.HEADERS)
        with self._proxy_opener.open(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data and isinstance(data[0], list):
            joined = "".join(str(seg[0]) for seg in data[0] if seg and seg[0])
            if joined.strip():
                return joined.strip()
        raise ValueError("unexpected gtx payload")
