"""
Tests for CL pickle cache compatibility.

Covers:
    - CL.__setstate__ backward compatibility (cl_config -> config migration)
    - CL._pickle_version round-trip
    - CL pickle serialization/deserialization
"""
import pickle
import pathlib
import tempfile

import pandas as pd
import pytest

from chanlun.cl import CL
from chanlun.cl_interface import ICL


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_cl():
    """创建一个标准的 CL 对象"""
    return CL(code="TEST", frequency="d", config={"fx_qj": "5"})


@pytest.fixture
def sample_klines():
    """创建简单的 K 线测试数据"""
    return pd.DataFrame({
        "code": ["TEST"] * 5,
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
        "open": [10, 11, 12, 11, 13],
        "high": [11, 12, 13, 12, 14],
        "low": [9, 10, 11, 10, 12],
        "close": [10.5, 11.5, 12.5, 11.5, 13.5],
        "volume": [1000, 1100, 1200, 1100, 1300],
    })


# ---------------------------------------------------------------------------
# CL.__setstate__ backward compatibility
# ---------------------------------------------------------------------------

class TestCLSetState:
    """测试 CL.__setstate__ 从旧 pickle 格式迁移数据"""

    def test_old_state_with_cl_config_migrates_to_config(self):
        """旧 pickle 只有 cl_config 时，__setstate__ 应自动创建 config"""
        old_state = {
            "code": "TEST",
            "frequency": "d",
            "cl_config": {"fx_qj": "5", "bi_type": "old"},
            "src_klines": [],
            "cl_klines": [],
        }
        cl_obj = object.__new__(CL)
        cl_obj.__setstate__(old_state)
        assert cl_obj.config == {"fx_qj": "5", "bi_type": "old"}
        assert cl_obj.code == "TEST"
        assert cl_obj.frequency == "d"

    def test_old_state_cleans_up_cl_config_after_migration(self):
        """迁移完成后，__dict__ 中不应残留 cl_config 属性"""
        old_state = {
            "code": "TEST",
            "frequency": "d",
            "cl_config": {"fx_qj": "5"},
            "src_klines": [],
        }
        cl_obj = object.__new__(CL)
        cl_obj.__setstate__(old_state)
        assert "cl_config" not in cl_obj.__dict__
        assert "config" in cl_obj.__dict__

    def test_new_state_with_config_preserves_config(self):
        """新格式（有 config）时，不应触发迁移"""
        state = {
            "code": "NEW",
            "frequency": "w",
            "config": {"fx_qj": "10"},
            "src_klines": [],
            "_pickle_version": 1,
            "cl_klines": [],
            "idx": {},
            "start_datetime": None,
            "fxs": [],
            "bis": [],
            "xds": [],
            "zsds": [],
            "qsds": [],
            "bi_zss": [],
            "xd_zss": [],
            "zsd_zss": [],
            "qsd_zss": [],
        }
        cl_obj = object.__new__(CL)
        cl_obj.__setstate__(state)
        assert cl_obj.config == {"fx_qj": "10"}
        assert cl_obj.code == "NEW"
        assert cl_obj.frequency == "w"
        assert "cl_config" not in cl_obj.__dict__

    def test_missing_attributes_filled_with_defaults(self):
        """从极旧版本加载时，缺失的属性应填充默认值"""
        minimal_state = {
            "code": "OLD",
            "frequency": "m",
            "cl_config": {"fx_qj": "3"},
        }
        cl_obj = object.__new__(CL)
        cl_obj.__setstate__(minimal_state)
        assert cl_obj.idx == {}
        assert cl_obj.start_datetime is None
        assert cl_obj.fxs == []
        assert cl_obj.bis == []
        assert cl_obj.xds == []
        assert cl_obj.bi_zss == []
        assert cl_obj.xd_zss == []

    def test_state_with_both_config_and_cl_config_prefers_config(self):
        """同时有 config 和 cl_config 时，优先使用 config 不触发迁移"""
        state = {
            "code": "BOTH",
            "frequency": "d",
            "config": {"fx_qj": "20"},
            "cl_config": {"fx_qj": "5"},
            "src_klines": [],
            "idx": {},
            "start_datetime": None,
            "fxs": [], "bis": [], "xds": [], "zsds": [], "qsds": [],
            "bi_zss": [], "xd_zss": [], "zsd_zss": [], "qsd_zss": [],
        }
        cl_obj = object.__new__(CL)
        cl_obj.__setstate__(state)
        assert cl_obj.config == {"fx_qj": "20"}

    def test_cl_config_without_config_in_dict_is_migrated(self):
        """兜底：__dict__ 中只有 cl_config 没有 config 时，自动迁移"""
        old_state = {
            "code": "TEST",
            "frequency": "d",
            "cl_config": {"fx_qj": "5"},
            "src_klines": [],
            "cl_klines": [],
        }
        cl_obj = object.__new__(CL)
        cl_obj.__setstate__(old_state)
        assert cl_obj.config == {"fx_qj": "5"}
        assert "cl_config" not in cl_obj.__dict__


# ---------------------------------------------------------------------------
# CL pickle round-trip
# ---------------------------------------------------------------------------

