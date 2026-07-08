#!/usr/bin/env python
"""
Diagnostic script for the ChanLun (CL) pipeline.

Fetches K-line data using the same exchange the web app uses, then runs the full
CL pipeline step by step, reporting detailed diagnostics at each stage to identify
why certain stocks (e.g., 300491.SZ) or frequencies (minute charts) produce no CL data.

Modes:
  --mode direct    : Bypass caching, run pipeline step by step (default)
  --mode web       : Replicate the exact web-app flow through FileCacheDB

Usage:
    python tests/diagnose_cl_pipeline.py --code SZ.300491 --freq 5m
    python tests/diagnose_cl_pipeline.py --code 300491 --freq all
    python tests/diagnose_cl_pipeline.py --code SZ.300491 --freq 1m,5m,30m,d
    python tests/diagnose_cl_pipeline.py --code SZ.300491 --freq all --mode web
"""

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import sys
import traceback
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Ensure the src directory is on the path
sys.path.insert(0, "src")

from chanlun import fun
from chanlun.cl import CL
from chanlun.cl_interface import Config, ICL
from chanlun.cl_utils import (
    query_cl_chart_config,
    web_batch_get_cl_datas,
    cl_data_to_tv_chart,
)
from chanlun.exchange import get_exchange, Market
from chanlun.file_db import FileCacheDB
from chanlun.get_src_klines import convert_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process
from chanlun.get_xd import XD_Process
from chanlun.get_zs import create_dn_zs as create_dn_zs_fn


# ── helpers ──────────────────────────────────────────────────────────────


def _fmt_num(n: int) -> str:
    return f"{n}" if n > 0 else "⚠ 0"


def _red(s: str) -> str:
    return f"\033[91m{s}\033[0m"


def _green(s: str) -> str:
    return f"\033[92m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[93m{s}\033[0m"


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


def normalize_code(code: str) -> str:
    """Ensure code has SH./SZ. prefix. 300xxx → SZ, 600xxx → SH."""
    if "." in code:
        return code.upper()
    code = code.strip().upper()
    if code.startswith("6") or code.startswith("5"):
        return f"SH.{code}"
    return f"SZ.{code}"


THE_FREQUENCIES = ["d", "w", "120m", "60m", "30m", "15m", "10m", "5m", "2m", "1m"]


# ── diagnostics: direct mode (bypass cache) ───────────────────────────────


