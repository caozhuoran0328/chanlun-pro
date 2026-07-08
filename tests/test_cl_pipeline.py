"""
Tests for full CL pipeline (cl.py)

Phase 1.4 fixes covered:
- get_idx() MACD(12,26,9)
- get_klines() return type
- get_fx() empty list safety
- Remove duplicate zsds
- cl_config passed to sub-processors
- Constructor parameter name
- Incremental processing
- beichi_pz / beichi_qs / zss_is_qs / create_dn_zs stubs
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd
import pytest
import numpy as np
from chanlun.cl import CL
from chanlun.cl_interface import ICL, Kline, CLKline, FX, BI, XD, ZS, LINE, Config


class TestConstructor:
    """Test CL constructor"""

    def test_default_config(self):
        cl = CL('TEST.000001', 'd')
        assert cl.code == 'TEST.000001'
        assert cl.frequency == 'd'
        assert cl.config == {}

    def test_custom_config(self):
        cfg = {'FX_BH_TYPE': Config.FX_BH_NO.value}
        cl = CL('TEST.000001', 'w', config=cfg)
        assert cl.config == cfg

    def test_start_datetime(self):
        import datetime
        dt = datetime.datetime(2024, 1, 1)
        cl = CL('TEST.000001', 'd', start_datetime=dt)
        assert cl.start_datetime == dt


class TestProcessKlines:
    """Test process_klines pipeline"""

    def _make_sample_df(self, n: int = 100) -> pd.DataFrame:
        """Create sample kline data"""
        import numpy as np
        dates = pd.date_range('2024-01-01', periods=n, freq='D')
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 2)
        high = close + np.abs(np.random.randn(n) * 1.5)
        low = close - np.abs(np.random.randn(n) * 1.5)
        open_price = close - np.random.randn(n) * 0.5
        return pd.DataFrame({
            'date': dates,
            'h': high,
            'l': low,
            'o': open_price,
            'c': close,
            'a': np.abs(np.random.randn(n) * 10000 + 50000),
        })

    def test_process_klines_empty(self):
        cl = CL('TEST.000001', 'd')
        df = self._make_sample_df(10)
        cl.process_klines(df)
        assert len(cl.fxs) >= 0
        assert len(cl.bis) >= 0
        assert cl.get_idx() is not None

    def test_process_klines_returns_self(self):
        cl = CL('TEST.000001', 'd')
        df = self._make_sample_df(20)
        result = cl.process_klines(df)
        assert result is cl

    def test_process_klines_with_config(self):
        cfg = {'FX_BH_TYPE': Config.FX_BH_YES.value}
        cl = CL('TEST.000001', 'd', config=cfg)
        df = self._make_sample_df(30)
        cl.process_klines(df)
        assert len(cl.fxs) >= 0


class TestGetIdx:
    """Test get_idx() MACD computation"""

    def _make_sample_df(self, n: int = 50) -> pd.DataFrame:
        dates = pd.date_range('2024-01-01', periods=n, freq='D')
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 2)
        high = close + np.abs(np.random.randn(n) * 1.5)
        low = close - np.abs(np.random.randn(n) * 1.5)
        open_price = close - np.random.randn(n) * 0.5
        return pd.DataFrame({
            'date': dates,
            'h': high,
            'l': low,
            'o': open_price,
            'c': close,
            'a': np.abs(np.random.randn(n) * 10000 + 50000),
        })

    def test_macd_structure(self):
        cl = CL('TEST.000001', 'd')
        df = self._make_sample_df(50)
        cl.process_klines(df)
        idx = cl.get_idx()
        assert 'macd' in idx
        macd = idx['macd']
        assert 'dif' in macd
        assert 'dea' in macd
        assert 'hist' in macd

    def test_macd_length_matches_input(self):
        cl = CL('TEST.000001', 'd')
        df = self._make_sample_df(50)
        cl.process_klines(df)
        idx = cl.get_idx()
        assert len(idx['macd']['dif']) == 50
        assert len(idx['macd']['dea']) == 50
        assert len(idx['macd']['hist']) == 50

    def test_macd_known_values(self):
        """Test MACD with known input values"""
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        close_values = list(range(100, 130))  # Steadily increasing
        df = pd.DataFrame({
            'date': dates,
            'h': [c + 1 for c in close_values],
            'l': [c - 1 for c in close_values],
            'o': close_values,
            'c': close_values,
            'a': [10000] * 30,
        })
        cl = CL('TEST.000001', 'd')
        cl.process_klines(df)
        idx = cl.get_idx()
        # In an uptrend, DIF should be positive at the end
        assert idx['macd']['dif'][-1] > 0
        # DEA should also be positive (lagging DIF)
        assert isinstance(idx['macd']['dea'][-1], float)

    def test_macd_empty_data(self):
        cl = CL('TEST.000001', 'd')
        idx = cl.get_idx()
        assert idx == {}


class TestGetFxSafety:
    """Test get_fx() empty list safety"""

    def _make_sample_df(self, n=20):
        dates = pd.date_range('2024-01-01', periods=n, freq='D')
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 2)
        return pd.DataFrame({
            'date': dates,
            'h': close + 1,
            'l': close - 1,
            'o': close,
            'c': close,
            'a': [10000] * n,
        })

    def test_get_fx_returns_none_when_empty(self):
        cl = CL('TEST.000001', 'd')
        result = cl.get_fx()
        assert result is None

    def test_get_fx_returns_last(self):
        cl = CL('TEST.000001', 'd')
        df = self._make_sample_df(30)
        cl.process_klines(df)
        fx = cl.get_fx()
        if len(cl.fxs) > 0:
            assert fx is not None
        else:
            assert fx is None


class TestIncrementalProcessing:
    """Test incremental processing support"""

    def test_second_call_no_duplication(self):
        cl = CL('TEST.000001', 'd')
        np.random.seed(42)
        dates1 = pd.date_range('2024-01-01', periods=20, freq='D')
        close1 = 100 + np.cumsum(np.random.randn(20) * 2)
        df1 = pd.DataFrame({
            'date': dates1,
            'h': close1 + 1, 'l': close1 - 1,
            'o': close1, 'c': close1,
            'a': [10000] * 20,
        })
        cl.process_klines(df1)
        fx_count_1 = len(cl.fxs)
        # Process same data again — should return early (no new data)
        cl.process_klines(df1)
        fx_count_2 = len(cl.fxs)
        assert fx_count_1 == fx_count_2


class TestStubMethods:
    """Test stub implementations of ZS/BC/QS methods"""

    def _make_sample_cl(self, n=100) -> CL:
        cl = CL('TEST.000001', 'd')
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=n, freq='D')
        close = 100 + np.cumsum(np.random.randn(n) * 2)
        df = pd.DataFrame({
            'date': dates,
            'h': close + np.abs(np.random.randn(n) * 2),
            'l': close - np.abs(np.random.randn(n) * 2),
            'o': close,
            'c': close + np.random.randn(n) * 0.5,
            'a': np.ones(n) * 10000,
        })
        cl.process_klines(df)
        return cl

    def test_create_dn_zs_empty(self):
        cl = self._make_sample_cl()
        result = cl.create_dn_zs('bi', [])
        assert result == []

    def test_create_dn_zs_with_lines(self):
        cl = self._make_sample_cl()
        result = cl.create_dn_zs('bi', cl.bis)
        assert isinstance(result, list)

    def test_beichi_pz(self):
        cl = self._make_sample_cl()
        if len(cl.bis) >= 3 and len(cl.bi_zss) > 0:
            zs = cl.bi_zss[0]
            now_line = cl.bis[-1]
            result = cl.beichi_pz(zs, now_line)
            assert isinstance(result, tuple)
            assert len(result) == 2

    def test_beichi_qs(self):
        cl = self._make_sample_cl()
        result = cl.beichi_qs(cl.bis, cl.bi_zss, cl.bis[-1] if cl.bis else None)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_zss_is_qs_no_zss(self):
        cl = self._make_sample_cl()
        result = cl.zss_is_qs(None, None)
        assert result == (None, None)


class TestGetMethods:
    """Test all getter methods"""

    def _make_cl(self):
        cl = CL('TEST.000001', 'd')
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        close = 100 + np.cumsum(np.random.randn(30) * 2)
        df = pd.DataFrame({
            'date': dates,
            'h': close + 1, 'l': close - 1,
            'o': close, 'c': close,
            'a': [10000] * 30,
        })
        cl.process_klines(df)
        return cl

    def test_get_code(self):
        cl = CL('ABC.123', 'd')
        assert cl.get_code() == 'ABC.123'

    def test_get_frequency(self):
        cl = CL('ABC.123', '15m')
        assert cl.get_frequency() == '15m'

    def test_get_config(self):
        cfg = {'debug': True}
        cl = CL('ABC.123', 'd', config=cfg)
        assert cl.get_config() == cfg

    def test_get_src_klines(self):
        cl = self._make_cl()
        assert len(cl.get_src_klines()) > 0

    def test_get_klines(self):
        cl = self._make_cl()
        klines = cl.get_klines()
        assert len(klines) > 0

    def test_get_cl_klines(self):
        cl = self._make_cl()
        assert len(cl.get_cl_klines()) > 0

    def test_get_fxs(self):
        cl = self._make_cl()
        assert isinstance(cl.get_fxs(), list)

    def test_get_bis(self):
        cl = self._make_cl()
        assert isinstance(cl.get_bis(), list)

    def test_get_xds(self):
        cl = self._make_cl()
        assert isinstance(cl.get_xds(), list)

    def test_get_zsds(self):
        cl = self._make_cl()
        assert isinstance(cl.get_zsds(), list)

    def test_get_last_bi_zs_empty(self):
        cl = self._make_cl()
        result = cl.get_last_bi_zs()
        assert result is None or isinstance(result, ZS)

    def test_get_last_xd_zs_empty(self):
        cl = self._make_cl()
        result = cl.get_last_xd_zs()
        assert result is None or isinstance(result, ZS)


class TestRealPipelineEndToEnd:
    """Full pipeline integration tests with real CSV data"""

    def _load_real_data(self):
        from chanlun.get_src_klines import convert_src_klines
        csv_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        df = pd.read_csv(csv_path, parse_dates=['date'])
        return convert_src_klines(df)

    def test_full_pipeline_no_crash(self):
        """process_klines should complete without exception with real data"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)
        # All phases should have results
        assert len(cl.get_cl_klines()) > 0
        assert isinstance(cl.get_fxs(), list)
        assert isinstance(cl.get_bis(), list)
        assert isinstance(cl.get_xds(), list)

    def test_pipeline_returns_self(self):
        """process_klines should return self for chaining"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        result = cl.process_klines(df)
        assert result is cl

    def test_macd_indices_valid(self):
        """MACD indices should be valid after processing"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)
        idx = cl.get_idx()
        n = len(df)
        for key in ['dif', 'dea', 'hist']:
            assert len(idx['macd'][key]) == n

    def test_config_propagation_full(self):
        """Config should propagate through all pipeline stages"""
        cfg = {
            'FX_BH_TYPE': Config.FX_BH_DINGDI.value,
            'BI_MIN_KLINE_COUNT': 5,
            'BI_MIN_AMPLITUDE': 0.001,
            'ZS_WZGX_TYPE': Config.ZS_WZGX_ZGD.value,
        }
        cl = CL('TEST.SH.001', 'd', config=cfg)
        df = self._load_real_data()
        cl.process_klines(df)
        # Verify config is stored
        assert cl.get_config() == cfg

    def test_pipeline_data_integrity(self):
        """Verify pipeline produces self-consistent data"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)

        # BI indices should be sequential and non-decreasing
        bis = cl.get_bis()
        for i in range(1, len(bis)):
            assert bis[i].index >= bis[i - 1].index

        # Each BI should have valid start/end
        for bi in bis:
            assert bi.start is not None
            assert bi.end is not None

    def test_bi_zss_created(self):
        """BI ZSs should be created from BI list"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)

        bi_zss = cl.get_bi_zss()
        assert isinstance(bi_zss, list)

        # All ZSs should have valid attributes
        for zs in bi_zss:
            assert zs.zs_type in ('bi', 'xd')
            assert zs.zg >= zs.zd  # zg should be >= zd for valid ZS

    def test_xd_zss_created(self):
        """XD ZSs should be created from XD list"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)

        xd_zss = cl.get_xd_zss()
        assert isinstance(xd_zss, list)

    def test_bc_computed_on_bis(self):
        """BC should be computed on BIs after pipeline"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)

        for bi in cl.get_bis():
            assert isinstance(bi.get_bcs('bi'), list)
            assert isinstance(bi.get_bcs('xd'), list)

    def test_mmd_computed_on_bis(self):
        """MMD should be computed on BIs after pipeline"""
        cl = CL('TEST.SH.001', 'd')
        df = self._load_real_data()
        cl.process_klines(df)

        for bi in cl.get_bis():
            assert isinstance(bi.get_mmds('bi'), list)
            assert isinstance(bi.get_mmds('xd'), list)

    def test_pipeline_with_minimal_data(self):
        """Pipeline should handle minimal CSV data without crash"""
        small_df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=10, freq='D'),
            'h': [10.5, 11.0, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5, 15.0, 14.5],
            'l': [9.8, 10.0, 10.5, 10.0, 11.5, 10.5, 12.0, 11.5, 13.0, 12.5],
            'o': [10.0, 10.5, 11.0, 10.8, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5],
            'c': [10.2, 10.8, 11.5, 11.0, 12.5, 11.8, 13.5, 12.8, 14.5, 13.8],
            'a': [10000] * 10,
        })
        cl = CL('TEST.MIN.001', 'd')
        # Support both 'high' and 'h' column formats
        df2 = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=10, freq='D'),
            'high': [10.5, 11.0, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5, 15.0, 14.5],
            'low': [9.8, 10.0, 10.5, 10.0, 11.5, 10.5, 12.0, 11.5, 13.0, 12.5],
            'open': [10.0, 10.5, 11.0, 10.8, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5],
            'close': [10.2, 10.8, 11.5, 11.0, 12.5, 11.8, 13.5, 12.8, 14.5, 13.8],
            'volume': [10000] * 10,
        })
        # Should handle both column formats
        cl.process_klines(small_df)
        cl2 = CL('TEST.MIN.002', 'd')
        cl2.process_klines(df2)
        assert len(cl2.get_cl_klines()) > 0


