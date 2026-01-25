#!/usr/bin/env python3
import os
import json
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from agents.tool_context import ToolContext
import asyncio

try:
    from futureshow.tool.tool_polymarket_data import get_polymarket_info_by_slug
except Exception:  # pragma: no cover - optional dependency fallback
    get_polymarket_info_by_slug = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data" / "agent_data"
RUNTIME_ENV_PATH = os.environ.get("RUNTIME_ENV_PATH", str(PROJECT_ROOT / ".runtime_env.json"))

# ------------- helpers -------------

def load_runtime_env() -> dict:
    try:
        if os.path.exists(RUNTIME_ENV_PATH):
            with open(RUNTIME_ENV_PATH, "r", encoding="utf-8") as f:
                obj = json.load(f)
                if isinstance(obj, dict):
                    return obj
    except Exception:
        pass
    return {}

def get_default_signature() -> str | None:
    env = load_runtime_env()
    sig = env.get("SIGNATURE")
    if isinstance(sig, str) and sig.strip():
        return sig
    # fallback: pick first folder under data/agent_data
    if DATA_DIR.exists():
        for p in DATA_DIR.iterdir():
            if p.is_dir():
                return p.name
    return None

# JSONL reading

def read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            if limit is None:
                for line in f:
                    if line.strip():
                        try:
                            out.append(json.loads(line))
                        except Exception:
                            continue
            else:
                # read last N lines efficiently
                import deque as _dq  # type: ignore
    except Exception:
        # Fallback simple
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
    return out

# ------------- HTTP handler -------------

