"""因子约束分配表（V027）链路测试：互斥校验、空值边界、中断续跑与跨模块核对。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.store import store
from app.services.expr_factor import ExprFactorService, ALLOC_MODULE
from app.services.metric_def import MetricDefService
from app.routers import expr_factor as expr_factor_router
from app.routers import metric_def as metric_def_router


def _clear_all():
    for k in list(store._tables.keys()):
        store._tables[k] = []


def _experiment(code="EXPE-0001", ratio="4:6"):
    return {"id": len(store.rows("experiment")) + 1, "方案编号": code, "实验名称": f"实验{code}",
            "对照组说明": "对照", "实验组说明": "实验", "样本总量": "1000", "分流比例": ratio,
            "启动日期": "2026-11-01", "预期时长": "14", "status": "运行中",
            "pending": False, "abnormal": False}


def _factor(code, experiment, *, level="UI层", rule="", name=None):
    return {"id": len(store.rows("expr_factor")) + 1, "因子编号": code, "因子名称": name or f"因子{code}",
            "因子层级": level, "取值集合": "A,B", "分配比例": "5:5", "互斥规则": rule,
            "关联实验": experiment, "生效批次": "B001", "status": "已生效",
            "pending": False, "abnormal": False}


def _metric(version="V027", formula="clicks / impressions"):
    return {"id": len(store.rows("metric_def")) + 1, "指标编号": f"METR-{version}", "指标名称": "点击率",
            "计算公式": formula, "统计粒度": "日", "时间窗口": "7", "基准取值": "0.1",
            "精度位数": "4", "口径版本": version, "status": "已生效",
            "pending": False, "abnormal": False}


def _seed_base(*, version="V027"):
    """一个实验 + 一条 V027 指标口径。"""
    store.rows("experiment").append(_experiment())
    store.rows("metric_def").append(_metric(version))


def test_alloc_valid_row_persists_level_and_rule():
    """有效组合落库时必须同时带上因子层级与互斥规则，并读取实验分流比例与指标口径。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001", level="UI层", rule="颜色互斥"))
    svc = ExprFactorService()
    result, message = svc.generate_allocation(version="V027")
    assert result["generated"] == 1 and result["rejected"] == 0, message
    rows = store.rows(ALLOC_MODULE)
    assert len(rows) == 1
    row = rows[0]
    assert row["组合状态"] == "有效"
    assert row["因子层级"] == "UI层" and row["互斥规则"] == "颜色互斥"  # 同时落库
    assert row["实验分流比例"] == "4:6"  # 来自实验
    assert row["指标口径"] == "clicks / impressions"  # 来自 V027 指标定义
    assert row["缺失字段"] == [] and row["拒绝原因"] == ""


def test_alloc_mutex_conflict_rejected_not_valid():
    """两个互斥因子同时命中同一实验：拒绝冲突组合并列出原因，不生成有效组合。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001", rule="样式互斥"))
    store.rows("expr_factor").append(_factor("EXPR-2", "EXPE-0001", rule="样式互斥"))
    svc = ExprFactorService()
    result, _ = svc.generate_allocation(version="V027")
    assert result["generated"] == 0 and result["rejected"] == 2
    rows = store.rows(ALLOC_MODULE)
    assert all(r["组合状态"] == "已拒绝" for r in rows)
    for row in rows:
        assert "互斥因子冲突" in row["拒绝原因"]
        assert "EXPR-1" in row["拒绝原因"] and "EXPR-2" in row["拒绝原因"]
        assert "样式互斥" in row["拒绝原因"]


def test_alloc_missing_level_rejected_not_empty_string():
    """缺失因子层级不再当作空字符串继续执行：记为拒绝并列出缺失字段，不补造默认值。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001", level=""))
    svc = ExprFactorService()
    result, _ = svc.generate_allocation(version="V027")
    assert result["generated"] == 0 and result["rejected"] == 1
    row = store.rows(ALLOC_MODULE)[0]
    assert row["组合状态"] == "已拒绝"
    assert "因子层级" in row["缺失字段"]
    assert "缺失必填字段" in row["拒绝原因"]
    assert row["因子层级"] == ""  # 保持缺失，不补造默认值


def test_alloc_mutex_and_missing_combined():
    """互斥命中且一方层级缺失：两种原因都要列出，冲突与空层级都不进入有效分配。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001", level="", rule="样式互斥"))
    store.rows("expr_factor").append(_factor("EXPR-2", "EXPE-0001", level="UI层", rule="样式互斥"))
    svc = ExprFactorService()
    result, _ = svc.generate_allocation(version="V027")
    assert result["generated"] == 0 and result["rejected"] == 2
    rows = {r["因子编号"]: r for r in store.rows(ALLOC_MODULE)}
    assert "互斥因子冲突" in rows["EXPR-1"]["拒绝原因"]
    assert "因子层级" in rows["EXPR-1"]["缺失字段"]
    assert "互斥因子冲突" in rows["EXPR-2"]["拒绝原因"]
    assert rows["EXPR-2"]["缺失字段"] == []


def test_alloc_empty_state_message():
    """空态：没有命中因子时给出暂无说明，分配表保持为空。"""
    _clear_all()
    _seed_base()
    svc = ExprFactorService()
    result, message = svc.generate_allocation(version="V027")
    assert result["generated"] == 0 and result["rejected"] == 0
    assert "为空" in message
    items, total = svc.list_allocation(version="V027")
    assert items == [] and total == 0


def test_alloc_list_and_detail_consistent():
    """列表入口与详情面板读同一张表，结果必须一致。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001"))
    svc = ExprFactorService()
    svc.generate_allocation(version="V027")
    items, total = svc.list_allocation(version="V027")
    assert total == 1
    detail = svc.get_allocation(items[0]["id"])
    assert detail is items[0] or detail == items[0]