def diagnose_direct(
    market: str,
    code: str,
    frequencies: List[str],
) -> Dict[str, dict]:
    """
    Run the CL pipeline for each frequency, bypassing FileCacheDB.
    Tests each stage individually.
    """
    results: Dict[str, dict] = {}

    print(f"\n{_bold('Exchange Setup')}")
    print(f"  Market: {market}")
    print(f"  Code:   {code}")
    try:
        ex = get_exchange(Market(market))
        print(f"  {_green('exchange OK')}: {type(ex).__name__}")
    except Exception as e:
        print(f"  {_red('exchange FAILED')}: {e}")
        return results

    # Get CL config — same as the web app
    cl_config = query_cl_chart_config(market, code)
    if cl_config is None:
        cl_config = {}

    for freq in frequencies:
        divider = "─" * 70
        print(f"\n{divider}")
        print(f"{_bold('Frequency')}: {freq}")
        print(f"{divider}")

        result: dict = {
            "kline_count": 0,
            "cl_kline_count": 0,
            "fx_count": 0,
            "bi_count": 0,
            "xd_count": 0,
            "bi_zs_count": 0,
            "xd_zs_count": 0,
            "error": None,
            "done_bis": 0,
            "done_xds": 0,
        }
        results[freq] = result

        # ── Step 1: Fetch K-line data ─────────────────────────────────
        try:
            klines: pd.DataFrame = ex.klines(code, freq)
        except Exception as e:
            result["error"] = f"klines fetch: {e}"
            print(f"  {_red('Step 1 FAIL')}: fetch klines — {e}")
            continue

        if klines is None or len(klines) == 0:
            result["error"] = "klines returned empty/None"
            print(f"  {_red('Step 1 FAIL')}: klines is empty or None")
            continue

        result["kline_count"] = len(klines)
        dt_from = klines.iloc[0]["date"]
        dt_to = klines.iloc[-1]["date"]
        price_hi = klines["high"].max()
        price_lo = klines["low"].min()
        price_last = klines.iloc[-1]["close"]
        print(f"  Step 1 [K-lines]    : {_fmt_num(len(klines))} rows")
        print(f"    range : {dt_from}  →  {dt_to}")
        print(f"    price : {price_lo:.2f} – {price_hi:.2f}  (last close {price_last:.2f})")

        # ── Step 2: Convert source klines ─────────────────────────────
        try:
            if "high" in klines.columns:
                src_klines = convert_src_klines(klines)
            else:
                src_klines = klines
            print(f"  Step 2 [convert]   : {len(src_klines)} rows (same format as process_klines receives)")
        except Exception as e:
            result["error"] = f"convert_src_klines: {e}"
            print(f"  {_red('Step 2 FAIL')}: convert_src_klines — {e}")
            traceback.print_exc()
            continue

        # ── Step 3: CL K-lines (containment processing) ───────────────
        try:
            cl_klines = get_cl_lines(src_klines, config=cl_config)
            result["cl_kline_count"] = len(cl_klines)
            if len(cl_klines) == 0:
                print(f"  {_red('Step 3 FAIL')}: get_cl_lines → 0 CLKlines (all contained?)")
                continue
            cl_ratio = len(cl_klines) / max(len(src_klines), 1)
            flag = _green if cl_ratio >= 0.3 else _yellow if cl_ratio >= 0.1 else _red
            print(f"  Step 3 [CL-klines] : {_fmt_num(len(cl_klines))} rows  (ratio {cl_ratio:.2%}) {flag('')}")
        except Exception as e:
            result["error"] = f"get_cl_lines: {e}"
            print(f"  {_red('Step 3 FAIL')}: get_cl_lines — {e}")
            traceback.print_exc()
            continue

        # ── Step 4: FX (分型) ─────────────────────────────────────────
        try:
            fx_proc = FX_PROCESS(config=cl_config)
            fxs = fx_proc.find_fenxing(cl_klines)
            result["fx_count"] = len(fxs)
            if len(fxs) == 0:
                print(f"  {_red('Step 4 FAIL')}: find_fenxing → 0 FXs")
                report_fx_diagnostic_direct(cl_klines, cl_config)
                continue
            tops = sum(1 for f in fxs if f.type in ("top", "verify_top", "failure_top"))
            bots = sum(1 for f in fxs if f.type in ("bottom", "verify_bottom", "failure_bottom"))
            print(f"  Step 4 [FX / 分型]  : {_fmt_num(len(fxs))}  (tops={tops}, bots={bots})")
        except Exception as e:
            result["error"] = f"find_fenxing: {e}"
            print(f"  {_red('Step 4 FAIL')}: find_fenxing — {e}")
            traceback.print_exc()
            continue

        # ── Step 5: BI (笔) ───────────────────────────────────────────
        try:
            bi_proc = BI_Process(config=cl_config)
            bis = bi_proc.handle(fxs)
            result["bi_count"] = len(bis)
            if len(bis) == 0:
                print(f"  {_red('Step 5 FAIL')}: BI_Process → 0 BIs")
                report_bi_diagnostic_direct(fxs, cl_config)
                continue
            ups = sum(1 for b in bis if b.type in ("up", "verify_up"))
            downs = sum(1 for b in bis if b.type in ("down", "verify_down"))
            done = sum(1 for b in bis if b.is_done())
            result["done_bis"] = done
            print(f"  Step 5 [BI / 笔]    : {_fmt_num(len(bis))}  (up={ups}, down={downs}, done={done})")
        except Exception as e:
            result["error"] = f"BI_Process: {e}"
            print(f"  {_red('Step 5 FAIL')}: BI_Process — {e}")
            traceback.print_exc()
            continue

        # ── Step 6: XD (线段) ─────────────────────────────────────────
        try:
            xd_proc = XD_Process(config=cl_config)
            xds = xd_proc.handle(bis)
            result["xd_count"] = len(xds)
            if len(xds) == 0:
                print(f"  {_red('Step 6 FAIL')}: XD_Process → 0 XDs")
                report_xd_diagnostic_direct(bis, cl_config)
                continue
            ups = sum(1 for x in xds if x.type in ("up", "verify_up"))
            downs = sum(1 for x in xds if x.type in ("down", "verify_down"))
            done = sum(1 for x in xds if x.is_done())
            result["done_xds"] = done
            print(f"  Step 6 [XD / 线段]  : {_fmt_num(len(xds))}  (up={ups}, down={downs}, done={done})")
        except Exception as e:
            result["error"] = f"XD_Process: {e}"
            print(f"  {_red('Step 6 FAIL')}: XD_Process — {e}")
            traceback.print_exc()
            continue

        # ── Step 7: ZS (中枢) ─────────────────────────────────────────
        try:
            bi_zss = create_dn_zs_fn("bi", bis, config=cl_config)
            result["bi_zs_count"] = len(bi_zss)
            xd_zss = create_dn_zs_fn("xd", xds, config=cl_config)
            result["xd_zs_count"] = len(xd_zss)
            if len(bi_zss) == 0 and len(xd_zss) == 0:
                print(f"  {_yellow('Step 7 WARN')}: ZS → 0 bi_zss, 0 xd_zss (may be OK for short data)")
            else:
                print(f"  Step 7 [ZS / 中枢]  : bi_zs={_fmt_num(len(bi_zss))},  xd_zs={_fmt_num(len(xd_zss))}")
        except Exception as e:
            result["error"] = f"create_dn_zs: {e}"
            print(f"  {_red('Step 7 FAIL')}: create_dn_zs — {e}")
            traceback.print_exc()
            continue

        # ── Step 8: Full pipeline via process_klines (integration test)
        try:
            cd = CL(code, freq, cl_config)
            cd.process_klines(klines)
            tv = {
                "bis": len(cd.get_bis()),
                "xds": len(cd.get_xds()),
                "fxs": len(cd.get_fxs()),
                "bi_zss": len(cd.get_bi_zss()),
                "xd_zss": len(cd.get_xd_zss()),
            }
            all_ok = all(v > 0 for v in tv.values())
            flag8 = _green if all_ok else _yellow
            print(f"  Step 8 [Full pipeline]: bis={_fmt_num(tv['bis'])}, xds={_fmt_num(tv['xds'])}, "
                  f"fxs={_fmt_num(tv['fxs'])}, bi_zss={_fmt_num(tv['bi_zss'])}, xd_zss={_fmt_num(tv['xd_zss'])} {flag8('')}")
        except Exception as e:
            result["error"] = result.get("error") or f"process_klines: {e}"
            print(f"  {_red('Step 8 FAIL')}: process_klines — {e}")
            traceback.print_exc()

        print(f"\n  {_green('✓ Done')} {freq}")

    return results


