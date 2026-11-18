"""实验因子业务规则：状态流转、字段校验与筛选口径都收在这里。

同时维护「因子约束分配表」（factor_alloc）：
- 生成时读取因子配置与实验分流比例，先校验互斥与空值边界，再落库；
- 互斥冲突与缺失层级一律记为已拒绝组合，不进入有效分配，也不补造默认值；
- 因子层级与互斥规则随分配行同时落库，下游只看分配结果也能发现冲突；
- 按实验逐个提交，中断后保留已完成实验，续跑只补未完成的实验。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "expr_factor"
LIST_FIELDS = ["因子编号", "因子名称", "因子层级", "取值集合", "分配比例", "互斥规则", "关联实验", "生效批次"]
REQUIRED_FIELDS = ["因子编号", "因子名称", "因子层级"]
STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用因子": "已停用"}
NEGATIVE_ACTIONS = ["停用因子"]

# 因子约束分配表：独立模块落库，列表入口与详情面板都读这张表，保证两边一致。
ALLOC_MODULE = "factor_alloc"
ALLOC_LIST_FIELDS = [
    "分配编号", "口径版本", "关联实验", "实验分流比例", "指标口径",
    "因子编号", "因子名称", "因子层级", "互斥规则", "分配比例",
    "组合状态", "拒绝原因", "缺失字段",
]
ALLOC_FILTER_FIELDS = ["分配编号", "口径版本", "关联实验", "因子编号", "因子名称", "组合状态"]
# 参与分配前必须齐全的因子字段；缺失一律记为拒绝，不再按空字符串放行。
ALLOC_REQUIRED_FIELDS = ["因子编号", "因子名称", "因子层级", "取值集合", "分配比例"]
ALLOC_VALID = "有效"
ALLOC_REJECTED = "已拒绝"
DEFAULT_ALLOC_VERSION = "V027"


class ExprFactorService:
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("因子编号", "")).casefold()]
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
            return None, f"因子配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于实验因子可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"因子配置已{action}"

    # ------------------------------------------------------------------
    # 因子约束分配表
    # ------------------------------------------------------------------
    def generate_allocation(
        self,
        *,
        version: str = DEFAULT_ALLOC_VERSION,
        experiment_code: str | None = None,
        resume: bool = False,
    ) -> tuple[dict[str, Any], str]:
        """按口径版本生成因子约束分配表。

        每个实验单独构建、单独提交：中断时已提交的实验保留，恢复续跑只处理
        尚未完成的实验；缺失层级保持缺失并记为拒绝，绝不补造默认值。
        """
        version = (version or "").strip() or DEFAULT_ALLOC_VERSION
        experiments = store.rows("experiment")
        if experiment_code:
            experiments = [e for e in experiments if str(e.get("方案编号", "")).strip() == experiment_code]
            if not experiments:
                return ({"version": version, "interrupted": False, "completed": [],
                         "generated": 0, "rejected": 0},
                        f"实验 {experiment_code} 不存在，无法生成分配表")
        factors = store.rows(MODULE)
        alloc_rows = store.rows(ALLOC_MODULE)
        calib = self._metric_calib(version)
        next_id = store.next_id(ALLOC_MODULE)
        completed: list[str] = []
        generated = 0
        rejected = 0
        interrupted = False
        interrupt_message = ""
        for experiment in experiments:
            code = str(experiment.get("方案编号", "")).strip()
            if not code:
                continue
            if resume and any(
                row.get("口径版本") == version and row.get("关联实验") == code for row in alloc_rows
            ):
                continue  # 续跑：保留已完成实验，不重复生成
            try:
                new_rows = self._build_experiment_rows(experiment, factors, version, calib)
            except Exception as exc:  # 中断：已提交实验保留，剩余实验等重试
                interrupted = True
                interrupt_message = f"实验 {code} 分配中断：{exc}"
                break
            for row in new_rows:
                row["id"] = next_id
                row["分配编号"] = f"ALOC-{next_id:04d}"
                next_id += 1
            # 单实验事务：整批构建完成后一次性替换旧行，避免空数据残留
            alloc_rows[:] = [
                row for row in alloc_rows
                if not (row.get("口径版本") == version and row.get("关联实验") == code)
            ] + new_rows
            store.bump_version(ALLOC_MODULE)
            completed.append(code)
            generated += sum(1 for row in new_rows if row.get("组合状态") == ALLOC_VALID)
            rejected += sum(1 for row in new_rows if row.get("组合状态") == ALLOC_REJECTED)
        result = {
            "version": version,
            "resumed": resume,
            "interrupted": interrupted,
            "completed": completed,
            "generated": generated,
            "rejected": rejected,
        }
        if interrupted:
            return result, (
                f"{interrupt_message}；已完成 {len(completed)} 个实验的分配被保留，"
                "可重试或续跑未完成的实验"
            )
        version_rows_exist = any(row.get("口径版本") == version for row in alloc_rows)
        if not completed:
            if resume and version_rows_exist:
                return result, f"{version} 的分配均已完成，没有需要续跑的实验"
            return result, f"{version} 下没有可分配的实验，分配表为空"
        if generated == 0 and rejected == 0:
            suffix = "" if version_rows_exist else "，分配表为空"
            return result, f"{version} 本次没有命中任何实验因子{suffix}"
        return result, f"{version} 因子约束分配表已生成：有效 {generated} 条，已拒绝 {rejected} 条"

    def _build_experiment_rows(
        self,
        experiment: dict[str, Any],
        factors: list[dict[str, Any]],
        version: str,
        calib: str,
    ) -> list[dict[str, Any]]:
        """构建单个实验的分配行；先校验互斥与空值边界，再决定有效或拒绝。"""
        code = str(experiment.get("方案编号", "")).strip()
        ratio = str(experiment.get("分流比例") or "").strip()
        linked = [f for f in factors if str(f.get("关联实验", "")).strip() == code]
        # 互斥分组：同一实验下互斥规则相同的因子不能同时进入有效分配
        groups: dict[str, list[dict[str, Any]]] = {}
        for factor in linked:
            rule = str(factor.get("互斥规则") or "").strip()
            if rule:
                groups.setdefault(rule, []).append(factor)
        conflict_reason: dict[int, str] = {}
        for rule, members in groups.items():
            if len(members) < 2:
                continue
            codes = "、".join(str(m.get("因子编号", "")) for m in members)
            for member in members:
                conflict_reason[id(member)] = (
                    f"互斥因子冲突：{codes} 同属互斥规则「{rule}」，不能同时进入同一实验"
                )
        rows: list[dict[str, Any]] = []
        for factor in linked:
            missing = [
                field for field in ALLOC_REQUIRED_FIELDS
                if not str(factor.get(field) or "").strip()
            ]
            reasons: list[str] = []
            if id(factor) in conflict_reason:
                reasons.append(conflict_reason[id(factor)])
            if missing:
                reasons.append("缺失必填字段：" + "、".join(missing))
            rejected = bool(reasons)
            rows.append({
                "口径版本": version,
                "关联实验": code,
                "experiment_id": experiment.get("id"),
                "factor_id": factor.get("id"),
                "实验分流比例": ratio,
                "指标口径": calib,
                "因子编号": str(factor.get("因子编号") or ""),
                "因子名称": str(factor.get("因子名称") or ""),
                # 因子层级与互斥规则同时落库；缺失就保持缺失，不补造默认值
                "因子层级": str(factor.get("因子层级") or ""),
                "互斥规则": str(factor.get("互斥规则") or ""),
                "取值集合": str(factor.get("取值集合") or ""),
                "分配比例": str(factor.get("分配比例") or ""),
                "组合状态": ALLOC_REJECTED if rejected else ALLOC_VALID,
                "拒绝原因": "；".join(reasons),
                "缺失字段": missing,
                "status": ALLOC_REJECTED if rejected else ALLOC_VALID,
                "pending": False,
                "abnormal": rejected,
            })
        return rows

    def _metric_calib(self, version: str) -> str:
        """读取该口径版本下的指标口径，随分配行落库供下游核对。"""
        for row in store.rows("metric_def"):
            if str(row.get("口径版本", "")).strip() == version:
                return str(row.get("计算公式") or "")
        return ""

    def list_allocation(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        version: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(ALLOC_MODULE)
        if version:
            rows = [row for row in rows if row.get("口径版本") == version]
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [
                row for row in rows
                if keyword.casefold() in str(row.get("因子编号", "")).casefold()
                or keyword.casefold() in str(row.get("分配编号", "")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("组合状态") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_allocation(self, alloc_id: int) -> dict[str, Any] | None:
        return store.find(ALLOC_MODULE, alloc_id)
