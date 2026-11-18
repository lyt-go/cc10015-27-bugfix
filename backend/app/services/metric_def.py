"""指标定义业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "metric_def"
ALLOC_MODULE = "factor_alloc"
LIST_FIELDS = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间窗口", "基准取值", "精度位数", "口径版本"]
REQUIRED_FIELDS = ["指标编号", "指标名称", "计算公式"]
STATUS_ORDER = ["草稿", "待校验", "已生效", "已废弃"]
ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "标记废弃": "已废弃"}
NEGATIVE_ACTIONS = []
DEFAULT_CHECK_VERSION = "V027"


class MetricDefService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("指标编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"指标定义 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于指标定义可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"指标定义已{action}"

    def check_factor_layers(self, version: str = DEFAULT_CHECK_VERSION) -> dict[str, Any]:
        """跨模块联动：读取全份该版本的因子约束分配表，核对每个实验的因子层是否完整。

        指标口径直接从分配表行里取（生成时已随行落库），不重新推导，
        保证指标定义看到的就是消费链路实际使用的口径。
        """
        version = (version or "").strip() or DEFAULT_CHECK_VERSION
        rows = [row for row in store.rows(ALLOC_MODULE) if row.get("口径版本") == version]
        if not rows:
            return {
                "version": version,
                "experiments": [],
                "complete": False,
                "message": f"暂无{version}因子约束分配数据，请先在实验因子模块生成分配表",
            }
        by_experiment: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_experiment.setdefault(str(row.get("关联实验", "")), []).append(row)
        experiments: list[dict[str, Any]] = []
        complete = True
        for code, items in by_experiment.items():
            rejected = [item for item in items if item.get("组合状态") != "有效"]
            missing_layers = sorted({
                str(item.get("因子编号", ""))
                for item in items
                if not str(item.get("因子层级") or "").strip()
            })
            calib = next(
                (str(item.get("指标口径") or "") for item in items if str(item.get("指标口径") or "").strip()),
                "",
            )
            exp_complete = not rejected and not missing_layers
            complete = complete and exp_complete
            experiments.append({
                "关联实验": code,
                "组合数": len(items),
                "有效组合": len(items) - len(rejected),
                "已拒绝": len(rejected),
                "缺失层级因子": missing_layers,
                "指标口径": calib,
                "完整": exp_complete,
            })
        message = "全部实验因子层完整" if complete else "存在因子层缺失或被拒绝的组合，请回到实验因子模块处理"
        return {"version": version, "experiments": experiments, "complete": complete, "message": message}
