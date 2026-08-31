"""Temporary debug probe for supabase db reset host connectivity. Do not commit."""
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "debug-6c9ba9.log"
SESSION = "6c9ba9"


def emit(hypothesis_id: str, location: str, message: str, data: dict):
    rec = {
        "sessionId": SESSION,
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def tcp_probe(host: str, port: int, timeout: float = 8.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.connect((host, port))
        ms = round((time.time() - t0) * 1000)
        return True, ms, None
    except Exception as e:
        ms = round((time.time() - t0) * 1000)
        return False, ms, f"{type(e).__name__}: {e}"
    finally:
        s.close()


def main():
    emit("A", "scripts/_debug_supabase_db.py:main", "probe_start", {"utc": datetime.now(timezone.utc).isoformat()})

    for hid, host, port in [
        ("B", "127.0.0.1", 54322),
        ("C", "127.0.0.1", 54321),
        ("D", "localhost", 54322),
    ]:
        ok, ms, err = tcp_probe(host, port)
        emit(hid, "scripts/_debug_supabase_db.py:tcp_probe", "tcp_result", {
            "host": host, "port": port, "ok": ok, "ms": ms, "error": err,
        })

    # Postgres protocol: send startup and see if we get a response (no password in logs)
    host, port = "127.0.0.1", 54322
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(8.0)
    t0 = time.time()
    try:
        s.connect((host, port))
        # SSLRequest
        s.sendall(b"\x00\x00\x00\x08\x04\xd2\x16\x2f")
        first = s.recv(1)
        emit("E", "scripts/_debug_supabase_db.py:pg_ssl", "postgres_responded", {
            "first_byte": first.decode("ascii", "replace") if first else None,
            "ms": round((time.time() - t0) * 1000),
        })
    except Exception as e:
        emit("E", "scripts/_debug_supabase_db.py:pg_ssl", "postgres_no_response", {
            "error": f"{type(e).__name__}: {e}",
            "ms": round((time.time() - t0) * 1000),
        })
    finally:
        s.close()


if __name__ == "__main__":
    main()