# ── diagnostics: web replica mode (through FileCacheDB) ───────────────────


def diagnose_web(
    market: str,
    code: str,
    frequencies: List[str],
) -> Dict[str, dict]:
    """
    Replicate the exact web-app flow:
    1. ex.klines() → raw data
    2. web_batch_get_cl_datas() → FileCacheDB.get_web_cl_data() → CL.process_klines()
    3. cl_data_to_tv_chart() → JSON
    """
    results: Dict[str, dict] = {}

    print(f"\n{_bold('Exchange Setup')}")
    print(f"  Market: {market}")
    print(f"  Code:   {code}")
    try:
        ex = get_exchange(Market(market))
        print(f"  {_green('exchange OK')}: {type(ex).__name__}")
    except Exception as e:
        print(f"  {_red('exchange FAILED')}: {e}")
        return results

    cl_config = query_cl_chart_config(market, code)
    if cl_config is None:
        cl_config = {}

    for freq in frequencies:
        divider = "─" * 70
        print(f"\n{divider}")
        print(f"{_bold('Frequency')}: {freq}")
        print(f"{divider}")

        result: dict = {
            "kline_count": 0,
            "bi_count": 0,
            "xd_count": 0,
            "fxs_count": 0,
            "bi_zs_count": 0,
            "xd_zs_count": 0,
            "bi_zs_dn_count": 0,
            "xd_zs_dn_count": 0,
            "tv_has_bis": False,
            "tv_has_xds": False,
            "tv_has_zs": False,
            "tv_has_mmds": False,
            "tv_has_bcs": False,
            "error": None,
        }
        results[freq] = result

        # ── Step W1: Fetch K-line data ───────────────────────────────
        try:
            klines: pd.DataFrame = ex.klines(code, freq)
        except Exception as e:
            result["error"] = f"klines fetch: {e}"
            print(f"  {_red('Step W1 FAIL')}: fetch klines — {e}")
            continue

        if klines is None or len(klines) == 0:
            result["error"] = "klines returned empty/None"
            print(f"  {_red('Step W1 FAIL')}: klines is empty or None")
            continue

        result["kline_count"] = len(klines)
        dt_from = klines.iloc[0]["date"]
        dt_to = klines.iloc[-1]["date"]
        print(f"  Step W1 [K-lines] : {_fmt_num(len(klines))} rows  ({dt_from} → {dt_to})")

        # ── Step W2: web_batch_get_cl_datas (FileCacheDB flow) ────────
        try:
            klines_dict = {freq: klines}
            cd_list = web_batch_get_cl_datas(market, code, klines_dict, cl_config)
            cd: ICL = cd_list[0]
        except Exception as e:
            result["error"] = f"web_batch_get_cl_datas: {e}"
            print(f"  {_red('Step W2 FAIL')}: web_batch_get_cl_datas — {e}")
            traceback.print_exc()
            continue

        # Inspect computed CL data
        bis = cd.get_bis()
        xds = cd.get_xds()
        fxs = cd.get_fxs()
        bi_zss = cd.get_bi_zss()
        xd_zss = cd.get_xd_zss()

        result["bi_count"] = len(bis)
        result["xd_count"] = len(xds)
        result["fxs_count"] = len(fxs)
        result["bi_zs_count"] = len(cd.get_bi_zss())
        result["xd_zs_count"] = len(cd.get_xd_zss())
        result["bi_zs_dn_count"] = len(cd.get_bi_zss("dn"))
        result["xd_zs_dn_count"] = len(cd.get_xd_zss("dn"))

        print(f"  Step W2 [CL compute] : bis={_fmt_num(len(bis))}, xds={_fmt_num(len(xds))}, "
              f"fxs={_fmt_num(len(fxs))}, bi_zss={len(bi_zss)}, xd_zss={len(xd_zss)}")
        print(f"    bi_zss(dn)={len(cd.get_bi_zss('dn'))}, xd_zss(dn)={len(cd.get_xd_zss('dn'))}")

        if len(bis) > 0:
            done_bis = sum(1 for b in bis if b.is_done())
            up_bis = sum(1 for b in bis if b.type in ("up", "verify_up"))
            print(f"    BIs: done={done_bis}, up={up_bis}, down={len(bis)-up_bis}")
            print(f"    First BI: {bis[0]}")
            print(f"    Last BI : {bis[-1]}")
        if len(xds) > 0:
            done_xds = sum(1 for x in xds if x.is_done())
            up_xds = sum(1 for x in xds if x.type in ("up", "verify_up"))
            print(f"    XDs: done={done_xds}, up={up_xds}, down={len(xds)-up_xds}")
            print(f"    First XD: {xds[0]}")
            print(f"    Last XD : {xds[-1]}")

        # ── Step W3: cl_data_to_tv_chart (serialize) ──────────────────
        try:
            tv_chart = cl_data_to_tv_chart(cd, cl_config, to_frequency=None)
        except Exception as e:
            result["error"] = f"cl_data_to_tv_chart: {e}"
            print(f"  {_red('Step W3 FAIL')}: cl_data_to_tv_chart — {e}")
            traceback.print_exc()
            continue

        result["tv_has_bis"] = len(tv_chart.get("bis", [])) > 0
        result["tv_has_xds"] = len(tv_chart.get("xds", [])) > 0
        result["tv_has_zs"] = (len(tv_chart.get("bi_zss", [])) > 0 or len(tv_chart.get("xd_zss", [])) > 0)
        result["tv_has_mmds"] = len(tv_chart.get("mmds", [])) > 0
        result["tv_has_bcs"] = len(tv_chart.get("bcs", [])) > 0

        # Validate TV chart output
        tv_t = tv_chart.get("t", [])
        print(f"  Step W3 [TV chart]  : t={len(tv_t)}, c={len(tv_chart.get('c',[]))}")
        print(f"    fxs={len(tv_chart.get('fxs',[]))}, bis={len(tv_chart.get('bis',[]))}, "
              f"xds={len(tv_chart.get('xds',[]))}, zsds={len(tv_chart.get('zsds',[]))}")
        print(f"    bi_zss={len(tv_chart.get('bi_zss',[]))}, xd_zss={len(tv_chart.get('xd_zss',[]))}, "
              f"zsd_zss={len(tv_chart.get('zsd_zss',[]))}")
        print(f"    bcs={len(tv_chart.get('bcs',[]))}, mmds={len(tv_chart.get('mmds',[]))}")

        # Check if the TV output would actually render anything
        has_content = (
            result["tv_has_bis"]
            or result["tv_has_xds"]
            or result["tv_has_zs"]
            or result["tv_has_mmds"]
            or result["tv_has_bcs"]
            or len(tv_t) > 0
        )
        if has_content:
            print(f"  {_green('Step W3 OK')}: TV chart has content to render")
        else:
            print(f"  {_red('Step W3 EMPTY')}: TV chart has NO content (no overlays + no K-lines)")
            result["error"] = "TV chart empty: no overlays and no K-lines"

        # ── Step W4: Inspect cache file ───────────────────────────────
        print_cache_info(market, code, freq, cl_config)

        print(f"\n  {_green('✓ Done')} {freq}")

    return results