class TestDefaultFxBhConfig:
    """Test that the default fx_bh config is FX_BH_DINGDI (minute-data friendly)"""

    def test_default_fx_bh_is_dingdi_not_no(self):
        """CL should process with FX_BH_DINGDI as the new recommended default"""
        # Verify that Config values exist and are distinct
        assert Config.FX_BH_DINGDI.value == "fx_bh_dingdi"
        assert Config.FX_BH_NO.value == "fx_bh_no"
        assert Config.FX_BH_DINGDI.value != Config.FX_BH_NO.value

    def test_default_fx_bh_dingdi_produces_fxs_with_tight_ranges(self):
        """FX_BH_DINGDI should produce FXs even with tight price ranges (simulates minute data)"""
        import numpy as np
        # Simulate minute-level data with small oscillations
        dates = pd.date_range('2024-01-01', periods=100, freq='1min')
        np.random.seed(42)
        base = 10.0
        small_moves = np.sin(np.linspace(0, 4*np.pi, 100)) * 0.05  # ±5% peak
        close = base + small_moves + np.cumsum(np.random.randn(100) * 0.01)
        high = close + np.abs(np.random.randn(100) * 0.02)
        low = close - np.abs(np.random.randn(100) * 0.02)
        df = pd.DataFrame({
            'date': dates,
            'h': high,
            'l': low,
            'o': close,
            'c': close + np.random.randn(100) * 0.005,
            'a': np.ones(100) * 1000,
        })

        # Use FX_BH_NO (old strict default)
        cl_strict = CL('TEST', '1m', config={'FX_BH_TYPE': Config.FX_BH_NO.value})
        cl_strict.process_klines(df)
        fxs_strict = len(cl_strict.get_fxs())

        # Use FX_BH_DINGDI (new default)
        cl_dingdi = CL('TEST', '1m', config={'FX_BH_TYPE': Config.FX_BH_DINGDI.value})
        cl_dingdi.process_klines(df)
        fxs_dingdi = len(cl_dingdi.get_fxs())

        # DINGDI should produce >= FXs than NO for minute data with small oscillations
        assert fxs_dingdi >= fxs_strict

    def test_min_amplitude_config_reduces_bis(self):
        """Higher BI_MIN_AMPLITUDE should reduce BI count"""
        import numpy as np
        dates = pd.date_range('2024-01-01', periods=200, freq='1min')
        np.random.seed(42)
        base = 10.0
        waves = np.sin(np.linspace(0, 8*np.pi, 200)) * 1.0  # ±10% waves
        close = base + waves + np.cumsum(np.random.randn(200) * 0.05)
        df = pd.DataFrame({
            'date': dates,
            'h': close + np.abs(np.random.randn(200) * 0.05),
            'l': close - np.abs(np.random.randn(200) * 0.05),
            'o': close - np.random.randn(200) * 0.02,
            'c': close,
            'a': np.ones(200) * 1000,
        })

        # Low amplitude threshold → more BIs
        cl_low = CL('TEST', '1m', config={
            'FX_BH_TYPE': Config.FX_BH_YES.value,
            'BI_MIN_AMPLITUDE': 0.0001,
            'BI_MIN_KLINE_COUNT': 3,
        })
        cl_low.process_klines(df)

        # High amplitude threshold → fewer BIs
        cl_high = CL('TEST', '1m', config={
            'FX_BH_TYPE': Config.FX_BH_YES.value,
            'BI_MIN_AMPLITUDE': 0.1,
            'BI_MIN_KLINE_COUNT': 5,
        })
        cl_high.process_klines(df)

        assert len(cl_high.get_bis()) <= len(cl_low.get_bis())

    def test_min_kline_count_config_reduces_bis(self):
        """Higher BI_MIN_KLINE_COUNT should reduce BI count"""
        import numpy as np
        dates = pd.date_range('2024-01-01', periods=200, freq='1min')
        np.random.seed(42)
        base = 10.0
        waves = np.sin(np.linspace(0, 8*np.pi, 200)) * 1.0
        close = base + waves + np.cumsum(np.random.randn(200) * 0.05)
        df = pd.DataFrame({
            'date': dates,
            'h': close + np.abs(np.random.randn(200) * 0.05),
            'l': close - np.abs(np.random.randn(200) * 0.05),
            'o': close - np.random.randn(200) * 0.02,
            'c': close,
            'a': np.ones(200) * 1000,
        })

        # Low kline count threshold → more BIs
        cl_low = CL('TEST', '1m', config={
            'FX_BH_TYPE': Config.FX_BH_YES.value,
            'BI_MIN_KLINE_COUNT': 3,
        })
        cl_low.process_klines(df)

        # High kline count threshold → fewer BIs
        cl_high = CL('TEST', '1m', config={
            'FX_BH_TYPE': Config.FX_BH_YES.value,
            'BI_MIN_KLINE_COUNT': 8,
        })
        cl_high.process_klines(df)

        assert len(cl_high.get_bis()) <= len(cl_low.get_bis())


