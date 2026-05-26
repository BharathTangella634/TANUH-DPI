"""
DPI Concurrency Test Suite
===========================
Stress-tests concurrent request handling for all 4 DPI services.
Writes a detailed timing report to a .txt file for analysis.

Usage:
    python3 concurrency_test.py --service clinical --concurrent 200 --base-url https://dpi-dev.tanuh.ai
    python3 concurrency_test.py --service insurance --concurrent 200 --base-url https://dpi-dev.tanuh.ai
    python3 concurrency_test.py --service privacy --concurrent 200 --base-url https://dpi-dev.tanuh.ai
    python3 concurrency_test.py --service forgery --concurrent 200 --base-url https://dpi-dev.tanuh.ai

Requirements:
    pip install requests
"""

import argparse
import time
import json
import os
import sys
import statistics
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

requests.packages.urllib3.disable_warnings()

TEST_START = 0
SUCCESS_STATUSES = {"completed", "complete", "SUCCESS"}


def log(f, msg=""):
    f.write(msg + "\n")
    f.flush()


def progress(service, msg):
    print(f"[{service.upper()}] {msg}", file=sys.stderr, flush=True)


def get_token(base_url, service):
    endpoints = {
        "clinical": f"{base_url}/pdf2abdm/api/token",
        "insurance": f"{base_url}/pdf2nhcx/api/token",
        "privacy": f"{base_url}/privacy-filter/api/demo-token",
        "forgery": f"{base_url}/forgensic/api/token",
    }
    resp = requests.post(
        endpoints[service],
        json={"name": "Concurrency Test", "email": "test@tanuh.ai"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def test_clinical(base_url, token, pdf_path, worker_id):
    global TEST_START
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.time()
    rel_start = t0 - TEST_START

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{base_url}/pdf2abdm/submit", headers=headers,
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                timeout=120,
            )
        r.raise_for_status()
        task_id = r.json().get("task_id")
    except Exception as e:
        return {"worker": worker_id, "task_id": None, "status": f"SUBMIT_ERROR: {e}",
                "submit_time": round(time.time() - t0, 2), "total_time": round(time.time() - t0, 2),
                "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}

    submit_time = time.time() - t0
    status = "timeout"

    for _ in range(400):
        try:
            s = requests.get(f"{base_url}/pdf2abdm/task-status/{task_id}", timeout=30).json()
            status = s.get("status", "")
            if status in ("completed", "failed"):
                break
        except Exception:
            pass
        time.sleep(3)

    return {"worker": worker_id, "task_id": task_id, "status": status,
            "submit_time": round(submit_time, 2), "total_time": round(time.time() - t0, 2),
            "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}


def test_insurance(base_url, token, pdf_path, worker_id):
    global TEST_START
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.time()
    rel_start = t0 - TEST_START

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{base_url}/pdf2nhcx/submit", headers=headers,
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                timeout=120,
            )
        r.raise_for_status()
        task_id = r.json().get("task_id")
    except Exception as e:
        return {"worker": worker_id, "task_id": None, "status": f"SUBMIT_ERROR: {e}",
                "submit_time": round(time.time() - t0, 2), "total_time": round(time.time() - t0, 2),
                "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}

    submit_time = time.time() - t0
    status = "timeout"

    for _ in range(400):
        try:
            s = requests.get(f"{base_url}/pdf2nhcx/task-status/{task_id}", timeout=30).json()
            status = s.get("status", "")
            if status in ("completed", "failed"):
                break
        except Exception:
            pass
        time.sleep(3)

    return {"worker": worker_id, "task_id": task_id, "status": status,
            "submit_time": round(submit_time, 2), "total_time": round(time.time() - t0, 2),
            "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}


def test_privacy(base_url, token, pdf_path, worker_id):
    global TEST_START
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.time()
    rel_start = t0 - TEST_START

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{base_url}/privacy-filter/api/redact", headers=headers,
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                timeout=900,
            )
    except Exception as e:
        return {"worker": worker_id, "status": f"ERROR: {e}", "entities_found": 0,
                "total_time": round(time.time() - t0, 2),
                "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}

    total_time = time.time() - t0
    try:
        data = r.json()
        entity_count = sum(data.get("entity_counts", {}).values())
        status = "SUCCESS"
    except Exception:
        entity_count = 0
        status = f"FAILED({r.status_code})"

    return {"worker": worker_id, "status": status, "entities_found": entity_count,
            "total_time": round(total_time, 2),
            "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}


def test_forgery(base_url, token, pdf_path, worker_id):
    global TEST_START
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.time()
    rel_start = t0 - TEST_START

    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{base_url}/forgensic/jobs", headers=headers,
                files={"file": (os.path.basename(pdf_path), f)},
                data={"ocr_enabled": "false"},
                timeout=120,
            )
        r.raise_for_status()
        job_id = r.json().get("job_id")
    except Exception as e:
        return {"worker": worker_id, "job_id": None, "status": f"SUBMIT_ERROR: {e}",
                "submit_time": round(time.time() - t0, 2), "total_time": round(time.time() - t0, 2),
                "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}

    submit_time = time.time() - t0
    status = "unknown"

    for _ in range(600):
        try:
            s = requests.get(f"{base_url}/forgensic/jobs/{job_id}", headers=headers, timeout=30).json()
            status = s.get("status", "")
            if status in ("complete", "error"):
                break
        except Exception:
            pass
        time.sleep(2)

    return {"worker": worker_id, "job_id": job_id, "status": status,
            "submit_time": round(submit_time, 2), "total_time": round(time.time() - t0, 2),
            "started_at": round(rel_start, 2), "finished_at": round(time.time() - TEST_START, 2)}


def find_test_pdf(service):
    candidates = {
        "clinical": ["frontend/assets/abdm_discharge_summary.pdf", "frontend/assets/abdm_diagnostic_report.pdf"],
        "insurance": ["frontend/assets/nhcx_demo_doc.pdf"],
        "privacy": ["frontend/assets/abdm_discharge_summary.pdf", "frontend/assets/abdm_diagnostic_report.pdf"],
        "forgery": ["frontend/assets/abdm_discharge_summary.pdf", "frontend/assets/abdm_diagnostic_report.pdf"],
    }
    for path in candidates.get(service, []):
        if os.path.exists(path):
            return path
    return None


def write_report(f, service, concurrent, base_url, pdf_path, results, wall_clock):
    sep = "=" * 80

    log(f, sep)
    log(f, f"  DPI CONCURRENCY TEST REPORT — {service.upper()}")
    log(f, sep)
    log(f, f"  Date:             {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f, f"  Base URL:         {base_url}")
    log(f, f"  Concurrent:       {concurrent}")
    log(f, f"  Test PDF:         {pdf_path} ({os.path.getsize(pdf_path) / 1024:.0f} KB)")
    log(f, f"  Wall Clock Total: {wall_clock:.1f}s ({wall_clock/60:.1f} min)")
    log(f, sep)

    successful = [r for r in results if r.get("status") in SUCCESS_STATUSES]
    failed = [r for r in results if r.get("status") not in SUCCESS_STATUSES]

    # ── Per-worker table (by worker ID) ──
    log(f)
    log(f, "-" * 80)
    log(f, "  PER-WORKER RESULTS (sorted by Worker ID)")
    log(f, "-" * 80)
    log(f, f"  {'Worker':>6}  {'Status':>14}  {'Submit(s)':>10}  {'Total(s)':>10}  {'Start@(s)':>10}  {'End@(s)':>10}")
    log(f, f"  {'------':>6}  {'-'*14:>14}  {'-'*10:>10}  {'-'*10:>10}  {'-'*10:>10}  {'-'*10:>10}")

    for r in sorted(results, key=lambda x: x["worker"]):
        sub = f"{r['submit_time']:.1f}" if "submit_time" in r else "—"
        log(f, f"  {r['worker']:>6}  {str(r.get('status','?'))[:14]:>14}  {sub:>10}  "
              f"{r.get('total_time',0):>10.1f}  {r.get('started_at',0):>10.1f}  {r.get('finished_at',0):>10.1f}")

    # ── Per-worker table (by finish time) ──
    log(f)
    log(f, "-" * 80)
    log(f, "  PER-WORKER RESULTS (sorted by Finish Time — shows processing order)")
    log(f, "-" * 80)
    log(f, f"  {'#':>4}  {'Worker':>6}  {'Status':>14}  {'Total(s)':>10}  {'End@(s)':>10}")
    log(f, f"  {'--':>4}  {'------':>6}  {'-'*14:>14}  {'-'*10:>10}  {'-'*10:>10}")

    for i, r in enumerate(sorted(results, key=lambda x: x.get("finished_at", 0)), 1):
        log(f, f"  {i:>4}  {r['worker']:>6}  {str(r.get('status','?'))[:14]:>14}  "
              f"{r.get('total_time',0):>10.1f}  {r.get('finished_at',0):>10.1f}")

    # ── Timing statistics ──
    log(f)
    log(f, sep)
    log(f, "  TIMING STATISTICS")
    log(f, sep)

    submit_times = [r["submit_time"] for r in results if "submit_time" in r and isinstance(r["submit_time"], (int, float))]
    success_times = [r["total_time"] for r in successful if r.get("total_time", 0) > 0]
    all_times = [r["total_time"] for r in results if r.get("total_time", 0) > 0]

    if submit_times:
        log(f)
        log(f, "  Submit Phase (time to upload PDF and receive task_id):")
        log(f, f"    Min:      {min(submit_times):.2f}s")
        log(f, f"    Max:      {max(submit_times):.2f}s")
        log(f, f"    Average:  {statistics.mean(submit_times):.2f}s")
        if len(submit_times) >= 2:
            log(f, f"    Median:   {statistics.median(submit_times):.2f}s")
            log(f, f"    Std Dev:  {statistics.stdev(submit_times):.2f}s")

    if success_times:
        log(f)
        log(f, "  End-to-End (successful requests — submit + queue wait + processing):")
        log(f, f"    Min:      {min(success_times):.1f}s")
        log(f, f"    Max:      {max(success_times):.1f}s")
        log(f, f"    Average:  {statistics.mean(success_times):.1f}s")
        if len(success_times) >= 2:
            log(f, f"    Median:   {statistics.median(success_times):.1f}s")
            log(f, f"    Std Dev:  {statistics.stdev(success_times):.1f}s")
            s = sorted(success_times)
            log(f, f"    P90:      {s[int(len(s)*0.90)]:.1f}s")
            log(f, f"    P95:      {s[int(len(s)*0.95)]:.1f}s")
            log(f, f"    P99:      {s[min(int(len(s)*0.99), len(s)-1)]:.1f}s")

    if all_times and len(all_times) != len(success_times):
        log(f)
        log(f, "  All Requests (including failures):")
        log(f, f"    Min:      {min(all_times):.1f}s")
        log(f, f"    Max:      {max(all_times):.1f}s")
        log(f, f"    Average:  {statistics.mean(all_times):.1f}s")

    # ── Concurrency analysis ──
    log(f)
    log(f, sep)
    log(f, "  CONCURRENCY ANALYSIS")
    log(f, sep)
    log(f, f"  Total requests sent:    {len(results)}")
    log(f, f"  Successful:             {len(successful)}")
    log(f, f"  Failed:                 {len(failed)}")
    log(f, f"  Success rate:           {len(successful)/len(results)*100:.1f}%")
    log(f, f"  Wall clock time:        {wall_clock:.1f}s ({wall_clock/60:.1f} min)")

    if successful and wall_clock > 0:
        throughput = len(successful) / wall_clock
        log(f, f"  Throughput:             {throughput:.3f} docs/sec ({throughput*60:.1f} docs/min)")

        if success_times:
            sum_t = sum(success_times)
            eff_parallel = sum_t / wall_clock
            log(f, f"  Effective parallelism:  {eff_parallel:.1f}")
            log(f, f"    (= sum of all processing times / wall clock)")
            log(f, f"    (1.0 = fully sequential, 8.0 = 8 workers truly parallel)")

            if len(success_times) >= 2:
                single_doc_avg = statistics.mean(success_times[:8]) if len(success_times) >= 8 else statistics.mean(success_times)
                ideal_sequential = single_doc_avg * len(successful)
                speedup = ideal_sequential / wall_clock
                log(f, f"  Speedup vs sequential: {speedup:.1f}x")
                log(f, f"    (if processed one-by-one it would take ~{ideal_sequential:.0f}s = {ideal_sequential/60:.0f} min)")

    # ── Batch analysis ──
    log(f)
    log(f, sep)
    log(f, "  BATCH ANALYSIS")
    log(f, "  Workers finishing within 20s of each other were likely processed in parallel.")
    log(f, sep)

    if successful:
        sorted_s = sorted(successful, key=lambda r: r.get("finished_at", 0))
        batches = [[sorted_s[0]]]

        for r in sorted_s[1:]:
            if r.get("finished_at", 0) - batches[-1][0].get("finished_at", 0) <= 20:
                batches[-1].append(r)
            else:
                batches.append([r])

        for i, batch in enumerate(batches, 1):
            t_min = min(r.get("finished_at", 0) for r in batch)
            t_max = max(r.get("finished_at", 0) for r in batch)
            wids = sorted(r["worker"] for r in batch)
            if len(wids) <= 10:
                ids_str = ", ".join(str(w) for w in wids)
            else:
                ids_str = f"{', '.join(str(w) for w in wids[:4])}, ..., {', '.join(str(w) for w in wids[-2:])}"
            log(f, f"  Batch {i:3d}  |  @{t_min:7.1f}s - {t_max:7.1f}s  |  {len(batch):3d} parallel  |  workers [{ids_str}]")

        log(f)
        batch_sizes = [len(b) for b in batches]
        log(f, f"  Total batches:         {len(batches)}")
        log(f, f"  Avg batch size:        {statistics.mean(batch_sizes):.1f}")
        log(f, f"  Max batch size:        {max(batch_sizes)} (= max observed parallelism)")
        log(f, f"  Min batch size:        {min(batch_sizes)}")

    # ── Failure details ──
    if failed:
        log(f)
        log(f, sep)
        log(f, "  FAILED REQUESTS")
        log(f, sep)
        status_counts = {}
        for r in failed:
            s = str(r.get("status", "unknown"))
            status_counts[s] = status_counts.get(s, 0) + 1
        log(f, "  Failure breakdown:")
        for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
            log(f, f"    {s}: {c}")
        log(f)
        for r in sorted(failed, key=lambda x: x["worker"]):
            log(f, f"  Worker {r['worker']:3d}: {str(r.get('status','unknown'))[:40]}  ({r.get('total_time',0):.1f}s)")

    log(f)
    log(f, sep)
    log(f, "  END OF REPORT")
    log(f, sep)


def main():
    global TEST_START

    parser = argparse.ArgumentParser(description="DPI Concurrency Tester")
    parser.add_argument("--service", required=True, choices=["clinical", "insurance", "privacy", "forgery"])
    parser.add_argument("--concurrent", type=int, default=3)
    parser.add_argument("--base-url", default="https://dpi-dev.tanuh.ai")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--output", default=None, help="Output report file path")
    args = parser.parse_args()

    pdf_path = args.pdf or find_test_pdf(args.service)
    if not pdf_path or not os.path.exists(pdf_path):
        print("ERROR: No test PDF found. Provide one with --pdf /path/to/file.pdf", file=sys.stderr)
        sys.exit(1)

    test_fn = {"clinical": test_clinical, "insurance": test_insurance,
               "privacy": test_privacy, "forgery": test_forgery}[args.service]

    output_file = args.output or f"concurrency_{args.service}_{args.concurrent}.txt"

    progress(args.service, f"Starting {args.concurrent}-concurrent test → {output_file}")
    progress(args.service, f"PDF: {pdf_path} ({os.path.getsize(pdf_path)/1024:.0f} KB)")
    progress(args.service, "Getting token...")
    token = get_token(args.base_url, args.service)
    progress(args.service, f"Token OK. Launching {args.concurrent} workers...")

    TEST_START = time.time()
    results = []
    done = 0

    with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
        futures = {pool.submit(test_fn, args.base_url, token, pdf_path, i+1): i+1
                   for i in range(args.concurrent)}

        for future in as_completed(futures):
            wid = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append({"worker": wid, "status": f"EXCEPTION: {e}",
                                "total_time": 0, "started_at": 0,
                                "finished_at": time.time() - TEST_START})
            done += 1
            if done % 10 == 0 or done == args.concurrent:
                progress(args.service, f"{done}/{args.concurrent} completed")

    wall_clock = time.time() - TEST_START

    with open(output_file, "w") as f:
        write_report(f, args.service, args.concurrent, args.base_url, pdf_path, results, wall_clock)

    successful = [r for r in results if r.get("status") in SUCCESS_STATUSES]
    progress(args.service, f"DONE — {len(successful)}/{len(results)} successful in {wall_clock:.1f}s ({wall_clock/60:.1f} min)")
    progress(args.service, f"Report saved: {output_file}")


if __name__ == "__main__":
    main()