def print_cache_info(market: str, code: str, frequency: str, cl_config: dict):
    """Print information about the cached CL data file."""
    fdb = FileCacheDB()
    config_keys = fdb.config_keys
    unique_md5_str = (
        f'{[f"{k}:{v}" for k, v in cl_config.items() if k in config_keys]}'
    )
    key = hashlib.md5(unique_md5_str.encode("UTF-8")).hexdigest()
    cache_path = (
        fdb.cl_data_path
        / f"{market}_{code.replace('/', '_').replace('.', '_')}_{frequency}_{key}.pkl"
    )

    print(f"  Step W4 [Cache]     :")
    print(f"    MD5 key: {key}")
    if cache_path.exists():
        st = cache_path.stat()
        print(f"    File  : {cache_path}")
        print(f"    Size  : {st.st_size:,} bytes")
        print(f"    Mtime : {datetime.datetime.fromtimestamp(st.st_mtime)}")
        # Try to peek at pickle contents
        try:
            import pickle
            with open(cache_path, "rb") as fp:
                cd = pickle.load(fp)
            print(f"    Type  : {type(cd).__name__}")
            print(f"    Version: {getattr(cd, '_pickle_version', 'N/A')}")
            src_k = cd.get_src_klines()
            k_count = len(src_k) if hasattr(src_k, '__len__') else '?'
            print(f"    K-lines: {k_count}")
            print(f"    BIs    : {len(cd.get_bis())}")
            print(f"    XDs    : {len(cd.get_xds())}")
        except Exception as e:
            print(f"    {_yellow('peek failed')}: {e}")
    else:
        print(f"    {_yellow('No cache file')}: {cache_path}")