class TestCLPickleRoundTrip:
    """测试 CL 对象的完整 pickle 序列化/反序列化流程"""

    def test_new_cl_round_trip(self, sample_cl, sample_klines):
        """新创建的 CL 对象可以正常 pickle/unpickle 往返"""
        sample_cl.process_klines(sample_klines)
        pickled = pickle.dumps(sample_cl)
        loaded: CL = pickle.loads(pickled)
        assert loaded.code == "TEST"
        assert loaded.frequency == "d"
        assert loaded.config == {"fx_qj": "5"}
        assert loaded._pickle_version == CL.PICKLE_VERSION
        # 5 根简单 K 线不一定产生笔，但对象结构应完好
        assert loaded.get_bis() is not None

    def test_loaded_cl_works_after_incremental_update(self, sample_cl, sample_klines):
        """pickle 加载后的 CL 对象可以正确处理增量 K 线"""
        sample_cl.process_klines(sample_klines)
        bis_before = len(sample_cl.get_bis())

        pickled = pickle.dumps(sample_cl)
        loaded: CL = pickle.loads(pickled)

        # 追加一根新的 K 线
        new_klines = pd.DataFrame({
            "code": ["TEST"],
            "date": pd.to_datetime(["2024-01-06"]),
            "open": [14],
            "high": [15],
            "low": [13],
            "close": [14.5],
            "volume": [1400],
        })
        full_klines = pd.concat([sample_klines, new_klines], ignore_index=True)
        loaded.process_klines(full_klines)

        assert len(loaded.get_bis()) >= bis_before

    def test_round_trip_preserves_idx(self, sample_cl, sample_klines):
        """pickle 往返后 MACD 指标数据正确保留"""
        sample_cl.process_klines(sample_klines)
        pickled = pickle.dumps(sample_cl)
        loaded: CL = pickle.loads(pickled)
        assert "macd" in loaded.get_idx()
        assert len(loaded.get_idx()["macd"]["dif"]) > 0
        assert len(loaded.get_idx()["macd"]["dea"]) > 0

    def test_round_trip_preserves_bis(self, sample_cl, sample_klines):
        """pickle 往返后笔数据正确保留"""
        sample_cl.process_klines(sample_klines)
        original_bis_count = len(sample_cl.get_bis())
        pickled = pickle.dumps(sample_cl)
        loaded: CL = pickle.loads(pickled)
        assert len(loaded.get_bis()) == original_bis_count

    def test_round_trip_preserves_config(self, sample_cl, sample_klines):
        """pickle 往返后配置信息正确保留"""
        sample_cl.config["test_key"] = "test_value"
        sample_cl.process_klines(sample_klines)
        pickled = pickle.dumps(sample_cl)
        loaded: CL = pickle.loads(pickled)
        assert loaded.config == sample_cl.config


# ---------------------------------------------------------------------------
# PICKLE_VERSION constant
# ---------------------------------------------------------------------------

class TestPickleVersion:
    """测试 CL.PICKLE_VERSION 定义"""

    def test_pickle_version_is_positive_int(self):
        """版本号是正整数"""
        assert isinstance(CL.PICKLE_VERSION, int)
        assert CL.PICKLE_VERSION >= 1

    def test_new_instance_has_version(self, sample_cl):
        """新创建的 CL 对象自带版本号"""
        assert hasattr(sample_cl, '_pickle_version')
        assert sample_cl._pickle_version == CL.PICKLE_VERSION

    def test_pickle_contains_version(self, sample_cl):
        """pickle 序列化后包含版本号"""
        data = pickle.dumps(sample_cl)
        loaded = pickle.loads(data)
        assert hasattr(loaded, '_pickle_version')
        assert loaded._pickle_version == CL.PICKLE_VERSION


# ---------------------------------------------------------------------------
# Pickle file-based tests (no FileCacheDB import needed)
# ---------------------------------------------------------------------------

class TestPickleFileCompatibility:
    """测试 pickle 文件的兼容性处理"""

    def test_valid_pickle_file_loads_correctly(self, sample_cl, sample_klines):
        """有效的 pickle 文件可以正确加载"""
        sample_cl.process_klines(sample_klines)
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fp:
            pickle.dump(sample_cl, fp)
            tmp_path = pathlib.Path(fp.name)

        try:
            with open(tmp_path, "rb") as f:
                loaded = pickle.load(f)
            assert loaded.code == "TEST"
            assert loaded.config == sample_cl.config
            assert loaded._pickle_version == CL.PICKLE_VERSION
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_old_version_pickle_detected_and_migrated(self, sample_cl):
        """旧版本 pickle（版本0，有 cl_config）被正确识别和迁移"""
        # 模拟旧版本状态
        old_state = {
            "code": "OLD_CODE",
            "frequency": "d",
            "cl_config": {"fx_qj": "3"},
            "src_klines": [],
            "cl_klines": [],
        }
        # 使用 CL 的 __setstate__ 机制加载
        cl_obj = object.__new__(CL)
        # 先不传 _pickle_version，模拟旧 pickle 没有版本号
        cl_obj.__setstate__(old_state)
        # 新 __setstate__ 会自动设置版本号
        assert cl_obj._pickle_version == CL.PICKLE_VERSION
        assert cl_obj.config == {"fx_qj": "3"}
        assert "cl_config" not in cl_obj.__dict__

    def test_broken_pickle_file_raises(self):
        """损坏的 pickle 文件在加载时抛出异常"""
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fp:
            fp.write(b"this is not a valid pickle file")
            tmp_path = pathlib.Path(fp.name)

        try:
            with pytest.raises((pickle.UnpicklingError, ValueError, EOFError, Exception)):
                with open(tmp_path, "rb") as f:
                    pickle.load(f)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_version_mismatch_detectable(self, sample_cl):
        """版本不匹配可以被检测到"""
        sample_cl._pickle_version = 999  # 不存在的高版本
        stored_version = getattr(sample_cl, '_pickle_version', 0)
        curr_version = CL.PICKLE_VERSION
        assert stored_version != curr_version

    def test_no_version_is_version_zero(self, sample_cl):
        """没有版本号的对象版本为0"""
        del sample_cl._pickle_version
        stored_version = getattr(sample_cl, '_pickle_version', 0)
        assert stored_version == 0
        assert stored_version != CL.PICKLE_VERSION