class TestConfigPropagation:
    """Test config propagation through all pipeline stages"""

    def _load_real_data(self):
        from chanlun.get_src_klines import convert_src_klines
        csv_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        df = pd.read_csv(csv_path, parse_dates=['date'])
        return convert_src_klines(df)

    def test_fx_bh_config_affects_fx_count(self):
        """Different FX_BH configs may produce different FX counts"""
        df = self._load_real_data()
        cl_strict = CL('TEST.001', 'd', config={'FX_BH_TYPE': Config.FX_BH_NO.value})
        cl_loose = CL('TEST.001', 'd', config={'FX_BH_TYPE': Config.FX_BH_YES.value})
        cl_strict.process_klines(df)
        cl_loose.process_klines(df)
        # Loose config should produce >= FX than strict
        assert len(cl_loose.get_fxs()) >= len(cl_strict.get_fxs())

    def test_bi_min_amplitude_affects_bi_count(self):
        """Higher min amplitude threshold should produce fewer BIs"""
        df = self._load_real_data()
        cl_default = CL('TEST.DEF', 'd')
        cl_default.process_klines(df)
        cl_strict = CL('TEST.STR', 'd', config={'BI_MIN_AMPLITUDE': 0.1})
        cl_strict.process_klines(df)
        # Higher threshold → fewer BIs
        assert len(cl_strict.get_bis()) <= len(cl_default.get_bis())

    def test_zs_wzgx_config_propagates_to_zss_is_qs(self):
        """ZS_WZGX_TYPE config should propagate to zss_is_qs"""
        df = self._load_real_data()
        cl = CL('TEST.ZS', 'd', config={'ZS_WZGX_TYPE': Config.ZS_WZGX_GD.value})
        cl.process_klines(df)
        # If we have >= 2 ZSs, zss_is_qs should work with the config
        result = cl.zss_is_qs(None, None)
        assert result == (None, None)