# ── failure diagnostics (direct mode) ─────────────────────────────────────


def report_fx_diagnostic_direct(cl_klines, config):
    """When FX detection produces 0 results, report why."""
    n = len(cl_klines)
    if n < 3:
        print(f"    {_red('Root cause')}: only {n} CLKlines — need ≥ 3 to form a 分型 (left/middle/right)")
        return

    fx_bh = config.get("fx_bh", "FX_BH_DINGDI")
    potential_tops = 0
    potential_bots = 0
    for i in range(1, n - 1):
        left, mid, right = cl_klines.iloc[i - 1], cl_klines.iloc[i], cl_klines.iloc[i + 1]
        is_top = mid.h > left.h and mid.h >= right.h
        is_bot = mid.l < left.l and mid.l <= right.l
        if is_top:
            potential_tops += 1
        if is_bot:
            potential_bots += 1

    print(f"    CLKlines count: {n}")
    print(f"    Potential TOP patterns (before BH validation): {potential_tops}")
    print(f"    Potential BOTTOM patterns: {potential_bots}")
    print(f"    fx_bh config: {fx_bh}")
    print(f"    {_yellow('Suggestion')}: With {n} CLKlines, need sufficient price swings to form 分型 patterns.")


def report_bi_diagnostic_direct(fxs, config):
    """When BI detection produces 0 results, report why."""
    n = len(fxs)
    if n < 2:
        print(f"    {_red('Root cause')}: only {n} FXs — need ≥ 2 to form a 笔")
        return

    min_kline = config.get("BI_MIN_KLINE_COUNT", 5)
    min_amp = config.get("BI_MIN_AMPLITUDE", 0.001)

    valid_pairs = 0
    for i in range(len(fxs) - 1):
        f1, f2 = fxs[i], fxs[i + 1]
        t1_dir = "top" if f1.type in ("top", "verify_top", "failure_top") else "bottom"
        t2_dir = "top" if f2.type in ("top", "verify_top", "failure_top") else "bottom"
        if t1_dir == t2_dir:
            continue
        k_count = f2.k.k_index - f1.k.k_index
        amp = abs(f2.val - f1.val) / max(abs(f1.val), 1e-8)
        if k_count >= min_kline and amp >= min_amp:
            valid_pairs += 1

    print(f"    FX count: {n}")
    print(f"    Valid TOP-BOTTOM pairs (k≥{min_kline}, amp≥{min_amp*100:.1f}%): {valid_pairs}")
    if valid_pairs == 0 and n >= 2:
        print(f"    {_yellow('Potential reasons')}:")
        for i in range(min(n - 1, 10)):
            f1, f2 = fxs[i], fxs[i + 1]
            k_count = f2.k.k_index - f1.k.k_index
            amp = abs(f2.val - f1.val) / max(abs(f1.val), 1e-8)
            note = ""
            if k_count < min_kline:
                note += f" K-count={k_count}<{min_kline}"
            if amp < min_amp:
                note += f" amp={amp:.4%}<{min_amp*100:.1f}%"
            if note:
                print(f"      Pair {i}: {f1.type}→{f2.type}{note}")


def report_xd_diagnostic_direct(bis, config):
    """When XD detection produces 0 results, report why."""
    n = len(bis)
    if n < 3:
        print(f"    {_red('Root cause')}: only {n} BIs — XD_Process needs ≥ 3 BIs to form an 线段")
        return

    ups = sum(1 for b in bis if b.type in ("up", "verify_up"))
    downs = sum(1 for b in bis if b.type in ("down", "verify_down"))
    print(f"    BI count: {n} (up={ups}, down={downs})")
    print(f"    {_yellow('Likely cause')}: XD processing state machine needs sufficient alternating BIs with proper feature sequences.")


# ── summary ───────────────────────────────────────────────────────────────


