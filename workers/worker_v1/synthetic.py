from __future__ import annotations
import argparse, json, sys, time

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--duration", type=float, required=True); p.add_argument("--outcome", choices=["PASS", "FAIL"], required=True); p.add_argument("--stderr", action="store_true"); p.add_argument("--completion-file", required=True)
    a = p.parse_args()
    print("W2_SYNTHETIC_STARTED", flush=True)
    if a.stderr: print("W2_SYNTHETIC_DIAGNOSTIC", file=sys.stderr, flush=True)
    time.sleep(a.duration)
    with open(a.completion_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"schema":"deputy.worker-completion.v1","overall":a.outcome}, f, sort_keys=True); f.write("\n"); f.flush()
    print("W2_SYNTHETIC_FINISHED", flush=True)
    return 0 if a.outcome == "PASS" else 1

if __name__ == "__main__": raise SystemExit(main())