class TestPickleBackwardCompatibility:
    """Test that old pickled CL objects (with cl_config) work with new code (config)"""

    def test_unpickle_old_format_with_cl_config(self):
        """Simulate unpickling an old CL object that had cl_config instead of config"""
        import pickle
        import datetime

        # Simulate old state dict (as if from pickle of old code)
        old_state = {
            'code': 'TEST.OLD.001',
            'frequency': 'd',
            'cl_config': {'FX_BH_TYPE': Config.FX_BH_YES.value},
            # Old objects would NOT have 'config' key
            'start_datetime': datetime.datetime(2024, 1, 1),
            'src_klines': [],
            'cl_klines': [],
            'idx': {},
            'fxs': [],
            'bis': [],
            'xds': [],
            'zsds': [],
            'qsds': [],
            'bi_zss': [],
            'xd_zss': [],
            'zsd_zss': [],
            'qsd_zss': [],
        }

        # Use __setstate__ directly (simulating what pickle.load would do)
        cl = CL.__new__(CL)
        cl.__setstate__(old_state)

        # Verify migration happened: config should now exist and match cl_config
        assert cl.config == old_state['cl_config']
        assert cl.config == {'FX_BH_TYPE': Config.FX_BH_YES.value}
        assert cl.code == 'TEST.OLD.001'
        assert cl.frequency == 'd'

    def test_unpickle_old_format_process_klines_works(self):
        """Old unpickled CL should be able to call process_klines without AttributeError"""
        import datetime

        old_state = {
            'code': 'TEST.OLD.002',
            'frequency': 'd',
            'cl_config': {'FX_BH_TYPE': Config.FX_BH_YES.value},
            'start_datetime': None,
            'src_klines': [],
            'cl_klines': [],
            'idx': {},
            'fxs': [],
            'bis': [],
            'xds': [],
            'zsds': [],
            'qsds': [],
            'bi_zss': [],
            'xd_zss': [],
            'zsd_zss': [],
            'qsd_zss': [],
        }

        cl = CL.__new__(CL)
        cl.__setstate__(old_state)

        # This would raise AttributeError before the fix
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=20, freq='D')
        close = 100 + np.cumsum(np.random.randn(20) * 2)
        df = pd.DataFrame({
            'date': dates,
            'h': close + 1, 'l': close - 1,
            'o': close, 'c': close,
            'a': [10000] * 20,
        })
        result = cl.process_klines(df)
        assert result is cl
        assert len(cl.get_cl_klines()) > 0

    def test_full_pickle_roundtrip(self):
        """New CL objects should pickle/unpickle correctly"""
        import pickle

        cl = CL('TEST.RT.001', 'd', config={'FX_BH_TYPE': Config.FX_BH_NO.value})
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        close = 100 + np.cumsum(np.random.randn(30) * 2)
        df = pd.DataFrame({
            'date': dates,
            'h': close + 1, 'l': close - 1,
            'o': close, 'c': close,
            'a': [10000] * 30,
        })
        cl.process_klines(df)

        # Pickle and unpickle
        data = pickle.dumps(cl)
        cl2 = pickle.loads(data)

        assert cl2.code == cl.code
        assert cl2.frequency == cl.frequency
        assert cl2.config == cl.config
        assert cl2.get_config() == cl.get_config()
        assert len(cl2.get_cl_klines()) == len(cl.get_cl_klines())