def print_summary(results: Dict[str, dict], guard_results: Dict[str, dict] = None):
    print(f"\n\n{_bold('═' * 70)}")
    print(f"{_bold('SUMMARY')}")
    print(f"{_bold('═' * 70)}")

    col_w = max(10, max((len(f) for f in results.keys()), default=10))
    header = (
        f"  {'Freq':<{col_w}}  {'Klines':>7}  {'CL-K':>6}  {'FX':>5}  {'BI':>5}  {'XD':>5}  "
        f"{'ZS(BI/XD)':>12}  {'Status':>12}"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    for freq, r in results.items():
        zs_info = f"{r.get('bi_zs_count',0)}/{r.get('xd_zs_count',0)}"
        if r.get("error"):
            status = _red("FAIL")
            status_info = f"[{r.get('error', '?')}]"
        elif r.get("bi_count", 0) == 0 and r.get("xd_count", 0) == 0:
            status = _red("NO CL DATA")
            status_info = "no BIs or XDs"
        elif r.get("bi_count", 0) > 0 and r.get("xd_count", 0) == 0:
            status = _yellow("BI ONLY")
            status_info = "has BIs, no XDs"
        else:
            status = _green("OK")
            status_info = "pipeline OK"

        cl_k = r.get("cl_kline_count", "-")
        print(
            f"  {freq:<{col_w}}  {r.get('kline_count',0):>7}  {cl_k:>6}  "
            f"{r.get('fx_count',0):>5}  {r.get('bi_count',0):>5}  {r.get('xd_count',0):>5}  "
            f"{zs_info:>12}  {status:<12} {status_info}"
        )

    # Key findings
    failed = [f for f, r in results.items() if r.get("error") or (r.get("bi_count", 0) == 0 and r.get("xd_count", 0) == 0)]
    working = [f for f, r in results.items() if not r.get("error") and (r.get("bi_count", 0) > 0 or r.get("xd_count", 0) > 0)]

    print(f"\n{_bold('Key Findings')}:")
    if failed:
        print(f"  Failing frequencies: {', '.join(failed)}")
        for f in failed:
            r = results[f]
            if r.get("error"):
                print(f"    {f}: error → {r['error']}")
            elif r.get("kline_count", 0) == 0:
                print(f"    {f}: no K-line data returned")
            elif r.get("cl_kline_count", 0) == 0:
                print(f"    {f}: all K-lines contained → 0 CLKlines")
            elif r.get("fx_count", 0) == 0:
                print(f"    {f}: no FX → check price swings and fx_bh config")
            elif r.get("bi_count", 0) == 0:
                print(f"    {f}: no BIs → check FX count, BI_MIN_KLINE_COUNT, BI_MIN_AMPLITUDE")
            elif r.get("xd_count", 0) == 0:
                print(f"    {f}: no XDs → check BI count and XD state machine")
    if working:
        print(f"  Working frequencies: {', '.join(working)}")

    # Guard verification summary
    if guard_results:
        print(f"\n{_bold('Guard Verification')}:")
        guard2 = guard_results.get("guard_2", [])
        blocked_cbs = [g["countback"] for g in guard2 if g["blocked"]]
        passed_cbs = [g["countback"] for g in guard2 if not g["blocked"]]
        print(f"  Verified: ex.now_trading() real call → {_green('OK')}")
        print(f"  Guard #2 results (views_tv.py:183-186):")
        print(f"    BLOCKED countbacks: {blocked_cbs} → {json.dumps({'s': 'no_data', 'errmsg': '非交易时间'})}")
        print(f"    PASS countbacks   : {passed_cbs} → fetches klines + CL data")
        tdx_ok = guard_results.get("tdx_ok", False)
        print(f"  TDX connectivity    : {_green('OK') if tdx_ok else _red('FAILED')}")
        verdict = guard_results.get("verdict", "")
        if verdict == "blocked":
            print(f"  {_red('VERDICT: Web app guards WILL block. CL pipeline never reached.')}")
        elif verdict == "ok":
            print(f"  {_green('VERDICT: Guards pass. Check pipeline diagnostics below.')}")


# ── web app guard simulation ──────────────────────────────────────────────


def simulate_web_app_guards(ex, code: str, frequencies: List[str]) -> Dict[str, dict]:
    """
    Execute the EXACT guard logic from views_tv.py:history() using the real
    exchange object (same ExchangeTDX instance the web app uses).

    NOTE: Importing views_tv.py directly is not feasible because it's a Django
    view module that requires DATABASES, INSTALLED_APPS, middleware, and URL
    routing to be configured. However, the guard functions it calls ARE
    available and exercised here:

      Guard #1 (views_tv.py:170-174):  int(_to) < old_k_time
        → Uses real ex.klines() to get actual K-line timestamps
        → Tests the exact same integer comparison

      Guard #2 (views_tv.py:183-186):  ex.now_trading() is False and countback < 5
        → Calls ex.now_trading() — same ExchangeTDX.now_trading() method
        → Tests the exact same boolean/integer condition

    Returns a dict with verification results:
      { "guard_1": [...], "guard_2": [...], "verdict": "...", "tdx_ok": bool }
    """
    results: Dict[str, dict] = {"guard_1": [], "guard_2": [], "verdict": "", "tdx_ok": False}

    print(f"\n{_bold('Web App Guard Simulation')}")
    print(f"  Source: views_tv.py:161-200 (history())")
    print(f"  Evidence: Real ExchangeTDX.now_trading() + real K-line timestamps")
    print(f"{'=' * 70}")

    now = datetime.datetime.now()
    now_int = fun.datetime_to_int(now)
    is_trading = ex.now_trading()  # ← REAL FUNCTION CALL (exchange_tdx.py:307)
    weekday = now.weekday()
    weekday_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][weekday]

    print(f"\n{_bold('Context')}:")
    print(f"  Current time    : {now} ({weekday_name})")
    print(f"  VERIFIED: ex.now_trading() → {is_trading}  [exchange_tdx.py:307, called by views_tv.py:183]")
    print(f"  now_int         : {now_int}")

    # Fetch actual data to get realistic timestamps for Guard #1 simulation
    actual_ranges = {}
    for freq in frequencies[:2]:
        try:
            klines = ex.klines(code, freq)
            if klines is not None and len(klines) > 0:
                first_dt = klines.iloc[0]["date"]
                last_dt = klines.iloc[-1]["date"]
                actual_ranges[freq] = {
                    "_from": fun.datetime_to_int(first_dt),
                    "_to": fun.datetime_to_int(last_dt),
                    "count": len(klines),
                }
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════
    # Guard #1 — load_old_kline_times cache (views_tv.py:164-174)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{_bold('Guard #1 — load_old_kline_times (views_tv.py:164-174)')}")
    print(f"  Exact code from views_tv.py:")
    print(f'    _symbol_res_old_k_time_key = f"{{symbol}}_{{resolution}}"')
    print(f'    if _symbol_res_old_k_time_key in load_old_kline_times.keys():')
    print(f'        old_k_time = load_old_kline_times[_symbol_res_old_k_time_key]')
    print(f'    if int(_to) < old_k_time:')
    print(f'        return {{"s": "no_data", "errmsg": "不支持历史数据加载", "nextTime": now_time + 3}}')
    print(f"")

    guard1_results = []
    for freq, info in actual_ranges.items():
        first_k_time = info["_from"]
        last_k_time = info["_to"]
        # After initial load, views_tv.py:209 sets old_k_time = first bar's time
        old_k_time = first_k_time
        symbol_key = f"a:{code}_{freq}"

        scenarios = [
            ("latest bar", last_k_time),
            ("1/4 into history", first_k_time + (last_k_time - first_k_time) // 4),
            ("before first bar", first_k_time - 86400),
        ]

        print(f"  {freq}: initial load sets old_k_time = {first_k_time}")
        print(f"    ({symbol_key})")
        for label, _to in scenarios:
            blocked = int(_to) < old_k_time  # ← EXACT same logic as views_tv.py:172
            payload = json.dumps({"s": "no_data", "errmsg": "不支持历史数据加载", "nextTime": now_int + 3}, ensure_ascii=False)
            if blocked:
                print(f"    _to={_to} ({label}): {_red('BLOCKED')} → {payload}")
            else:
                print(f"    _to={_to} ({label}): {_green('PASS')} — data returned")
            guard1_results.append({
                "freq": freq, "scenario": label, "_to": _to,
                "blocked": blocked, "payload": payload if blocked else None,
            })

    results["guard_1"] = guard1_results

    # ═══════════════════════════════════════════════════════════════════════
    # Guard #2 — now_trading() + countback (views_tv.py:180-186)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{_bold('Guard #2 — now_trading() + countback (views_tv.py:180-186)')}")
    print(f"  Exact code from views_tv.py:")
    print(f"    if ex.now_trading() is False and int(countback) < 5:")  # line 183
    print(f'        return {{"s": "no_data", "errmsg": "非交易时间", "nextTime": now_time + (10*60)}}')  # line 184-185
    print(f"")
    print(f"  VERIFIED: ex.now_trading() = {is_trading}  [real ExchangeTDX.now_trading() call]")
    print(f"")

    test_countbacks = [0, 1, 2, 3, 4, 5, 10, 100, 300]
    print(f"  {'countback':>10}  {'trading?':>9}  {'evaluation':>30}  {'Web App Returns'}")
    print(f"  {'─' * 10}  {'─' * 9}  {'─' * 30}  {'─' * 45}")

    guard2_results = []
    blocked_count = 0
    pass_count = 0
    blocked_payload = json.dumps({"s": "no_data", "errmsg": "非交易时间", "nextTime": now_int + 600}, ensure_ascii=False)

    for cb in test_countbacks:
        # ← EXACT same logic as views_tv.py:183
        blocked = (is_trading is False) and (int(cb) < 5)

        if blocked:
            blocked_count += 1
            evaluation = _red("BLOCKED")
            response = blocked_payload
        else:
            pass_count += 1
            evaluation = _green("PASS")
            response = '{"s":"ok",...}  ← K-lines + CL overlays returned'

        trading_label = "yes" if is_trading else "no"
        print(f"  {cb:>10}  {trading_label:>9}  {evaluation:>30}  {response}")
        guard2_results.append({"countback": cb, "blocked": blocked, "payload": blocked_payload if blocked else None})

    results["guard_2"] = guard2_results

    # ═══════════════════════════════════════════════════════════════════════
    # Verdict
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{_bold('═' * 70)}")
    if not is_trading:
        verdict = (
            f"  VERIFIED: At {weekday_name} {now.strftime('%H:%M')}, ex.now_trading() returns False.\n"
            f"  Guards at views_tv.py:183-186 WILL block {blocked_count}/{len(test_countbacks)} tested countback values (0-4).\n"
            f"  These requests get: {blocked_payload}\n"
            f"  The CL pipeline is never reached — the web app rejects before calling ex.klines().\n"
            f"\n"
            f"  ROOT CAUSE for '300491.SZ minute charts show no CL data':\n"
            f"  → If viewed outside trading hours + countback < 5, web app returns\n"
            f"    '非交易时间' — empty chart, no K-lines, no CL overlays.\n"
            f"  → This is at the web-app level (views_tv.py:183), NOT a CL pipeline bug."
        )
        results["verdict"] = "blocked"
    else:
        verdict = (
            f"  VERIFIED: ex.now_trading() returns True (trading hours).\n"
            f"  All countback values PASS guard #2. Web app proceeds to fetch klines.\n"
            f"  If no CL data appears, check the pipeline diagnostics below."
        )
        results["verdict"] = "ok"
    print(verdict)

    # ═══════════════════════════════════════════════════════════════════════
    # TDX Connectivity Check
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{_bold('TDX Connectivity Check')}:")
    try:
        stocks = ex.all_stocks()
        print(f"  VERIFIED: ex.all_stocks() → {len(stocks)} stocks")
        matching = [s for s in stocks if code[-6:] in s["code"]]
        if matching:
            print(f"  VERIFIED: code '{code[-6:]}' found → {matching[0]['code']} {matching[0]['name']}")
            results["tdx_ok"] = True
        else:
            print(f"  {_red('FAILED')}: code '{code}' not found in TDX stock list")
            results["tdx_ok"] = False
    except Exception as e:
        print(f"  {_red('FAILED')}: {e}")
        results["tdx_ok"] = False

    return results


# ── main ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose CL pipeline for a specific stock and frequency",
    )
    parser.add_argument(
        "--code",
        default="SZ.300491",
        help="Stock code (e.g., SZ.300491, SH.600519, or bare 300491)",
    )
    parser.add_argument(
        "--market",
        default="a",
        help="Market: a (A-shares), futures, currency",
    )
    parser.add_argument(
        "--freq",
        default="all",
        help="Frequency to test, or 'all' for all supported. Comma-separated: 5m,30m,d",
    )
    parser.add_argument(
        "--mode",
        default="direct",
        choices=["direct", "web"],
        help="direct = bypass FileCacheDB (step-by-step pipeline); web = replica of exact web-app flow",
    )

    args = parser.parse_args()
    code = normalize_code(args.code)

    if args.freq == "all":
        frequencies = THE_FREQUENCIES
    else:
        frequencies = [f.strip() for f in args.freq.split(",")]

    print(f"{_bold('CL Pipeline Diagnostic Tool')}")
    print(f"  Code:   {code}")
    print(f"  Market: {args.market}")
    print(f"  Mode:   {args.mode}")
    print(f"  Freqs:  {', '.join(frequencies)}")
    print(f"  Time:   {datetime.datetime.now().isoformat()}")

    # Always run web-app guard simulation before pipeline diagnostics
    guard_results = {}
    try:
        ex = get_exchange(Market(args.market))
        guard_results = simulate_web_app_guards(ex, code, frequencies)
    except Exception as e:
        print(f"  {_red('Exchange init failed')}: {e}")

    if args.mode == "direct":
        results = diagnose_direct(args.market, code, frequencies)
    else:
        results = diagnose_web(args.market, code, frequencies)

    print_summary(results, guard_results)

    all_ok = all(
        not r.get("error") and (r.get("bi_count", 0) > 0 or r.get("xd_count", 0) > 0)
        for r in results.values()
    )
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