class APIServer(SimpleHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            self._set_cors()
            self.end_headers()
        else:
            super().do_OPTIONS()

    def _send_json(self, data: dict, code: int = 200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._set_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def translate_path(self, path: str) -> str:
        # serve static files from FRONTEND_DIR for non-API paths
        if path.startswith("/api/"):
            return super().translate_path(path)
        rel = path.lstrip("/")
        if not rel:
            rel = "index.html"
        return str(FRONTEND_DIR / rel)

    # ---------- API routes ----------

    def _handle_status(self, qs: dict[str, list[str]]):
        env = load_runtime_env()
        sig = qs.get("signature", [None])[0] or get_default_signature()
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        # gather basic model list for convenience on landing
        models = []
        if DATA_DIR.exists():
            try:
                models = [p.name for p in DATA_DIR.iterdir() if p.is_dir()]
                models.sort()
            except Exception:
                models = []
        self._send_json({
            "ok": True,
            "signature": sig,
            "env": env,
            "server_time": now,
            "models": models,
            "models_count": len(models),
        })

    def _handle_positions(self, qs: dict[str, list[str]]):
        signature = qs.get("signature", [None])[0] or get_default_signature()
        if not signature:
            self._send_json({"ok": False, "error": "signature not found"}, 400)
            return
        pos_file = DATA_DIR / signature / "position" / "position.jsonl"
        rows = read_jsonl(pos_file)
        # derive trades from this_action
        trades = []
        for r in rows:
            act = r.get("this_action") or {}
            if isinstance(act, dict) and act.get("action") in ("buy", "sell", "settle"):
                trades.append({
                    "timestamp": r.get("timestamp") or r.get("date"),
                    **{k: v for k, v in act.items()}
                })
        latest = rows[-1] if rows else {}
        self._send_json({
            "ok": True,
            "signature": signature,
            "latest": latest,
            "trades": trades[-200:],  # cap
            "total_records": len(rows),
        })

    def _handle_pnl(self, qs: dict[str, list[str]]):
        signature = qs.get("signature", [None])[0] or get_default_signature()
        date = qs.get("date", [None])[0] or datetime.utcnow().strftime("%Y-%m-%d")
        full_flag_raw = qs.get("full", ["0"])[0]
        full_flag = isinstance(full_flag_raw, str) and full_flag_raw.lower() in {"1", "true", "yes", "all"}
        if not signature:
            self._send_json({"ok": False, "error": "signature not found"}, 400)
            return
        pnl_dir = DATA_DIR / signature / "pnl"
        rows: list[dict] = []
        used_date: str | None = date

        if full_flag:
            try:
                candidates = sorted(pnl_dir.glob("intraday_*.jsonl"))
            except Exception:
                candidates = []
            for fp in candidates:
                chunk = read_jsonl(fp)
                if not chunk:
                    continue
                rows.extend(chunk)
            if candidates:
                used_date = "ALL"
        else:
            f = pnl_dir / f"intraday_{date}.jsonl"
            rows = read_jsonl(f)
            # 回退：如果今天没有数据文件，选用该模型最新的 intraday_*.jsonl
            if not rows:
                try:
                    candidates = sorted(pnl_dir.glob("intraday_*.jsonl"))
                except Exception:
                    candidates = []
                if candidates:
                    latest = candidates[-1]
                    rows = read_jsonl(latest)
                    # parse yyyy-mm-dd from filename
                    try:
                        used_date = latest.stem.split("_")[1]
                    except Exception:
                        used_date = date

        if rows:
            timeline: dict[str, dict] = {}
            for r in rows:
                ts = r.get("timestamp") or r.get("as_of")
                if not ts:
                    continue
                timeline[ts] = r
            sorted_ts = sorted(timeline.keys())
            times = sorted_ts
            nav = [timeline[t].get("nav") for t in sorted_ts]
            ret = [timeline[t].get("return") for t in sorted_ts]
            ordered_rows = [timeline[t] for t in sorted_ts]
        else:
            times, nav, ret, ordered_rows = [], [], [], []

        latest = ordered_rows[-1] if ordered_rows else {}
        self._send_json({
            "ok": True,
            "signature": signature,
            "date": used_date,
            "times": times,
            "nav": nav,
            "returns": ret,
            "latest": latest,
            "count": len(ordered_rows),
            "full": full_flag,
        })

    def _find_latest_log_file(self, signature: str) -> Path | None:
        base = DATA_DIR / signature / "log"
        if not base.exists():
            return None
        days = sorted([p.name for p in base.iterdir() if p.is_dir()])
        if not days:
            return None
        return base / days[-1] / "log.jsonl"

    def _handle_messages(self, qs: dict[str, list[str]]):
        signature = qs.get("signature", [None])[0] or get_default_signature()
        if not signature:
            self._send_json({"ok": False, "error": "signature not found"}, 400)
            return
        log_file = self._find_latest_log_file(signature)
        rows = read_jsonl(log_file) if log_file else []
        # flatten new_messages
        messages = []
        for r in rows:
            ts = r.get("timestamp")
            for m in r.get("new_messages", []) or []:
                role = m.get("role")
                content = m.get("content")
                if isinstance(content, str) and content.strip():
                    messages.append({"timestamp": ts, "role": role, "content": content})
        self._send_json({
            "ok": True,
            "signature": signature,
            "messages": messages[-500:],
            "count": len(messages),
        })

    def _handle_polymarket_info(self, qs: dict[str, list[str]]):
        slug = qs.get("slug", [None])[0]
        if not slug:
            self._send_json({"ok": False, "error": "slug required"}, 400)
            return
        if get_polymarket_info_by_slug is None:
            self._send_json({"ok": False, "error": "polymarket tool unavailable"}, 500)
            return
        try:
            args = dict(slug=slug)
            ctx = ToolContext(
                context=None,
                tool_name="get_polymarket_info_by_slug",
                tool_call_id="get-polymarket-info-by-slug-test",
                tool_arguments=json.dumps(args)
            )
            info = asyncio.run(
                get_polymarket_info_by_slug.on_invoke_tool(
                    ctx,
                    json.dumps(args)
                )
            )
        except Exception as e:  # pragma: no cover
            self._send_json({"ok": False, "error": str(e)}, 500)
            return
        self._send_json({"ok": True, "slug": slug, "data": info})

    def _handle_models(self, qs: dict[str, list[str]]):
        # List available model signatures based on folders under DATA_DIR
        items: list[dict] = []
        if DATA_DIR.exists():
            try:
                for p in sorted([p for p in DATA_DIR.iterdir() if p.is_dir()], key=lambda x: x.name):
                    # inspect last updated time from position or pnl files
                    latest_ts = None
                    try:
                        pos = p / "position" / "position.jsonl"
                        pnl_dir = p / "pnl"
                        ts_candidates: list[float] = []
                        if pos.exists():
                            ts_candidates.append(pos.stat().st_mtime)
                        if pnl_dir.exists():
                            for pf in pnl_dir.glob("intraday_*.jsonl"):
                                ts_candidates.append(pf.stat().st_mtime)
                        if ts_candidates:
                            latest_ts = max(ts_candidates)
                    except Exception:
                        latest_ts = None
                    items.append({
                        "signature": p.name,
                        "name": p.name,
                        "last_modified": datetime.utcfromtimestamp(latest_ts).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_ts else None,
                    })
            except Exception:
                pass
        self._send_json({
            "ok": True,
            "models": items,
            "count": len(items),
            "default": get_default_signature(),
        })

    def do_GET(self):
        if self.path.startswith("/api/"):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/api/status":
                return self._handle_status(qs)
            if parsed.path == "/api/positions":
                return self._handle_positions(qs)
            if parsed.path == "/api/pnl":
                return self._handle_pnl(qs)
            if parsed.path == "/api/messages":
                return self._handle_messages(qs)
            if parsed.path == "/api/models":
                return self._handle_models(qs)
            if parsed.path == "/api/polymarket_info":
                return self._handle_polymarket_info(qs)
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        return super().do_GET()


def main():
    os.chdir(PROJECT_ROOT)
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "10032"))
    httpd = ThreadingHTTPServer((host, port), APIServer)
    print(f"🌐 Serving frontend from {FRONTEND_DIR} and APIs at http://{host}:{port}/api/*")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