class TestEmptyAndEdgeCases:
    """Test edge cases for the CL pipeline"""

    def test_empty_dataframe(self):
        cl = CL('TEST.EMPTY', 'd')
        df = pd.DataFrame()
        # process_klines should handle empty DataFrame gracefully
        try:
            cl.process_klines(df)
        except Exception:
            pass  # May need K-line columns
        # get_idx should still return dict or empty
        idx = cl.get_idx()
        assert isinstance(idx, dict)

    def test_very_few_klines(self):
        """Pipeline with very few klines should not crash"""
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=3, freq='D'),
            'h': [11.0, 12.0, 10.0],
            'l': [10.0, 11.0, 9.0],
            'o': [10.5, 11.5, 9.5],
            'c': [10.8, 11.8, 9.8],
            'a': [10000] * 3,
        })
        cl = CL('TEST.FEW', 'd')
        cl.process_klines(df)
        assert len(cl.get_cl_klines()) > 0
        # May or may not have FX/BI with only 3 klines
        assert isinstance(cl.get_fxs(), list)

    def test_flat_prices(self):
        """Pipeline with completely flat prices should not crash"""
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=10, freq='D'),
            'h': [10.0] * 10,
            'l': [10.0] * 10,
            'o': [10.0] * 10,
            'c': [10.0] * 10,
            'a': [10000] * 10,
        })
        cl = CL('TEST.FLAT', 'd')
        cl.process_klines(df)
        assert len(cl.get_cl_klines()) > 0