def test_alloc_interrupt_keeps_completed_and_resume(monkeypatch):
    """分配中断后保留已完成实验；续跑只补未完成实验，不为缺失层级补造默认值。"""
    _clear_all()
    store.rows("experiment").append(_experiment("EXPE-0001"))
    store.rows("experiment").append(_experiment("EXPE-0002"))
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001"))
    store.rows("expr_factor").append(_factor("EXPR-2", "EXPE-0002", level=""))
    svc = ExprFactorService()
    original = ExprFactorService._build_experiment_rows

    def flaky(self, experiment, factors, version, calib):
        if experiment.get("方案编号") == "EXPE-0002":
            raise RuntimeError("模拟中断")
        return original(self, experiment, factors, version, calib)

    monkeypatch.setattr(ExprFactorService, "_build_experiment_rows", flaky)
    result, message = svc.generate_allocation(version="V027")
    assert result["interrupted"] is True
    assert result["completed"] == ["EXPE-0001"]  # 已完成实验保留
    assert "重试" in message or "续跑" in message
    assert len(store.rows(ALLOC_MODULE)) == 1
    monkeypatch.setattr(ExprFactorService, "_build_experiment_rows", original)
    # 续跑：只补 EXPE-0002，EXPE-0001 不重复生成
    result2, _ = svc.generate_allocation(version="V027", resume=True)
    assert result2["interrupted"] is False
    assert result2["completed"] == ["EXPE-0002"]
    rows = store.rows(ALLOC_MODULE)
    assert len(rows) == 2  # 没有重复
    row2 = [r for r in rows if r["关联实验"] == "EXPE-0002"][0]
    assert row2["组合状态"] == "已拒绝" and row2["因子层级"] == ""  # 缺失层级不补造
    assert "因子层级" in row2["缺失字段"]


def test_alloc_regenerate_no_residue():
    """重复生成不留空数据残留：旧行被整批替换，总数不膨胀。"""
    _clear_all()
    _seed_base()
    factor = _factor("EXPR-1", "EXPE-0001")
    store.rows("expr_factor").append(factor)
    svc = ExprFactorService()
    svc.generate_allocation(version="V027")
    svc.generate_allocation(version="V027")
    assert len(store.rows(ALLOC_MODULE)) == 1
    # 因子层级后来缺失：再生成时旧有效行被替换为拒绝行，不留残留
    factor["因子层级"] = ""
    svc.generate_allocation(version="V027")
    rows = store.rows(ALLOC_MODULE)
    assert len(rows) == 1
    assert rows[0]["组合状态"] == "已拒绝" and rows[0]["因子层级"] == ""


def test_alloc_version_isolation():
    """不同口径版本的分配行互不干扰；V027 下校验不到未生成的版本。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001"))
    svc = ExprFactorService()
    svc.generate_allocation(version="V027")
    svc.generate_allocation(version="V028")
    v027, total27 = svc.list_allocation(version="V027")
    v028, total28 = svc.list_allocation(version="V028")
    assert total27 == 1 and total28 == 1
    assert v027[0]["口径版本"] == "V027" and v028[0]["口径版本"] == "V028"
    items, total = svc.list_allocation(version="V029")
    assert items == [] and total == 0


def test_metric_def_factor_layer_check():
    """跨模块联动：指标定义读取分配表指标口径，逐实验核对因子层完整性。"""
    _clear_all()
    _seed_base()
    store.rows("expr_factor").append(_factor("EXPR-1", "EXPE-0001", level=""))
    ExprFactorService().generate_allocation(version="V027")
    check = MetricDefService().check_factor_layers("V027")
    assert check["complete"] is False
    exp = check["experiments"][0]
    assert exp["关联实验"] == "EXPE-0001"
    assert exp["指标口径"] == "clicks / impressions"  # 从分配表读取
    assert exp["缺失层级因子"] == ["EXPR-1"]
    assert exp["已拒绝"] == 1
    # 补齐层级后重新生成，核对转为完整
    store.rows("expr_factor")[0]["因子层级"] = "UI层"
    ExprFactorService().generate_allocation(version="V027")
    check2 = MetricDefService().check_factor_layers("V027")
    assert check2["complete"] is True
    assert check2["experiments"][0]["缺失层级因子"] == []


def test_metric_def_factor_layer_check_empty():
    """分配表为空时核对给出暂无说明而不是报错。"""
    _clear_all()
    check = MetricDefService().check_factor_layers("V027")
    assert check["experiments"] == []
    assert "暂无" in check["message"]


def test_allocation_routes_declared_before_entry_id():
    """分配表与核对接口必须声明在 /{entry_id} 之前，否则会被路径参数吞掉。"""
    factor_paths = [r.path for r in expr_factor_router.router.routes]
    assert factor_paths.index("/api/expr_factor/allocation") < factor_paths.index("/api/expr_factor/{entry_id}")
    assert factor_paths.index("/api/expr_factor/allocation/{alloc_id}") < factor_paths.index("/api/expr_factor/{entry_id}")
    metric_paths = [r.path for r in metric_def_router.router.routes]
    assert metric_paths.index("/api/metric_def/factor_layer_check") < metric_paths.index("/api/metric_def/{entry_id}")
